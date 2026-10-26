"""Source + isolated JS helper guards; no Core imports/build or Windows runtime proof."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CS = ROOT / 'src/Zagent.Core/Dashboard/DashboardProfileAdministration.cs'
JS = ROOT / 'src/Zagent.Core/wwwroot/dashboard.js'
HINT = ('Use authenticated local-owner diagnostics with this request ID to check owner profile authorization, '
        'private management connectivity, and catalog validation. This response does not identify the failed check '
        'or prove Files is stopped. Do not bypass authorization. For uncertain mutations, retain the same payload and idempotency key.')


class DashboardProfileDiagnosticsSource(unittest.TestCase):
    def test_invalid_data_exception_reaches_bounded_administrator_envelope(self):
        text = CS.read_text(encoding='utf-8')
        catch_filter = text.split('private static bool DependencyFailure(Exception ex) =>', 1)[1].split(';', 1)[0]
        # InvalidDataException derives from SystemException, NOT IOException.
        self.assertRegex(catch_filter, r'\bInvalidDataException\b')
        self.assertEqual(text.count('DependencyStage(ex)'), 3)
        stage_helper = text.split('private static string DependencyStage(Exception ex)', 1)[1].split('private static bool DependencyFailure', 1)[0]
        self.assertIn('ex.Data["ZagentProfileStage"] as string', stage_helper)
        self.assertIn('"OWNER_BINDING" or "PRIVATE_REQUEST" or "RESPONSE_VALIDATION" => stage', stage_helper)
        self.assertIn('_ => "UNKNOWN"', stage_helper)
        self.assertNotRegex(stage_helper, r'\.(Message|ToString|StackTrace)|InnerException')
        self.assertIn('["stage"] = stage', text)
        self.assertIn('string stage = "UNKNOWN"', text)
        self.assertIn('"Backend did not report a committed profile outcome.", "RESPONSE_VALIDATION")', text)
        self.assertEqual(text.count('.RequireAuthorization("Administrator")'), 6)

    def test_problem_extensions_are_static_and_preserve_route_semantics(self):
        text = CS.read_text(encoding='utf-8')
        self.assertIn(f'private const string DependencyHint = "{HINT}";', text)
        self.assertIn('private static IResult DependencyProblem(HttpContext ctx, int statusCode, string title, string stage = "UNKNOWN")', text)
        helper = text.split('private static IResult DependencyProblem', 1)[1].split('private static string Actor', 1)[0]
        self.assertIn('Results.Problem(statusCode: statusCode, title: title,', helper)
        self.assertIn('["requestId"] = ctx.TraceIdentifier', helper)
        self.assertIn('["hint"] = DependencyHint', helper)
        self.assertIn('["stage"] = stage', helper)
        for forbidden in ('ex.', 'Exception', 'Identity', 'Request.Headers', 'Results.Ok', 'code ='):
            self.assertNotIn(forbidden, helper)
        for status, title in (
            (503, 'Trusted profile catalog unavailable; no local fallback.'),
            (503, 'Trusted profile unavailable.'),
            (502, 'Backend did not report a committed profile outcome.'),
            (503, 'Profile outcome unavailable. Retry only the same payload and idempotency key.'),
        ):
            stage = '"RESPONSE_VALIDATION"' if status == 502 else 'DependencyStage(ex)'
            self.assertIn(f'DependencyProblem(ctx, {status}, "{title}", {stage})', text)
        self.assertEqual(text.count('.RequireAuthorization("Administrator")'), 6)
        self.assertEqual(text.count('.RequireRateLimiting("commands")'), 4)
        self.assertIn('ex.Code is "REVISION_CONFLICT" or "IDEMPOTENCY_CONFLICT" ? 409 : 400', text)
        self.assertIn('if (revision.Length != 64 || !revision.All(Uri.IsHexDigit)) return Results.StatusCode(428);', text)
        self.assertIn('request["expected_revision"] = revision; request["idempotency_key"] = key;', text)
        self.assertNotRegex(text, r'ex\.(Message|ToString|StackTrace)')

    def test_ui_failure_stages_in_isolated_node_request_harness(self):
        text = JS.read_text(encoding='utf-8')
        # Execute only the actual request helper; never load the dashboard or product runtime.
        preamble = text.split('let csrf,', 1)[0]
        request = 'async function request(' + text.split('async function request(', 1)[1].split('async function mutate(', 1)[0]
        notice_match = re.search(r'^function notice\(.*$', text, re.MULTILINE)
        assert notice_match is not None
        notice = notice_match.group(0)
        harness = r'''
const assert = require('node:assert/strict');
const target = { textContent: '', classList: { toggle() {} } };
const $ = () => target;
let calls = 0;
async function message(failure, status = 503) {
  global.fetch = async () => { calls++; return { status, ok: false, json: async () => failure }; };
  try { await request('workspaces'); assert.fail('must reject'); }
  catch (error) { assert.equal(error.status, status); notice(error.message, true); return target.textContent; }
}
(async () => {
  for (const stage of ['OWNER_BINDING', 'PRIVATE_REQUEST', 'RESPONSE_VALIDATION', 'UNKNOWN']) {
    const before = calls;
    const value = await message({stage, hint: profileDependencyHint, requestId: 'safe-ID:1'});
    assert.ok(value.includes(`Failure stage: ${stage}.`), value);
    assert.ok(value.includes('Request ID: safe-ID:1.'));
    assert.ok(value.includes(profileDependencyHint));
    assert.equal(calls, before + 1, 'never auto retry');
  }
  for (const stage of [undefined, null, 3, {}, ['OWNER_BINDING'], 'owner_binding', '<img onerror=secret>', 'OWNER_BINDING\nsecret']) {
    const value = await message({stage, hint: profileDependencyHint});
    assert.ok(!value.includes('Failure stage:'), value);
    assert.ok(!value.includes('secret'), value);
  }
  for (const failure of [null, {}, {stage:'OWNER_BINDING'},
      {stage:'PRIVATE_REQUEST', hint:'<script>secret</script>', requestId:'<img>secret', code:'<b>secret'},
      {title:'secret', detail:'secret', message:'secret', stage:'arbitrary-secret'}]) {
    const value = await message(failure);
    assert.ok(!value.includes('Failure stage:'), value);
    assert.ok(!value.includes('secret'), value);
  }
  assert.ok((await message({code:'DEPENDENCY_UNAVAILABLE'})).includes('DEPENDENCY_UNAVAILABLE'));
  assert.ok((await message({stage:'RESPONSE_VALIDATION', hint:profileDependencyHint}, 502)).includes('Failure stage: RESPONSE_VALIDATION.'));
  console.log('isolated request stage/textContent checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node'], input=preamble + request + notice + harness,
                                text=True, capture_output=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ui_accepts_only_literal_hint_and_bounded_request_id_as_text(self):
        text = JS.read_text(encoding='utf-8')
        self.assertIn(f"const profileDependencyHint = '{HINT}';", text)
        request = text.split('async function request(', 1)[1].split('async function mutate(', 1)[0]
        self.assertIn('failure?.hint === profileDependencyHint', request)
        self.assertIn('typeof failure?.requestId === \'string\'', request)
        self.assertIn('/^[A-Za-z0-9_.:-]{1,128}$/.test(failure.requestId)', request)
        self.assertIn('Request ID: ${failure.requestId}', request)
        self.assertIn('${code}; no success is assumed.${requestId}${stage}${hint}', request)
        self.assertIn("['OWNER_BINDING', 'PRIVATE_REQUEST', 'RESPONSE_VALIDATION', 'UNKNOWN'].includes(failure?.stage)", request)
        self.assertNotIn('failure.title', request)
        self.assertNotIn('failure.detail', request)
        self.assertIn("$('notice').textContent = text", text)
        self.assertIn("$('freshness').textContent = 'OFFLINE / UNAVAILABLE — previous data is stale. ' + e.message", text)
        self.assertNotRegex(text, r'innerHTML|outerHTML|insertAdjacentHTML')
        self.assertIn("'Idempotency-Key': cmd.key, 'If-Match': cmd.revision", text)
        self.assertIn('}, body: cmd.body', text)
        self.assertIn("$('notice').append(button('Retry exact command', sendProfileCommand))", text)
        self.assertIn('error.profileUncertain = true;', text)


if __name__ == '__main__':
    unittest.main()

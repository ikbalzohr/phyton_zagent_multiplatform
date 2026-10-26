"""Source guards only: no Core imports/build or Windows runtime verification."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CS = ROOT / 'src/Zagent.Core/Dashboard/DashboardProfileAdministration.cs'
JS = ROOT / 'src/Zagent.Core/wwwroot/dashboard.js'
HINT = ('Use authenticated local-owner diagnostics with this request ID to check owner profile authorization, '
        'private management connectivity, and catalog validation. This response does not identify the failed check '
        'or prove Files is stopped. Do not bypass authorization. For uncertain mutations, retain the same payload and idempotency key.')


class DashboardProfileDiagnosticsSource(unittest.TestCase):
    def test_problem_extensions_are_static_and_preserve_route_semantics(self):
        text = CS.read_text(encoding='utf-8')
        self.assertIn(f'private const string DependencyHint = "{HINT}";', text)
        self.assertIn('private static IResult DependencyProblem(HttpContext ctx, int statusCode, string title)', text)
        helper = text.split('private static IResult DependencyProblem', 1)[1].split('private static string Actor', 1)[0]
        self.assertIn('Results.Problem(statusCode: statusCode, title: title,', helper)
        self.assertIn('["requestId"] = ctx.TraceIdentifier', helper)
        self.assertIn('["hint"] = DependencyHint', helper)
        for forbidden in ('ex.', 'Exception', 'Identity', 'Request.Headers', 'Results.Ok', 'code ='):
            self.assertNotIn(forbidden, helper)
        for status, title in (
            (503, 'Trusted profile catalog unavailable; no local fallback.'),
            (503, 'Trusted profile unavailable.'),
            (502, 'Backend did not report a committed profile outcome.'),
            (503, 'Profile outcome unavailable. Retry only the same payload and idempotency key.'),
        ):
            self.assertIn(f'DependencyProblem(ctx, {status}, "{title}")', text)
        self.assertEqual(text.count('.RequireAuthorization("Administrator")'), 6)
        self.assertEqual(text.count('.RequireRateLimiting("commands")'), 4)
        self.assertIn('ex.Code is "REVISION_CONFLICT" or "IDEMPOTENCY_CONFLICT" ? 409 : 400', text)
        self.assertIn('if (revision.Length != 64 || !revision.All(Uri.IsHexDigit)) return Results.StatusCode(428);', text)
        self.assertIn('request["expected_revision"] = revision; request["idempotency_key"] = key;', text)
        self.assertNotRegex(text, r'ex\.(Message|ToString|StackTrace)')

    def test_ui_accepts_only_literal_hint_and_bounded_request_id_as_text(self):
        text = JS.read_text(encoding='utf-8')
        self.assertIn(f"const profileDependencyHint = '{HINT}';", text)
        request = text.split('async function request(', 1)[1].split('async function mutate(', 1)[0]
        self.assertIn('failure?.hint === profileDependencyHint', request)
        self.assertIn('typeof failure?.requestId === \'string\'', request)
        self.assertIn('/^[A-Za-z0-9_.:-]{1,128}$/.test(failure.requestId)', request)
        self.assertIn('Request ID: ${failure.requestId}', request)
        self.assertIn('${code}; no success is assumed.${requestId}${hint}', request)
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

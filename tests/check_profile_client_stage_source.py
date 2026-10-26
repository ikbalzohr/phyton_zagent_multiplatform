"""Source-only stage guards; no product imports, C# build, or Windows runtime proof."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'src/Zagent.Core/Manager/ProfileAdministrationClient.cs'


class ProfileClientStageSource(unittest.TestCase):
    def setUp(self):
        self.text = CLIENT.read_text(encoding='utf-8')
        self.send = self.text.split('private async Task<JsonObject> SendAsync(', 1)[1].split(
            'public static JsonObject DecodeResponse(', 1)[0]

    def boundary(self, stage):
        # Inspect real scoped catches rather than accepting disconnected stage literals.
        matches = list(re.finditer(
            r'try\s*\{(?P<body>.*?)\}\s*catch\s*\(System\.Exception ex\)\s*\{'
            r'\s*ex\.Data\["ZagentProfileStage"\]\s*=\s*"(?P<stage>[A-Z_]+)";'
            r'\s*throw;\s*\}', self.send, re.S))
        selected = [m for m in matches if m['stage'] == stage]
        self.assertEqual(len(selected), 1, f'missing exception-preserving {stage} boundary')
        return selected[0]['body']

    def test_owner_binding_is_tagged_at_binding_call_only(self):
        body = self.boundary('OWNER_BINDING')
        self.assertEqual(body.strip(), 'binding = _binding();')
        self.assertNotIn('throw ex;', self.send)
        self.assertNotIn('new Exception', self.send)

    def test_private_request_covers_send_status_read_and_size_not_decode_or_secrets(self):
        body = self.boundary('PRIVATE_REQUEST')
        for required in (
            '_http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)',
            'response.EnsureSuccessStatusCode();',
            'response.Content.ReadAsStreamAsync(cancellationToken)',
            'stream.ReadAsync(buffer, cancellationToken)',
            'bytes.Length + count > 262144',
            'throw new InvalidDataException("Private profile response too large.");',
            'responseBytes = bytes.ToArray();',
        ):
            self.assertIn(required, body)
        for excluded in ('_binding()', 'BuildContext(', 'GetChildSecret(', 'DecodeResponse('):
            self.assertNotIn(excluded, body)
        self.assertIn('request.Headers.Add("X-Zagent-Internal-Token", '
                      'InternalManagementChannel.GetChildSecret("ZAGENT_INTERNAL_TOKEN"));', self.send)

    def test_response_validation_is_scoped_to_decode_and_tags_are_literal_only(self):
        body = self.boundary('RESPONSE_VALIDATION')
        self.assertEqual(body.strip(), 'outcome = DecodeResponse(responseBytes);')
        tags = re.findall(r'ex\.Data\["ZagentProfileStage"\]\s*=\s*([^;]+);', self.text)
        self.assertEqual(tags, ['"OWNER_BINDING"', '"PRIVATE_REQUEST"', '"RESPONSE_VALIDATION"'])
        # All catches annotate the original exception and use bare rethrow, including
        # InvalidDataException and OperationCanceledException (no wrapper/filter).
        self.assertEqual(self.send.count('catch ('), 3)
        self.assertEqual(self.send.count('catch (System.Exception ex)'), 3)
        self.assertEqual(self.send.count('throw;'), 3)
        self.assertNotRegex(self.send, r'ex\.(Message|StackTrace|ToString)|\b(Log|Console)\b')
        self.assertIn('if (action is null) outcome["default_profile_id"]', self.send)
        decode = self.text.split('public static JsonObject DecodeResponse(', 1)[1].split(
            'public void Dispose()', 1)[0]
        self.assertIn('OwnerProfileAdministrationBinding.RejectDuplicates(strict.RootElement);', decode)
        self.assertIn('throw new ProfileAdministrationDeniedException(code);', decode)
        self.assertIn('throw new InvalidDataException("Missing authoritative catalog revision.");', decode)


if __name__ == '__main__':
    unittest.main()

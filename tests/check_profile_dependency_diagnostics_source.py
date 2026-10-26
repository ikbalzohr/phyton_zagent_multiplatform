"""Non-import source guards only; Windows behavioral verification is separate."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / 'agents/tunnel/engine/router'


class ProfileDependencyDiagnosticsSource(unittest.TestCase):
    def test_public_hints_are_literal_allowlist_not_runtime_details(self):
        path = ROUTER / 'diagnostics.py'
        self.assertTrue(path.exists(), 'missing code-only safe error hints')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        mapping = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == '_PUBLIC_HINTS' for t in n.targets))
        hints = ast.literal_eval(mapping)
        self.assertEqual(set(hints), {'TOOL_NOT_AUTHORIZED', 'FILES_RESOURCE_NOT_AUTHORIZED',
            'PROFILE_MANAGEMENT_NOT_AUTHORIZED', 'PROFILE_CATALOG_NOT_CONFIGURED', 'PROFILE_CATALOG_UNAVAILABLE'})
        for hint in hints.values():
            self.assertIsInstance(hint, str)
            self.assertLessEqual(len(hint), 512)
            self.assertNotRegex(hint, r'https?://|principal_v1_|[A-Za-z]:\\')
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'public_error')
        self.assertEqual([a.arg for a in function.args.args], ['code'])
        self.assertFalse(any(isinstance(n, (ast.JoinedStr, ast.Import, ast.ImportFrom)) for n in ast.walk(function)))
        self.assertIn("_PUBLIC_HINTS.get(code)", ast.get_source_segment(path.read_text(), function) or '')

    def test_http_status_and_denial_decisions_remain_unchanged(self):
        text = (ROUTER / 'server.py').read_text()
        tree = ast.parse(text)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_auth_error')
        body = ast.get_source_segment(text, function) or ''
        self.assertIn('public_error(exc.code)', body)
        self.assertIn('status_code=exc.status', body)
        self.assertNotIn('exc.scope', body)
        self.assertIn('raise AuthorizationError("TOOL_NOT_AUTHORIZED", 403)', text)
        self.assertIn('require_profile_management(auth, placement, authorizer(), name)', text)
        self.assertIn('verify_internal_token(request.headers.get("x-zagent-internal-token", ""))', text)

    def test_catalog_failures_have_safe_private_reason_not_raw_exception(self):
        text = (ROUTER / 'registry.py').read_text()
        tree = ast.parse(text)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MCPRegistry')
        node = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'profile_catalog_snapshot')
        body = ast.get_source_segment(text, node) or ''
        self.assertIn('except httpx.HTTPStatusError', body)
        self.assertIn('except httpx.RequestError', body)
        self.assertIn('except (ValueError, TypeError, AttributeError, KeyError)', body)
        self.assertNotIn('str(exc)', body)
        for reason in ('PRIVATE_CHANNEL_REJECTED', 'TRANSPORT_UNAVAILABLE', 'RPC_ERROR', 'DOMAIN_ERROR', 'INVALID_RESPONSE', 'RESPONSE_RECEIVED'):
            self.assertIn(repr(reason), body)
        self.assertIn("'profile_catalog_diagnostic': state.profile_catalog_diagnostic", text)
        self.assertIn("raise AuthorizationError('PROFILE_CATALOG_UNAVAILABLE', 503) from None", body)
        self.assertIn("raise AuthorizationError('PROFILE_CATALOG_NOT_CONFIGURED', 503)", body)


if __name__ == '__main__':
    unittest.main()

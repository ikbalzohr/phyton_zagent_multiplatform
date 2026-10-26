"""Textual wiring guard, not Windows ACL/runtime evidence."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
HOST = (ROOT / 'src/Zagent.Core/Dashboard/DashboardHost.cs').read_text()

class OwnerWiring(unittest.TestCase):
    def test_owner_auth_replaces_form_login_without_anonymous_routes(self):
        self.assertIn('AddScheme<AuthenticationSchemeOptions, DashboardOwnerAuthenticationHandler>', HOST)
        self.assertIn('DashboardOwnerIdentity.Capture', HOST)
        self.assertNotIn('AddCookie(', HOST)
        self.assertNotIn('AllowAnonymous', HOST)
        self.assertNotIn('MapPost("/auth/login"', HOST)
        self.assertIn('RequireAuthenticatedUser()', HOST)
        self.assertIn('RequireRole("Administrator")', HOST)
        for guard in ['DashboardSecurity.IsExpectedHost', 'IPAddress.IsLoopback(address)',
                      'DashboardSecurity.IsSameOrigin', 'ValidateRequestAsync(ctx)',
                      'RequireRateLimiting("commands")', 'ProtectKeysWithDpapi']:
            self.assertIn(guard, HOST)
    def test_open_after_listener_started(self):
        self.assertIn('app.Lifetime.ApplicationStarted.Register', HOST)
        self.assertIn('UseShellExecute = true', HOST)
        self.assertEqual(HOST.count('Process.Start('), 1)

if __name__ == '__main__':
    unittest.main()

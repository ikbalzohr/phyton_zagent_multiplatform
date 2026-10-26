#!/usr/bin/env python3
"""Static local-owner dashboard guards; runtime handler tests are separate."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'src/Zagent.Core'
HOST = (CORE / 'Dashboard/DashboardHost.cs').read_text(encoding='utf-8')
LOGIN = (CORE / 'Pages/Login.cshtml').read_text(encoding='utf-8')
JS = (CORE / 'wwwroot/dashboard.js').read_text(encoding='utf-8')
INDEX = (CORE / 'Pages/Index.cshtml').read_text(encoding='utf-8')

class LoginUiSourceChecks(unittest.TestCase):
    def test_no_anonymous_stylesheet_or_management_bypass(self):
        self.assertNotIn('.AllowAnonymous()', HOST)
        self.assertNotIn('AllowAnonymousToPage', HOST)
        self.assertIn('app.UseStaticFiles(', HOST)
        self.assertLess(HOST.index('app.UseAuthorization()'), HOST.index('app.UseStaticFiles('))

    def test_local_owner_replaces_form_login_and_logout(self):
        self.assertIn('Response.Redirect("/")', LOGIN)
        self.assertNotIn('<form', LOGIN)
        self.assertNotIn('/auth/login', HOST)
        self.assertNotIn('/auth/logout', HOST + JS)
        self.assertNotIn("location.assign('/Login')", JS)
        self.assertNotIn('id="logout"', INDEX)
        self.assertIn('DashboardOwnerIdentity.Capture', HOST)
        self.assertIn('DashboardOwnerAuthenticationHandler.SchemeName', HOST)

    def test_security_guards_remain_in_pipeline(self):
        for guard in (
            'auth.FallbackPolicy = new AuthorizationPolicyBuilder().RequireAuthenticatedUser().Build()',
            'app.UseAuthentication(); app.UseAuthorization();',
            'DashboardSecurity.IsExpectedHost', 'IPAddress.IsLoopback(address)',
            'DashboardSecurity.IsSameOrigin', 'ValidateRequestAsync(ctx)',
            'af.Cookie.SecurePolicy = CookieSecurePolicy.Always',
            'af.Cookie.SameSite = SameSiteMode.Strict',
            "style-src 'self'", 'ctx.Response.Headers.CacheControl = "no-store"',
        ):
            self.assertIn(guard, HOST)
        self.assertLess(HOST.index('DashboardSecurity.IsExpectedHost'), HOST.index('app.UseRouting()'))

    def test_assets_copy_to_windows_build_and_publish_output(self):
        project = ET.parse(CORE / 'Zagent.Core.csproj').getroot()
        assets = next(e for e in project.iter('Content') if e.attrib.get('Update') == 'wwwroot\\**\\*')
        self.assertEqual(assets.attrib['CopyToOutputDirectory'], 'PreserveNewest')
        self.assertEqual(assets.attrib['CopyToPublishDirectory'], 'PreserveNewest')

if __name__ == '__main__':
    unittest.main(verbosity=2)

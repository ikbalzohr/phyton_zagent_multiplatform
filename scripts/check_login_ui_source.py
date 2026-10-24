#!/usr/bin/env python3
"""Static login UI regression guards; NOT a C# build or HTTP/runtime test."""
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/Zagent.Core"
HOST = (CORE / "Dashboard/DashboardHost.cs").read_text(encoding="utf-8")
LOGIN = (CORE / "Pages/Login.cshtml").read_text(encoding="utf-8")
CSS = (CORE / "wwwroot/dashboard.css").read_text(encoding="utf-8")


class LoginMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class LoginUiSourceChecks(unittest.TestCase):
    def test_stylesheet_has_exact_anonymous_get_head_endpoint(self):
        # StaticFileMiddleware after fallback authorization cannot serve an
        # anonymous request without endpoint AllowAnonymous metadata.
        self.assertRegex(HOST, re.compile(
            r'app\.MapMethods\("/dashboard\.css",\s*\["GET",\s*"HEAD"\],\s*'
            r'\(\)\s*=>\s*Results\.File\(\s*'
            r'Path\.Combine\(app\.Environment\.WebRootPath,\s*"dashboard\.css"\),\s*'
            r'contentType:\s*"text/css"\)\)\.AllowAnonymous\(\);', re.S))
        # No wildcard/static-directory exception or anonymous management surface.
        self.assertEqual(HOST.count(".AllowAnonymous()"), 2)
        self.assertNotIn("UseWhen", HOST)

    def test_existing_login_form_contract_remains_local_and_secret_free(self):
        markup = LoginMarkup()
        markup.feed(LOGIN)
        self.assertIn(("link", {"rel": "stylesheet", "href": "/dashboard.css"}), markup.tags)
        self.assertIn(("form", {"method": "post", "action": "/auth/login"}), markup.tags)
        self.assertIn("@Html.AntiForgeryToken()", LOGIN)
        self.assertIn('Request.Query.ContainsKey("failed")', LOGIN)
        self.assertIn('role="alert"', LOGIN)
        self.assertEqual(sum(tag == "label" for tag, _ in markup.tags), 2)
        inputs = {attrs.get("name"): attrs for tag, attrs in markup.tags if tag == "input"}
        self.assertEqual(inputs["account"]["autocomplete"], "username")
        self.assertEqual(inputs["password"]["type"], "password")
        self.assertEqual(inputs["password"]["autocomplete"], "current-password")
        for attrs in inputs.values():
            self.assertNotIn("value", attrs)
        self.assertNotRegex(LOGIN, r"<script|<style|https?://")

    def test_security_guards_remain_in_pipeline(self):
        for guard in (
            'auth.FallbackPolicy = new AuthorizationPolicyBuilder().RequireAuthenticatedUser().Build()',
            'app.UseAuthentication(); app.UseAuthorization();',
            'DashboardSecurity.IsExpectedHost', 'IPAddress.IsLoopback(address)',
            'DashboardSecurity.IsSameOrigin', 'ValidateRequestAsync(ctx)',
            'cookie.Cookie.HttpOnly = true', 'cookie.Cookie.SecurePolicy = CookieSecurePolicy.Always',
            'cookie.Cookie.SameSite = SameSiteMode.Strict',
            'Results.Redirect("/Login?failed=1")',
            '}).AllowAnonymous().RequireRateLimiting("login");',
            "style-src 'self'", 'ctx.Response.Headers.CacheControl = "no-store"',
        ):
            self.assertIn(guard, HOST)
        self.assertLess(HOST.index("DashboardSecurity.IsExpectedHost"), HOST.index("app.UseRouting()"))
        self.assertLess(HOST.index("app.UseAuthorization()"), HOST.index("app.UseStaticFiles("))

    def test_assets_copy_to_windows_build_and_publish_output(self):
        project = ET.parse(CORE / "Zagent.Core.csproj").getroot()
        assets = next(e for e in project.iter("Content") if e.attrib.get("Update") == "wwwroot\\**\\*")
        self.assertEqual(assets.attrib["CopyToOutputDirectory"], "PreserveNewest")
        self.assertEqual(assets.attrib["CopyToPublishDirectory"], "PreserveNewest")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Offline packaging checks only; fixture URLs are not real deployment evidence."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import os
import sys
import unittest
import shutil
import render


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            'issuer_origin': 'https://auth.zagent-fixture.net',
            'resource_uri': 'https://windows.zagent-fixture.net/mcp',
            'redirect_uri': 'http://127.0.0.1:8765/callback',
            'secret_dir': '/root/fixture-oauth/secrets',
            'tls_certificate': '/etc/fixture/fullchain.pem',
            'tls_certificate_key': '/etc/fixture/privkey.pem'}

    def test_realm_is_least_privilege(self):
        realm, nginx, proxy, issuer, directory = render.render(self.config)
        interactive, chatgpt, introspection = realm['clients']
        self.assertEqual(interactive['redirectUris'], [self.config['redirect_uri']])
        self.assertEqual(interactive['attributes']['pkce.code.challenge.method'], 'S256')
        self.assertTrue(interactive['publicClient'])
        self.assertEqual(interactive['optionalClientScopes'], ['files:read', 'offline_access'])
        self.assertEqual(chatgpt['clientId'], 'chatgpt-zagent-mp')
        self.assertEqual(chatgpt['redirectUris'],
                         ['https://chatgpt.com/connector_platform_oauth_redirect'])
        self.assertTrue(chatgpt['publicClient'])
        self.assertTrue(chatgpt['consentRequired'])
        self.assertEqual(chatgpt['attributes']['pkce.code.challenge.method'], 'S256')
        self.assertFalse(chatgpt['directAccessGrantsEnabled'])
        self.assertFalse(introspection['publicClient'])
        self.assertEqual(introspection['attributes']['resource_url'], self.config['resource_uri'])
        self.assertFalse(introspection['standardFlowEnabled'])
        self.assertFalse(introspection['serviceAccountsEnabled'])
        self.assertEqual(introspection['secret'], '${ZAGENT_INTROSPECTION_SECRET}')
        for client in realm['clients']:
            for key in ('implicitFlowEnabled', 'directAccessGrantsEnabled', 'fullScopeAllowed'):
                self.assertFalse(client[key])
        audience = realm['clientScopes'][-1]['protocolMappers'][0]['config']
        self.assertEqual(audience['included.custom.audience'], self.config['resource_uri'])
        self.assertEqual(audience['introspection.token.claim'], 'true')
        self.assertEqual(realm['users'], [])
        self.assertFalse(realm['registrationAllowed'])
        self.assertIn('location / { return 404; }', nginx)
        self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;', proxy)
        self.assertIn('proxy_set_header Forwarded "";', proxy)
        self.assertNotIn('proxy_add_x_forwarded_for', proxy)

    def test_execute_scope_exists_without_implicit_client_approval(self):
        realm, *_ = render.render(self.config)
        self.assertIn('files:execute', {s['name'] for s in realm['clientScopes']})
        self.assertNotIn('files:execute', realm['clients'][0]['optionalClientScopes'])
        self.assertNotIn('files:write', realm['clients'][0]['optionalClientScopes'])

    def test_access_token_has_subject_and_both_resource_audiences(self):
        realm, *_ = render.render(self.config)
        scope = next(s for s in realm['clientScopes'] if s['name'] == 'zagent-resource-audience')
        audience = next(m for m in scope['protocolMappers'] if m['protocolMapper'] == 'oidc-audience-mapper')
        self.assertNotIn('included.client.audience', audience['config'])
        self.assertEqual(audience['config']['included.custom.audience'], self.config['resource_uri'])
        introspection = next((m for m in scope['protocolMappers'] if m['name'] == 'zagent-introspection-audience'), {})
        self.assertTrue(introspection, 'Keycloak introspection requires its client ID in the audience')
        self.assertEqual(introspection['config']['included.client.audience'], 'zagent-resource-server')
        self.assertNotIn('included.custom.audience', introspection['config'])
        self.assertEqual(introspection['config']['access.token.claim'], 'true')
        self.assertEqual(introspection['config']['introspection.token.claim'], 'true')
        subject = next((m for m in scope['protocolMappers'] if m['protocolMapper'] == 'oidc-sub-mapper'), {})
        self.assertTrue(subject, 'Keycloak 25+ requires an explicit subject mapper')
        self.assertEqual(subject['config']['access.token.claim'], 'true')
        self.assertEqual(subject['config']['introspection.token.claim'], 'true')
        self.assertEqual(realm['clients'][0]['optionalClientScopes'], ['files:read', 'offline_access'])

    def test_placeholders_and_unsafe_urls_are_blocked(self):
        for field, values in {
            'issuer_origin': ['REQUIRED', 'http://auth.site.net', 'https://auth.example',
                              'https://user:pass@auth.site.net', 'https://auth.site.net/',
                              'https://127.0.0.1', 'https://auth.site.net/realms/zagent'],
            'resource_uri': ['https://resource.site.net/mcp?x=1', 'https://resource.site.net/*', 'https://resource.site.net/other'],
            'chatgpt_redirect_uri': ['https://evil.site.net/connector_platform_oauth_redirect',
                                     'https://chatgpt.com/connector/oauth/unknown', 'http://chatgpt.com/connector_platform_oauth_redirect'],
            'redirect_uri': ['http://localhost:8765/callback', 'http://127.0.0.1/callback',
                             'http://127.0.0.1:8765/*', 'https://redirect.site.net/*'],
            'secret_dir': [str(render.HERE / 'secrets'), 'relative', '/unsafe\npath'],
            'tls_certificate': ['/certs/file;include']}.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    c = copy.deepcopy(self.config)
                    c[field] = value
                    with self.assertRaises(ValueError):
                        render.render(c)

    def test_checked_in_example_is_not_deployable(self):
        example = json.loads((render.HERE / 'deployment.example.json').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):
            render.render(example)

    @unittest.skipIf(os.name == 'nt', 'Linux-only protected absolute path and output file-mode test')
    def test_cli_renders_files_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as scratch:
            config = Path(scratch) / 'fixture.json'
            config.write_text(json.dumps(self.config))
            output = Path(scratch) / 'rendered'
            command = [sys.executable, str(render.HERE / 'render.py'), str(config), '--output', str(output)]
            first = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(len(list(output.iterdir())), 5)
            reviewed = json.loads((output / 'cimd-policy-review.json').read_text(encoding='utf-8'))
            self.assertEqual(reviewed['status'], 'OWNER_REVIEW_REQUIRED_NOT_APPLIED')
            self.assertEqual([p['name'] for p in reviewed['client_policies']],
                             ['zmp-claude-cimd', 'zmp-hermes-cimd'])
            self.assertEqual(reviewed['resource_indicator_allow_list'],
                             [self.config['resource_uri']])
            for item in output.iterdir():
                self.assertEqual(item.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((output / 'zagent-realm.json').read_text(encoding='utf-8'))['realm'], 'zagent')
            second = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(second.returncode, 2)
            self.assertIn('Output exists', second.stderr)

    def test_runtime_packaging_guards(self):
        compose = (render.HERE / 'compose.yaml').read_text(encoding='utf-8')
        containerfile = (render.HERE / 'Containerfile').read_text(encoding='utf-8')
        # Docker 29 internal networks do not publish host ports. nginx reaches
        # the fixed private address; neither DB nor Keycloak binds a host port.
        self.assertNotIn('    ports:', compose)
        self.assertIn('ipv4_address: 172.30.88.3', compose)
        self.assertIn('ipv4_address: 172.30.88.2', compose)
        self.assertEqual(compose.count("max-size: '10m'"), 2)
        self.assertEqual(compose.count("max-file: '3'"), 2)
        self.assertIn('internal: true', compose)
        self.assertNotIn('start-dev', compose + containerfile)
        self.assertIn('KC_FEATURES=cimd,resource-indicators', containerfile)
        self.assertIn('[start, --optimized, --import-realm]', compose)
        self.assertNotIn('POSTGRES_PASSWORD:', compose)
        self.assertNotIn('KC_DB_PASSWORD:', compose)
        self.assertIn('@sha256:', containerfile)
        self.assertIn('postgres:17-bookworm@sha256:', compose)
        if shutil.which('bash'):
            subprocess.run(['bash', '-n', str(render.HERE / 'start.sh')], check=True)
        else:
            self.skipTest('bash is unavailable; shell syntax not validated on this host')


if __name__ == '__main__':
    unittest.main()

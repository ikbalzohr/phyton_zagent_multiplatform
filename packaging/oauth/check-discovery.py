#!/usr/bin/env python3
"""Read-only HTTPS discovery/perimeter verification AFTER approved deployment."""
import argparse
import json
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener
from render import https_url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify(origin):
    origin = https_url(origin, origin=True)
    issuer = origin + '/realms/zagent'
    opener = build_opener(NoRedirect())  # Default platform certificate/hostname checks remain enabled.
    with opener.open(issuer + '/.well-known/openid-configuration', timeout=15) as response:
        data = json.loads(response.read(65537))
    expected = {'issuer': issuer,
                'authorization_endpoint': issuer + '/protocol/openid-connect/auth',
                'token_endpoint': issuer + '/protocol/openid-connect/token',
                'introspection_endpoint': issuer + '/protocol/openid-connect/token/introspect'}
    for key, value in expected.items():
        if data.get(key) != value:
            raise ValueError('Unexpected discovery value: ' + key)
    if 'S256' not in data.get('code_challenge_methods_supported', []):
        raise ValueError('PKCE S256 not advertised')
    for path in ('/admin/', '/admin/realms', '/realms/master/.well-known/openid-configuration',
                 '/health/ready', '/metrics', '/realms/zagent/clients-registrations/openid-connect'):
        try:
            with opener.open(origin + path, timeout=15) as response:
                raise ValueError('Private endpoint exposed: ' + path)
        except HTTPError as error:
            if error.code != 404:
                raise ValueError('Expected perimeter 404: ' + path) from error
    print('PASS: trusted HTTPS discovery, exact issuer/endpoints, PKCE advertisement, private-path 404s')
    print('NOT VERIFIED: login, code exchange, refresh, introspection claims, Windows grants, MCP tools')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('issuer_origin')
    args = parser.parse_args()
    try:
        verify(args.issuer_origin)
    except Exception as error:
        parser.exit(2, f'BLOCKED: {type(error).__name__}: {error}\n')

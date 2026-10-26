#!/usr/bin/env python3
"""Interactive owner enrollment via private Keycloak Admin API; no secrets in argv/output."""
import argparse
import getpass
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--username', default='ikbal')
    args = parser.parse_args()
    if os.geteuid() != 0 or not sys.stdin.isatty():
        parser.exit(2, 'Run from the installation owner root interactive VPS terminal.\n')
    if not args.username or len(args.username) > 64 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789._-' for c in args.username):
        parser.exit(2, 'Use a lowercase username containing letters, digits, dot, dash or underscore.\n')
    runtime = args.runtime
    if not runtime.is_absolute() or runtime.is_symlink():
        parser.exit(2, 'An absolute private runtime directory is required.\n')
    st = runtime.stat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
        parser.exit(2, 'Runtime must be root-owned mode 0700.\n')
    config = json.loads((runtime / 'deployment.json').read_text(encoding='utf-8'))
    issuer_origin = config['issuer_origin']
    parsed = urllib.parse.urlsplit(issuer_origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        parser.exit(2, 'Invalid configured issuer origin.\n')
    bootstrap_path = runtime / 'secrets' / 'bootstrap_password'
    if bootstrap_path.is_symlink() or stat.S_IMODE(bootstrap_path.stat().st_mode) != 0o600:
        parser.exit(2, 'Private bootstrap credential permissions are invalid.\n')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    private_origin = 'http://172.30.88.3:8080'
    base_headers = {'Host': parsed.netloc, 'X-Forwarded-Proto': 'https', 'X-Forwarded-Port': '443'}
    token = None

    def request(path, method='GET', payload=None, form=None, authenticated=True) -> Any:
        headers = dict(base_headers)
        if authenticated:
            if not isinstance(token, str) or not token:
                raise ValueError('Private administrator authentication is missing.')
            headers['Authorization'] = 'Bearer ' + token
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        elif payload is not None:
            data = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(private_origin + path, data=data, headers=headers, method=method)
        with opener.open(req, timeout=15) as response:
            body = response.read(1024 * 1024)
            return json.loads(body) if body else None

    try:
        # This is private administration, NOT the application's OAuth password grant.
        token = request('/realms/master/protocol/openid-connect/token', method='POST', form={
            'grant_type': 'password', 'client_id': 'admin-cli', 'username': 'bootstrap-admin',
            'password': bootstrap_path.read_text(encoding='utf-8').strip()}, authenticated=False)['access_token']
        query = urllib.parse.urlencode({'username': args.username, 'exact': 'true'})
        endpoint = '/admin/realms/zagent/users'
        if request(endpoint + '?' + query):
            parser.exit(2, 'Account already exists. No overwrite or password reset performed.\n')
        print('Create a non-administrator OAuth login for: ' + args.username)
        print('Password is not displayed. Use a unique password, 14-256 characters.')
        password = getpass.getpass('New OAuth password: ')
        confirmation = getpass.getpass('Confirm OAuth password: ')
        if password != confirmation or not 14 <= len(password) <= 256:
            parser.exit(2, 'Password mismatch or invalid length. No account created.\n')
        request(endpoint, method='POST', payload={
            'username': args.username, 'enabled': True,
            'firstName': 'Ikbal', 'lastName': 'Zohr',
            'requiredActions': [],
            'credentials': [{'type': 'password', 'value': password, 'temporary': False}]})
        password = confirmation = None
        users = request(endpoint + '?' + query)
        if len(users) != 1 or users[0].get('username') != args.username or users[0].get('enabled') is not True:
            parser.exit(2, 'Enrollment write completed but read-back failed; do not rerun blindly.\n')
        user_id = users[0]['id']
        roles = request(endpoint + '/' + urllib.parse.quote(user_id, safe='') + '/role-mappings')
        if any(c.get('client') == 'realm-management' for c in roles.get('clientMappings', {}).values()):
            parser.exit(2, 'Unexpected administration roles found; activation blocked.\n')
        print('OAUTH_OWNER_CREATED username=' + args.username + ' subject=' + user_id)
        print('Read-back verified. Hermes login and Windows MCP integration remain NOT_VERIFIED.')
    except urllib.error.HTTPError as error:
        # Never print response bodies: administrative errors may echo request attributes.
        parser.exit(2, 'Private Keycloak operation failed (HTTP ' + str(error.code) + '). No credentials printed.\n')
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(2, 'Private enrollment failed. Check local service/configuration; no credentials printed.\n')


if __name__ == '__main__':
    main()

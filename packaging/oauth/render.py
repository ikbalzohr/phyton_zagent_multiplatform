#!/usr/bin/env python3
"""Render NONSECRET config only. No network, secret generation or service start."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
SCOPES = ('zagent:read', 'files:read', 'files:write', 'web:control',
          'arcmap:inspect', 'arcmap:execute', 'artifacts:read')


def https_url(value, origin=False):
    if (not isinstance(value, str) or any(c.isspace() for c in value)
            or any(c in value for c in '*$\r\n\t#{};\\')):
        raise ValueError('Invalid/placeholder HTTPS URL')
    u = urlsplit(value)
    if (u.scheme != 'https' or not u.hostname or u.username or u.password
            or u.query or u.fragment or u.port not in (None, 443)
            or not re.fullmatch(r'[a-z0-9.-]+', u.hostname)
            or u.hostname.endswith(('.example', '.invalid', '.test', '.localhost'))
            or u.hostname in ('localhost', 'example.com', 'example.org', 'example.net')):
        raise ValueError('Real HTTPS DNS hostname required (not an example or local URL)')
    try:
        ipaddress.ip_address(u.hostname)
    except ValueError:
        pass
    else:
        raise ValueError('Stable DNS hostname required, not an IP address')
    if origin and (u.path or value.endswith('/')):
        raise ValueError('issuer_origin must be an HTTPS origin without trailing slash')
    return value


def absolute_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value):
        raise ValueError('Absolute paths without shell/config metacharacters required')
    path = Path(value).resolve()
    if path == HERE.parents[1] or HERE.parents[1] in path.parents:
        raise ValueError('Runtime/secret/certificate paths must be outside repository')
    return str(path)


def render(config):
    issuer = https_url(config['issuer_origin'], origin=True)
    resource = https_url(config['resource_uri'])
    redirect = config['redirect_uri']
    u = urlsplit(redirect)
    if u.scheme == 'http' and u.hostname == '127.0.0.1':
        if (not u.port or not u.path or u.username or u.password or u.query or u.fragment
                or any(c in redirect for c in '*$\r\n\t#{};\\')):
            raise ValueError('Exact loopback redirect port/path required')
    else:
        https_url(redirect)
    secret_dir = absolute_path(config['secret_dir'])
    cert = absolute_path(config['tls_certificate'])
    key = absolute_path(config['tls_certificate_key'])
    realm = json.loads((HERE / 'realm.template.json').read_text())
    client = realm['clients'][0]
    client['redirectUris'] = [redirect]
    client['defaultClientScopes'] = ['zagent-resource-audience']
    client['optionalClientScopes'] = ['files:read', 'offline_access']
    realm['clientScopes'] = [dict(name=s, protocol='openid-connect', attributes={
        'include.in.token.scope': 'true', 'display.on.consent.screen': 'true',
        'consent.screen.text': s}) for s in SCOPES]
    realm['clientScopes'].append({
        'name': 'zagent-resource-audience', 'protocol': 'openid-connect',
        'attributes': {'include.in.token.scope': 'false', 'display.on.consent.screen': 'false'},
        'protocolMappers': [{
            'name': 'exact-zagent-resource', 'protocol': 'openid-connect',
            'protocolMapper': 'oidc-audience-mapper', 'consentRequired': False,
            'config': {'included.custom.audience': resource,

                       'access.token.claim': 'true', 'id.token.claim': 'false',
                       'introspection.token.claim': 'true'}}, {
            'name': 'zagent-owner-subject', 'protocol': 'openid-connect',
            'protocolMapper': 'oidc-sub-mapper', 'consentRequired': False,
            'config': {'access.token.claim': 'true', 'introspection.token.claim': 'true'}}]})
    host = urlsplit(issuer).hostname
    nginx = f'''# Parent must validate with nginx -t before enabling; certificates already required.
server {{
    listen 443 ssl;
    server_name {host};
    ssl_certificate {cert};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 64k;
    # No tokens, codes or login query strings in access logs.
    access_log off;
    location = /realms/zagent/.well-known/openid-configuration {{ include /etc/nginx/snippets/zagent-keycloak-proxy.conf; }}
    location ^~ /realms/zagent/protocol/openid-connect/ {{ include /etc/nginx/snippets/zagent-keycloak-proxy.conf; }}
    location ^~ /realms/zagent/login-actions/ {{ include /etc/nginx/snippets/zagent-keycloak-proxy.conf; }}
    location ^~ /resources/ {{ include /etc/nginx/snippets/zagent-keycloak-proxy.conf; }}
    # master realm, Admin API/UI, health, metrics, account and DCR are NOT public.
    location / {{ return 404; }}
}}
'''
    proxy = f'''proxy_pass http://172.30.88.3:8080;
proxy_set_header Host {host};
proxy_set_header X-Forwarded-Host {host};
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-Port 443;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Prefix "";
proxy_set_header Forwarded "";
proxy_set_header X-Forwarded-Client-Cert "";
proxy_set_header X-Remote-User "";
proxy_read_timeout 60s;
'''
    return realm, nginx, proxy, issuer, secret_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        realm, nginx, proxy, issuer, secret_dir = render(json.loads(args.config.read_text()))
        output = Path(absolute_path(str(args.output)))
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        files = {
            'zagent-realm.json': json.dumps(realm, indent=2) + '\n',
            'keycloak.nginx.conf': nginx,
            'zagent-keycloak-proxy.conf': proxy,
            'deployment.env': f'ISSUER_ORIGIN={issuer}\nSECRET_DIR={secret_dir}\nREALM_FILE={output}/zagent-realm.json\n'}
        # Validate first; never silently replace runtime config.
        if any((output / name).exists() for name in files):
            raise ValueError('Output exists; use a new directory and explicitly review differences')
        for name, value in files.items():
            with (output / name).open('x') as stream:
                stream.write(value)
            (output / name).chmod(0o600)
        print('NONSECRET configuration rendered; DNS/TLS ownership and live OAuth NOT VERIFIED')
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f'BLOCKED: {error}\n')


if __name__ == '__main__':
    main()

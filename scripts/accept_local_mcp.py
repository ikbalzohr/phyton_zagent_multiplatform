#!/usr/bin/env python3
"""Windows-owner opt-in LOCAL initialize/catalog probe. Not a readiness certificate.
No launch/provisioning, remote endpoints, writes, shell tools, or token output.
Bearer comes only from ZAGENT_ACCEPTANCE_BEARER in this process environment.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='actual DataRoot/tunnel/config/tunnel.json')
    parser.add_argument('--endpoint', default='http://127.0.0.3:18810/mcp')
    parser.add_argument('--protocol', required=True, help='offered version from actual router source, not product version')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise ValueError('Windows owner console required; runtime NOT_RUN on this host')
    url = urllib.parse.urlsplit(args.endpoint)
    if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', '127.0.0.3', '::1', 'localhost')
            or url.port != 18810 or url.path != '/mcp' or url.query or url.fragment or url.username or url.password):
        raise ValueError('Only exact local router HTTP /mcp port 18810 permitted; UI 19443 is not MCP')
    with open(args.config, encoding='utf-8-sig') as stream:
        resource = json.load(stream).get('resource_server', {})
    for name in ('resource_uri', 'issuer', 'introspection_endpoint'):
        parsed = urllib.parse.urlsplit(resource.get(name, ''))
        if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname.endswith('.example'):
            raise ValueError('BLOCKED: external OAuth/resource URL not configured: ' + name)
    for name in ('authorization_servers', 'workspace_id', 'policy_revision', 'introspection_client_id', 'introspection_secret_env', 'grants'):
        if not resource.get(name):
            raise ValueError('BLOCKED: OAuth policy not configured: ' + name)
    # This client deliberately does NOT read introspection/internal secret values.
    token = os.environ.get('ZAGENT_ACCEPTANCE_BEARER', '')
    if not token or any(c.isspace() for c in token):
        raise ValueError('BLOCKED: real AS bearer must be securely supplied in process environment')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *unused, **kwargs):
            raise ValueError('Redirect refused; bearer must stay on exact local router')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    session = None
    protocol = None

    def rpc(method, params=None, identifier=None):
        nonlocal session
        body = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            body['params'] = params
        if identifier is not None:
            body['id'] = identifier
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                   'Accept': 'application/json, text/event-stream'}
        if session:
            headers['Mcp-Session-Id'] = session
        if protocol:
            headers['MCP-Protocol-Version'] = protocol
        request = urllib.request.Request(args.endpoint, json.dumps(body).encode(), headers, method='POST')
        with opener.open(request, timeout=20) as response:
            session = response.headers.get('Mcp-Session-Id') or session
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('Response exceeds acceptance cap')
            if identifier is None:
                return None
            if response.headers.get_content_type() == 'text/event-stream':
                frames = raw.decode('utf-8').replace('\r\n', '\n').split('\n\n')
                replies = [json.loads('\n'.join(line[5:].lstrip() for line in frame.splitlines() if line.startswith('data:')))
                           for frame in frames if any(line.startswith('data:') for line in frame.splitlines())]
                matches = [reply for reply in replies if reply.get('id') == identifier]
                if len(matches) != 1:
                    raise ValueError('No unique matching MCP response')
                result = matches[0]
            else:
                result = json.loads(raw)
            if result.get('jsonrpc') != '2.0' or result.get('id') != identifier or 'error' in result or 'result' not in result:
                raise ValueError('MCP rejected request or response contract mismatch (body withheld)')
            return result['result']

    initialized = rpc('initialize', {'protocolVersion': args.protocol, 'capabilities': {},
                                    'clientInfo': {'name': 'zagent-local-acceptance', 'version': '1'}}, 1)
    protocol = initialized.get('protocolVersion')
    if not isinstance(protocol, str) or protocol != args.protocol:
        raise ValueError('Protocol negotiation differs; stop and inspect actual client/server supported versions')
    rpc('notifications/initialized')
    cursor = None
    count = 0
    seen = set()
    while True:
        page = rpc('tools/list', {'cursor': cursor} if cursor else {}, 2 + count)
        tools = page.get('tools')
        if not isinstance(tools, list) or not all(isinstance(t, dict) and isinstance(t.get('name'), str) for t in tools):
            raise ValueError('Invalid catalog shape')
        count += len(tools)
        cursor = page.get('nextCursor')
        if not cursor:
            break
        if cursor in seen or len(seen) >= 100:
            raise ValueError('Catalog cursor cycle/limit')
        seen.add(cursor)
    if not count:
        raise ValueError('Empty tool catalog; no capability acceptance')
    print(json.dumps({'status': 'INITIALIZE_CATALOG_ONLY', 'protocolVersion': protocol,
                      'tool_count': count, 'files_read': 'NOT_RUN', 'files_write': 'NOT_RUN',
                      'dashboard': 'NOT_RUN', 'release_ready': False}))


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        print('BLOCKED: HTTP status ' + str(error.code) + '; response/credentials withheld', file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, KeyError, TypeError) as error:
        # Never dump server bodies, request objects or environment values.
        print('BLOCKED: ' + (str(error) if isinstance(error, ValueError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)

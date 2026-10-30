"""Offline ASGI exercise of real middleware and RPC exception boundaries."""
import asyncio
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))


class RouterDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cfg = cls.root / 'config'
        cfg.mkdir()
        for name, value in [('core_services.json', {'services': []}),
                            ('additional_services.json', {'services': []}), ('tunnel.json', {})]:
            (cfg / name).write_text(json.dumps(value), encoding='utf-8')
        cls.env = patch.dict(os.environ, {
            'ZAGENT_TUNNEL_CONFIG_DIR': str(cfg), 'ZAGENT_TUNNEL_RUNTIME_DIR': str(cls.root / 'runtime'),
            'ZAGENT_CORE_DATA_ROOT': str(cls.root / 'private')})
        cls.env.start()
        cls.server = importlib.import_module('router.server')

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        # SQLite handles on Windows remain open until interpreter exit.

    async def asyncSetUp(self):
        from router import diagnostic_events
        self.events = diagnostic_events
        self.store = diagnostic_events.EventStore('router', self.root / self.id().split('.')[-1])
        self.patches = [patch.object(diagnostic_events, 'store', self.store),
                        patch.object(self.server, '_auth_client', object())]
        for item in self.patches:
            item.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.server.app), base_url='http://fixture')

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()

    def records(self):
        path = self.store.root / 'logs/diagnostics/router.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    async def test_auth_rejection_keeps_contract_and_adds_real_correlation(self):
        response = await self.client.post('/mcp', json={'jsonrpc':'2.0','id':7,'method':'initialize'},
                                          headers={'x-request-id':'a' * 32})
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body['error']['code'], 'NOT_CONFIGURED')
        self.assertIn('data', body['error'], 'sanitized auth error lacks correlated private diagnostics')
        correlation = body['error']['data']['requestId']
        self.assertNotEqual(correlation, 'a' * 32)
        self.assertTrue(any(e['requestId'] == correlation and e['stage'] == 'auth.token' for e in self.records()))
        self.assertEqual(response.headers['cache-control'], 'no-store')

    async def test_mcp_initialize_reaches_handler_only_after_authentication(self):
        from router.access import AuthContext
        auth = AuthContext('fixture-principal', 'fixture-workspace', frozenset(), frozenset(), '1', time.time()+60)
        authenticate = AsyncMock(return_value=auth)
        with patch.object(self.server.ResourceAuthorizer, 'authenticate', authenticate):
            response = await self.client.post('/mcp',
                json={'jsonrpc':'2.0','id':17,'method':'initialize'},
                headers={'Authorization':'Bearer fixture'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('result', response.json(), 'authenticated initialize must not lose request.state.auth')
        self.assertIn('protocolVersion', response.json()['result'])
        authenticate.assert_awaited_once()
        assert authenticate.await_args is not None
        self.assertEqual(authenticate.await_args.args[0], 'Bearer fixture')
        self.assertFalse(any(e['stage'] == 'mcp.auth_context' for e in self.records()))

    async def test_tools_list_failure_preserves_jsonrpc_and_never_serializes_exception(self):
        from router.access import AuthContext
        auth = AuthContext('p','w',frozenset(),frozenset(),'1',time.time()+60)
        secret = 'Bearer raw-token /private/owner/config policy-secret'
        with patch.object(self.server.ResourceAuthorizer, 'authenticate', AsyncMock(return_value=auth)), \
                patch.object(self.server, '_visible', side_effect=RuntimeError(secret)):
            response = await self.client.post('/mcp', json={'jsonrpc':'2.0','id':7,'method':'tools/list'})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual({k:v for k,v in body['error'].items() if k != 'data'}, {'code':-32603,'message':'Request failed'})
        self.assertIn('data', body['error'], 'RPC error lacks private correlation')
        events = self.records()
        self.assertTrue(any(e['stage'] == 'mcp.tools_list' and e['requestId'] == body['error']['data']['requestId'] for e in events))
        self.assertNotIn(secret, json.dumps(events) + response.text)

    async def test_introspection_transport_failure_records_specific_safe_gate(self):
        from router.access import ResourceAuthorizer
        cfg = dict(resource_uri='https://resource.example/mcp', issuer='https://issuer.example',
                   introspection_endpoint='https://issuer.example/introspect', workspace_id='ws',
                   policy_revision='1', introspection_client_id='client', introspection_secret_env='DIAGNOSTIC_TEST_SECRET',
                   authorization_servers=['https://issuer.example'])
        def unavailable(request):
            raise httpx.ConnectError('Bearer secret /private/path', request=request)
        with patch.dict(os.environ, {'DIAGNOSTIC_TEST_SECRET':'fixture'}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
                with self.assertRaises(self.server.AuthorizationError) as caught:
                    await ResourceAuthorizer(cfg).authenticate('Bearer fixture', client)
        self.assertEqual(caught.exception.code, 'authorization_unavailable')
        self.assertTrue(any(e['stage'] == 'auth.introspection' and e['code'] == 'AUTH_INTROSPECTION_FAILED' for e in self.records()))
        self.assertNotIn('secret', json.dumps(self.records()))

    async def test_direct_initialize_missing_request_auth_is_correlated_not_assumed_healthy(self):
        from starlette.requests import Request
        payload = json.dumps({'jsonrpc':'2.0','id':9,'method':'initialize'}).encode()
        async def receive():
            return {'type':'http.request','body':payload,'more_body':False}
        request = Request({'type':'http','method':'POST','path':'/mcp','headers':[(b'content-type',b'application/json')]}, receive)
        response = await self.server.mcp(request)
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body['error']['code'], -32603)
        self.assertTrue(any(e['stage'] == 'mcp.initialize' and e['requestId'] == body['error']['data']['requestId'] for e in self.records()))
        self.assertTrue(any(e['stage'] == 'mcp.auth_context' and e['code'] == 'AUTH_REQUIRED'
                            and e['requestId'] == body['error']['data']['requestId'] for e in self.records()))

    async def test_job_exception_is_safe_and_read_write_states_preserved(self):
        from router.orchestration import Orchestrator
        secret = 'Bearer raw-job-token /private/job/path'
        async def fail(*args):
            raise RuntimeError(secret)
        for mode, state in [('read', 'failed'), ('write', 'orphaned')]:
            runner = Orchestrator(fail, self.root / ('job-' + mode + '.db'))
            receipt = await runner.submit('fixture', 'stat', {}, {'session_id':'owner', 'access_mode':mode})
            await runner._run_task(receipt['task_id'], 0, 'general')
            public = await runner.result(receipt['task_id'])
            self.assertEqual(public['task']['state'], state)
            self.assertNotIn(secret, json.dumps(public) + json.dumps(runner.telemetry.summary()))
            runner.journal.conn.close()
        self.assertTrue(any(e['stage'] == 'job.execution' for e in self.records()))

    async def test_upstream_failure_is_recorded_and_reraised_without_changing_authority(self):
        from router.registry import MCPRegistry, UpstreamState
        from types import SimpleNamespace
        registry = MCPRegistry()
        registry.states['fixture'] = UpstreamState(service={'id':'fixture','name':'Fixture'})
        try:
            with patch.object(registry, 'ensure_initialized', AsyncMock(side_effect=RuntimeError('Bearer secret /private'))):
                with self.assertRaises(RuntimeError):
                    await registry.invoke('fixture', 'stat', {}, SimpleNamespace())
            self.assertTrue(any(e['stage'] == 'upstream.dispatch' and e['code'] == 'ROUTER_UPSTREAM_UNAVAILABLE' for e in self.records()))
        finally:
            await registry.close()

    async def test_configured_missing_token_denied_before_initialize_without_network(self):
        cfg = dict(resource_uri='https://resource.example/mcp', issuer='https://issuer.example',
                   introspection_endpoint='https://issuer.example/introspect', workspace_id='ws',
                   policy_revision='1', introspection_client_id='client', introspection_secret_env='DIAGNOSTIC_TEST_SECRET',
                   authorization_servers=['https://issuer.example'])
        with patch.object(self.server, 'load_tunnel_config', return_value={'resource_server':cfg}):
            response = await self.client.post('/mcp', json={'jsonrpc':'2.0','id':2,'method':'initialize'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'invalid_token')
        self.assertIn('Bearer resource_metadata=', response.headers['www-authenticate'])
        self.assertTrue(any(e['stage'] == 'auth.token_header' and e['code'] == 'AUTH_REQUIRED' for e in self.records()))

    async def test_unwritable_store_does_not_change_sanitized_rpc_response(self):
        from router.access import AuthContext
        auth = AuthContext('p','w',frozenset(),frozenset(),'1',time.time()+60)
        with patch.object(self.server.ResourceAuthorizer, 'authenticate', AsyncMock(return_value=auth)), \
                patch.object(self.server, '_visible', side_effect=RuntimeError('Bearer secret /private')), \
                patch.object(self.store, '_path', side_effect=OSError('Bearer disk-secret /private')):
            response = await self.client.post('/mcp', json={'jsonrpc':'2.0','id':7,'method':'tools/list'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['error']['code'], -32603)
        self.assertFalse(self.store.available)
        self.assertEqual(self.store.fallback[-1]['requestId'], response.json()['error']['data']['requestId'])
        self.assertNotIn('secret', json.dumps(list(self.store.fallback)) + response.text)


if __name__ == '__main__':
    unittest.main()

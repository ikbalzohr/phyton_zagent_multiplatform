"""Isolated HTTP/journal fixtures, NOT live OAuth or Windows acceptance."""
import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from router import server
from router.access import AuthContext, AuthorizationError, ResourceAuthorizer
from router.execution_context import new_context, scheduler_meta
from router.identity import Placement
from router.orchestration import Orchestrator


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth = AuthContext('p', 'ws', frozenset({'files:read', 'files:write'}),
                                frozenset({'files_search'}), '1', time.time()+300)
        self.resource = {'resource_id': 'workspace:ws:files', 'kind': 'files',
                         'profile_id': 'agentRoot', 'device_id': 'device', 'installation_id': 'install'}
        self.grant = {'scopes': ['files:read', 'files:write'], 'tools': ['files_search'], 'files_resource': self.resource}
        self.authorizer = ResourceAuthorizer({'workspace_id': 'ws', 'policy_revision': '1', 'grants': {'p': self.grant}})
        self.config = {'tool_policy': {'files_search': {'scope': 'files:read', 'enabled': True}}}
        self.orch = Orchestrator(AsyncMock(side_effect=AssertionError('executor must not run')), Path(self.tmp.name)/'tasks.db')
        self.addCleanup(self.orch.journal.conn.close)
        self.catalog = {'managed': False, 'revision': 'a'*64, 'profiles': [
            {'name': 'agentRoot', 'authorized_by_user': True, 'enabled': True}],
            'generations': {'agentRoot': 'g1'}, 'owner': None}
        for target, value in [('placement', Placement('device', 'install')), ('orchestrator', self.orch),
                              ('load_tunnel_config', lambda: self.config), ('authorizer', lambda: self.authorizer),
                              ('_auth_client', object())]:
            p = patch.object(server, target, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(ResourceAuthorizer, 'authenticate', AsyncMock(return_value=self.auth)); p.start(); self.addCleanup(p.stop)
        p = patch.object(server.registry, 'profile_catalog_snapshot', AsyncMock(return_value=self.catalog)); p.start(); self.addCleanup(p.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='https://fixture.invalid')
        self.addAsyncCleanup(self.client.aclose)
        self.context = new_context(self.auth, server.placement, 'files:read', 'files_search',
            resource_authorizer=self.authorizer, selected_profile_id='agentRoot',
            catalog={'default_profile_id': 'agentRoot', 'allowed_profile_ids': ['agentRoot'], 'generations': {'agentRoot': 'g1'}})
        self.task_id = self.context['task_id']
        row = dict(task_id=self.task_id, session_id=self.auth.owner, request_id=self.context['request_id'],
            trace_id=self.context['trace_id'], profile_id='', target_device_id='device', executed_on='device',
            service_id='zagent_files', tool_name='files_search', arguments_json=json.dumps({
                'path': 'phyton_zagent_multiplatform', 'profile_id': 'agentRoot', 'query': 'allowedExecutables', 'max_results': 100}),
            resource_key='installation:install', access_mode='write', priority=2, state='orphaned',
            created_at=1, updated_at=3, started_at=2, finished_at=3, error='Files failure', result_json='{"isError":true}',
            execution_context_json=json.dumps(self.context))
        await self.orch.journal.create(row)

    async def rpc(self, method, params=None):
        return await self.client.post('/mcp', headers={'Authorization': 'Bearer fixture-only'},
            json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})

    async def call(self, **args):
        response = await self.rpc('tools/call', {'name': 'zagent_task_recover', 'arguments': {'task_id': self.task_id, **args}})
        return response

    def value(self, response):
        result = response.json()['result']
        self.assertFalse(result['isError'])
        return json.loads(result['content'][0]['text'])


    async def test_owner_only_reconciliation_diagnostics_without_files_backend(self):
        before = await self.orch.journal.get(self.task_id)
        foreign = dict(before, task_id='tsk_'+'d'*32, session_id='owner_v1_foreign')
        await self.orch.journal.create(foreign)
        broken = AsyncMock(side_effect=AssertionError('Files must not be called'))
        with patch.object(server, '_files_catalog', broken):
            response = await self.rpc('tools/call', {
                'name': 'zagent_reconciliation_status', 'arguments': {'limit': 50}})
        self.assertEqual(response.status_code, 200)
        value = self.value(response)
        self.assertTrue(value['diagnostic_only'])
        self.assertEqual(value['owner_task_count'], 1)
        self.assertEqual(value['tasks'], [{
            'task_id': self.task_id, 'tool': 'files_search',
            'recovery': 'review_read_only_recovery_plan'}])
        self.assertNotIn('arguments_json', json.dumps(value))
        self.assertNotIn('installation:install', json.dumps(value))
        self.assertEqual(before, await self.orch.journal.get(self.task_id))
        broken.assert_not_awaited()
        with patch.object(ResourceAuthorizer, 'authenticate',
                          AsyncMock(return_value=AuthContext(
                              'p', 'ws', frozenset({'files:write'}),
                              frozenset({'files_search'}), '1', time.time()+300))):
            denied = await self.rpc('tools/call', {
                'name': 'zagent_reconciliation_status', 'arguments': {}})
            self.assertEqual(denied.status_code, 403)

    async def test_orphaned_arcmap_ping_diagnostic_is_nonblocking(self):
        historical = dict(self.context)
        historical.update({
            'public_tool': 'arcmap_ping',
            'required_scope': 'arcmap:inspect',
            'effective_access': 'write',
            'effective_resources': [
                {'resource_id': 'installation:install', 'kind': 'arcmap'}
            ],
        })
        await self.orch.journal.update(
            self.task_id, service_id='zagent_arcmap',
            tool_name='arcmap_ping', arguments_json='{}',
            execution_context_json=json.dumps(historical))
        response = await self.rpc('tools/call', {
            'name': 'zagent_reconciliation_status', 'arguments': {}})
        value = self.value(response)
        self.assertEqual(value['tasks'], [{
            'task_id': self.task_id, 'tool': 'arcmap_ping',
            'recovery': 'nonblocking_observation_no_action_required',
        }])
        self.assertEqual((await self.orch.journal.get(self.task_id))['state'],
                         'orphaned')

    async def test_write_orphan_is_diagnostic_only_never_automatically_recovered(self):
        row = await self.orch.journal.get(self.task_id)
        write_id = 'tsk_'+'e'*32
        other = dict(row, task_id=write_id, tool_name='files_exec_command',
                     service_id='zagent_files', arguments_json='{}')
        await self.orch.journal.create(other)
        response = await self.rpc('tools/call', {
            'name': 'zagent_reconciliation_status', 'arguments': {}})
        value = self.value(response)
        statuses = {t['task_id']: t['recovery'] for t in value['tasks']}
        self.assertEqual(statuses[write_id], 'manual_owner_reconciliation_required')
        self.assertEqual((await self.orch.journal.get(write_id))['state'], 'orphaned')
        self.assertEqual((await self.orch.journal.get(self.task_id))['state'], 'orphaned')

    async def test_http_plan_apply_wal_persistence_and_replay_denial(self):
        before = await self.orch.journal.get(self.task_id)
        reader = sqlite3.connect(self.orch.journal.path)
        self.addCleanup(reader.close)
        reader.execute('BEGIN')
        self.assertEqual(reader.execute('SELECT state FROM tasks').fetchone()[0], 'orphaned')
        self.assertTrue(Path(str(self.orch.journal.path)+'-wal').exists())
        plan = self.value(await self.call())
        self.assertTrue(plan['plan_only'])
        self.assertEqual(plan, self.value(await self.call()))
        self.assertEqual(before, await self.orch.journal.get(self.task_id))
        applied = self.value(await self.call(plan_only=False, expected_plan=plan['expected_plan']))
        self.assertEqual(applied['state'], 'failed')
        self.assertNotIn('accepted', applied)
        self.assertEqual(applied['remaining_resource_orphans'], 0)
        self.assertEqual(reader.execute('SELECT state FROM tasks').fetchone()[0], 'orphaned')
        reader.commit()
        self.assertEqual(reader.execute('SELECT state FROM tasks').fetchone()[0], 'failed')
        after = await self.orch.journal.get(self.task_id)
        for key in before:
            if key not in {'state', 'updated_at', 'recovered_at'}:
                self.assertEqual(before[key], after[key], key)
        audit = self.orch.journal.conn.execute('SELECT * FROM task_recovery_audit').fetchone()
        self.assertEqual(json.loads(audit['before_json']), before)
        self.assertEqual(json.loads(audit['after_json']), after)
        self.assertEqual((await self.call(plan_only=False, expected_plan=plan['expected_plan'])).status_code, 409)
        self.orch.executor.assert_not_awaited()

    async def test_recovery_does_not_depend_on_upstream_files_catalog(self):
        broken = AsyncMock(side_effect=AssertionError('Files catalog unavailable'))
        with patch.object(server, '_files_catalog', broken):
            plan = self.value(await self.call())
            applied = self.value(await self.call(plan_only=False, expected_plan=plan['expected_plan']))
            self.assertEqual(applied['state'], 'failed')
            verified = self.value(await self.call())
            self.assertEqual(verified['state'], 'failed')
            self.assertTrue(verified['audit_verified'])
            self.assertEqual(verified['expected_plan'], plan['expected_plan'])
            broken.assert_not_awaited()

    async def test_readback_rejects_unaudited_or_changed_failed_task(self):
        await self.orch.journal.update(self.task_id, state='failed')
        self.assertEqual((await self.call()).status_code, 409)
        await self.orch.journal.update(self.task_id, state='orphaned')
        plan = self.value(await self.call())
        self.value(await self.call(plan_only=False, expected_plan=plan['expected_plan']))
        await self.orch.journal.update(self.task_id, error='changed after recovery')
        self.assertEqual((await self.call()).status_code, 409)
        self.assertEqual((await self.orch.journal.get(self.task_id))['error'], 'changed after recovery')

    async def test_unknown_historical_context_is_not_recovered(self):
        for version in (None, True, 2):
            await self.orch.journal.update(self.task_id,
                execution_context_json=json.dumps(dict(self.context, context_version=version)))
            self.assertEqual((await self.call()).status_code, 409)
        self.assertEqual((await self.orch.journal.get(self.task_id))['state'], 'orphaned')

    async def test_real_search_glob_argument_is_recoverable(self):
        args = json.loads((await self.orch.journal.get(self.task_id))['arguments_json'])
        args['glob'] = '*.json'
        await self.orch.journal.update(self.task_id, arguments_json=json.dumps(args))
        self.assertEqual((await self.call()).status_code, 200)

    async def test_public_metadata_cannot_supply_authority(self):
        response = await self.rpc('tools/call', {'name': 'zagent_task_recover',
            'arguments': {'task_id': self.task_id}, '_meta': {'principal_id': 'forged'}})
        self.assertIn('error', response.json())

    async def test_authentication_failure_reaches_http_boundary(self):
        with patch.object(ResourceAuthorizer, 'authenticate', AsyncMock(side_effect=AuthorizationError('invalid_token', 401))):
            self.assertEqual((await self.call()).status_code, 401)

    async def test_authority_scope_resource_and_policy_denials(self):
        baseline = await self.orch.journal.get(self.task_id)
        from dataclasses import replace
        for auth in (replace(self.auth, principal_id='other'), replace(self.auth, workspace_id='other'),
                     replace(self.auth, scopes=frozenset({'files:read'})), replace(self.auth, tools=frozenset())):
            with self.subTest(auth=auth), patch.object(ResourceAuthorizer, 'authenticate', AsyncMock(return_value=auth)):
                response = await self.call()
                self.assertTrue(response.status_code == 403 or 'error' in response.json())
        for tool in ('files_search', 'zagent_task_recover'):
            old = self.config['tool_policy'].get(tool)
            for entry in (False, {}, {'scope': 'files:read' if tool == 'zagent_task_recover' else 'files:write'},
                          {'scope': 'files:read' if tool == 'files_search' else 'files:write', 'enabled': False}):
                self.config['tool_policy'][tool] = entry
                self.assertEqual((await self.call()).status_code, 403)
            if old is None:
                del self.config['tool_policy'][tool]
            else:
                self.config['tool_policy'][tool] = old
        for key, value in (('installation_id', 'other'), ('device_id', 'other'), ('profile_id', 'other'), ('revoked', True)):
            old = dict(self.resource)
            self.resource[key] = value
            self.assertEqual((await self.call()).status_code, 403)
            self.resource.clear(); self.resource.update(old)
        self.grant['revoked'] = True
        self.assertEqual((await self.call()).status_code, 403)
        self.assertEqual(baseline, await self.orch.journal.get(self.task_id))

    async def test_strict_schema_no_authority_or_implicit_apply(self):
        for args in ({'plan_only': False}, {'plan_only': 'false'}, {'principal_id': 'p'},
                     {'resource_key': 'installation:install'}, {'expected_plan': 'bad'}, {'all': True}):
            response = await self.call(**args)
            self.assertIn('error', response.json())
        self.assertEqual((await self.orch.journal.get(self.task_id))['state'], 'orphaned')

    async def test_row_and_resource_activity_denials(self):
        original = await self.orch.journal.get(self.task_id)
        for changes in ({'tool_name': 'files_write'}, {'state': 'running'}, {'started_at': None},
                        {'resource_key': 'installation:other'}, {'target_device_id': 'other'},
                        {'execution_context_json': json.dumps(dict(self.context, effective_access='write'))}):
            await self.orch.journal.update(self.task_id, **changes)
            response = await self.call()
            self.assertTrue(response.status_code in (403, 409) or 'error' in response.json())
            await self.orch.journal.update(self.task_id, **{k: original[k] for k in changes})
        async with self.orch.locks.acquire('installation:install', 'read'):
            self.assertEqual((await self.call()).status_code, 409)
        runner = asyncio.create_task(asyncio.sleep(10))
        self.orch._active_tasks[self.task_id] = runner
        try:
            self.assertEqual((await self.call()).status_code, 409)
        finally:
            runner.cancel(); await asyncio.gather(runner, return_exceptions=True)
            self.orch._active_tasks.clear()
        other = dict(original, task_id='tsk_'+'f'*32, state='queued')
        await self.orch.journal.create(other)
        self.assertEqual((await self.call()).status_code, 409)
        await self.orch.journal.update(other['task_id'], state='failed')
        await self.orch._enqueue(self.task_id, 2, emit_event=False)
        self.assertEqual((await self.call()).status_code, 409)

    async def test_stale_plan_concurrent_apply_and_other_orphan_preserved(self):
        plan = self.value(await self.call())
        await self.orch.journal.update(self.task_id, error='new evidence')
        self.assertEqual((await self.call(plan_only=False, expected_plan=plan['expected_plan'])).status_code, 409)
        other = dict(await self.orch.journal.get(self.task_id), task_id='tsk_'+'e'*32, tool_name='files_write')
        await self.orch.journal.create(other)
        other = await self.orch.journal.get(other['task_id'])
        plan = self.value(await self.call())
        responses = await asyncio.gather(*[self.call(plan_only=False, expected_plan=plan['expected_plan']) for _ in range(2)])
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        success = next(r for r in responses if r.status_code == 200)
        self.assertEqual(self.value(success)['remaining_resource_orphans'], 1)
        self.assertEqual(other, await self.orch.journal.get(other['task_id']))
        reopened = sqlite3.connect(self.orch.journal.path)
        try:
            self.assertEqual(reopened.execute('SELECT state FROM tasks WHERE task_id=?', (self.task_id,)).fetchone()[0], 'failed')
            self.assertEqual(reopened.execute('SELECT COUNT(*) FROM task_recovery_audit').fetchone()[0], 1)
        finally:
            reopened.close()

    async def test_audit_failure_rolls_back_task(self):
        conn = self.orch.journal.conn
        conn.execute('CREATE TABLE task_recovery_audit (task_id TEXT PRIMARY KEY, plan_digest TEXT NOT NULL, actor_id TEXT NOT NULL, workspace_id TEXT NOT NULL, recovered_at REAL NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL)')
        conn.execute("CREATE TRIGGER deny_audit BEFORE INSERT ON task_recovery_audit BEGIN SELECT RAISE(ABORT, 'fixture audit failure'); END")
        conn.commit()
        before = await self.orch.journal.get(self.task_id)
        plan = self.value(await self.call())
        response = await self.call(plan_only=False, expected_plan=plan['expected_plan'])
        self.assertIn('error', response.json())
        self.assertEqual(before, await self.orch.journal.get(self.task_id))
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM task_recovery_audit').fetchone()[0], 0)
        self.assertFalse(conn.in_transaction)

    async def test_discovery_existing_original_membership_no_new_grant(self):
        response = await self.rpc('tools/list')
        self.assertEqual(response.status_code, 200)
        tools = {t['name']: t for t in response.json()['result']['tools']}
        self.assertIn('zagent_task_recover', tools)
        self.assertFalse(tools['zagent_task_recover']['inputSchema']['additionalProperties'])

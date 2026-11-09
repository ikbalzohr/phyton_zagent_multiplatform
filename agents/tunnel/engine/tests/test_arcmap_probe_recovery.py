"""No-effect ArcMap health recovery: real Router HTTP and SQLite fixtures."""
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
from router.execution_context import new_context, scheduler_meta, validate_context
from router.identity import Placement
from router.orchestration import Orchestrator
from router.orphan_conflicts import nonblocking_probe, blocks_service, safe_read_target


class ArcMapProbeRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.auth = AuthContext(
            'p', 'ws', frozenset({'arcmap:inspect', 'arcmap:execute'}),
            frozenset({'arcmap_stage3_health'}), 'v1', time.time() + 300)
        self.placement = Placement('device', 'install')
        self.grant = {'scopes': ['arcmap:inspect', 'arcmap:execute'],
                      'tools': ['arcmap_stage3_health']}
        self.authorizer = ResourceAuthorizer(
            {'workspace_id': 'ws', 'policy_revision': 'v1',
             'grants': {'p': self.grant}})
        self.policy = {'tool_policy': {
            'arcmap_stage3_health': {'scope': 'arcmap:inspect', 'enabled': True}}}
        self.orch = Orchestrator(
            AsyncMock(side_effect=AssertionError('must not dispatch agent')),
            Path(self.tmp.name) / 'tasks.db')
        self.addCleanup(self.orch.journal.conn.close)
        for name, value in (
            ('placement', self.placement),
            ('orchestrator', self.orch),
            ('load_tunnel_config', lambda: self.policy),
            ('authorizer', lambda: self.authorizer),
            ('_auth_client', object())
        ):
            mock = patch.object(server, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        auth_patch = patch.object(
            ResourceAuthorizer, 'authenticate',
            AsyncMock(return_value=self.auth))
        auth_patch.start()
        self.addCleanup(auth_patch.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url='https://fixture.invalid')
        self.addAsyncCleanup(self.client.aclose)
        self.ctx = new_context(self.auth, self.placement, 'arcmap:inspect',
                               'arcmap_stage3_health')
        self.task_id = self.ctx['task_id']
        self.historical = dict(self.ctx, effective_access='write')
        await self.orch.journal.create(dict(
            task_id=self.task_id, session_id=self.auth.owner,
            request_id=self.ctx['request_id'], trace_id=self.ctx['trace_id'],
            profile_id='', target_device_id='device', executed_on='device',
            service_id='zagent_arcmap', tool_name='arcmap_stage3_health',
            arguments_json='{}', resource_key='installation:install',
            access_mode='write', priority=2,
            state='orphaned', created_at=1, updated_at=3,
            started_at=2, finished_at=3, error='timeout',
            execution_context_json=json.dumps(self.historical)))

    async def rpc(self, tool, args):
        response = await self.client.post(
            '/mcp', headers={'Authorization': 'Bearer fixture-only'},
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                  'params': {'name': tool, 'arguments': args}})
        return response

    def data(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        obj = response.json()['result']
        self.assertFalse(obj['isError'])
        return json.loads(obj['content'][0]['text'])

    async def test_new_health_is_reader_and_validates(self):
        self.assertEqual(self.ctx['effective_access'], 'read')
        meta = scheduler_meta(self.ctx, self.auth.owner)
        self.assertEqual(meta['access_mode'], 'read')
        self.assertEqual(meta['priority'], 1)
        self.assertEqual(validate_context(self.ctx, self.placement),
                         self.ctx)

    async def test_historical_health_no_longer_blocks(self):
        row = await self.orch.journal.get(self.task_id)
        self.assertTrue(nonblocking_probe(row))
        self.assertFalse(blocks_service(row, 'zagent_arcmap'))
        self.assertTrue(safe_read_target(
            'zagent_arcmap', 'arcmap_stage3_health', self.ctx))
        self.assertEqual(row['state'], 'orphaned')

    async def test_plan_apply_with_evidence_and_no_replay(self):
        plan = self.data(await self.rpc(
            'zagent_arcmap_probe_recover',
            {'task_id': self.task_id}))
        self.assertTrue(plan['plan_only'])
        self.assertEqual((await self.orch.journal.get(self.task_id))['state'],
                         'orphaned')
        applied = self.data(await self.rpc(
            'zagent_arcmap_probe_recover',
            {'task_id': self.task_id, 'plan_only': False,
             'expected_plan': plan['expected_plan']}))
        self.assertFalse(applied['plan_only'])
        self.assertTrue(applied['audit_recorded'])
        self.assertEqual(applied['remaining_owned_health_orphans'], 0)
        after = await self.orch.journal.get(self.task_id)
        self.assertEqual(after['state'], 'failed')
        audit = self.orch.journal.conn.execute(
            'SELECT * FROM arcmap_probe_recovery_audit WHERE task_id=?',
            (self.task_id,)).fetchone()
        self.assertEqual(json.loads(audit['before_json'])['state'],
                         'orphaned')
        self.assertEqual(json.loads(audit['after_json'])['state'],
                         'failed')
        self.assertEqual((await self.rpc(
            'zagent_arcmap_probe_recover',
            {'task_id': self.task_id, 'plan_only': False,
             'expected_plan': plan['expected_plan']})).status_code, 409)
        self.orch.executor.assert_not_awaited()

    async def test_wrong_plan_denied_without_change(self):
        response = await self.rpc(
            'zagent_arcmap_probe_recover',
            {'task_id': self.task_id, 'plan_only': False,
             'expected_plan': '0' * 64})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.orch.journal.get(self.task_id))['state'],
                         'orphaned')

    async def test_wrong_tool_or_forged_context_denied(self):
        await self.orch.journal.update(self.task_id, tool_name='arcmap_save_current_map')
        self.assertEqual((await self.rpc(
            'zagent_arcmap_probe_recover',
            {'task_id': self.task_id})).status_code, 409)
        await self.orch.journal.update(
            self.task_id, tool_name='arcmap_stage3_health',
            arguments_json='{"force":true}')
        self.assertEqual((await self.rpc(
            'zagent_arcmap_probe_recover',
            {'task_id': self.task_id})).status_code, 409)

    async def test_missing_mutation_scope_denied(self):
        limited = AuthContext('p', 'ws', frozenset({'arcmap:inspect'}),
                              frozenset({'arcmap_stage3_health'}),
                              'v1', time.time() + 300)
        with patch.object(ResourceAuthorizer, 'authenticate',
                          AsyncMock(return_value=limited)):
            response = await self.rpc(
                'zagent_arcmap_probe_recover',
                {'task_id': self.task_id})
        self.assertEqual(response.status_code, 403)
        self.assertEqual((await self.orch.journal.get(self.task_id))['state'],
                         'orphaned')


if __name__ == '__main__':
    unittest.main()

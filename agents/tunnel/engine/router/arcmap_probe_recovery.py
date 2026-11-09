"""Immediate, owner-scoped recovery for provably no-effect ArcMap health probes.

This is control-plane only: no agent call, no replay, no database deletion.
Historical orphaned health tasks are marked failed with an immutable audit
and exact compare-and-swap after inspection and a plan/apply handshake.
"""
from __future__ import annotations

import json
import time

from .access import AuthorizationError, digest
from .orphan_conflicts import nonblocking_probe
from .task_recovery import _idle, _conflict

TOOL = 'zagent_arcmap_probe_recover'
ORIGINAL = 'arcmap_stage3_health'
SCHEMA = {
    'type': 'object',
    'properties': {
        'task_id': {'type': 'string', 'pattern': '^tsk_[0-9a-f]{32}$'},
        'plan_only': {'type': 'boolean', 'default': True},
        'expected_plan': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
    },
    'required': ['task_id'],
    'additionalProperties': False,
    'allOf': [{'if': {'properties': {'plan_only': {'const': False}},
                   'required': ['plan_only']},
               'then': {'required': ['expected_plan']}}],
}


def require_available(auth, get_authorizer, policy_lookup):
    original = policy_lookup(ORIGINAL)
    scope = original.get('scope')
    if scope not in ('arcmap:inspect', 'arcmap:execute') or original.get('enabled', True) is not True:
        raise AuthorizationError('TOOL_NOT_AUTHORIZED', 403)
    auth.require(scope, ORIGINAL)
    # Changing a journal status requires an explicit effect-capable grant.
    auth.require('arcmap:execute')
    grant = get_authorizer().current_grant(auth)
    scopes = set(grant.get('scopes') or [])
    tools = set(grant.get('tools') or [])
    if (scope not in scopes or 'arcmap:execute' not in scopes
            or (ORIGINAL not in tools and '*' not in tools)):
        raise AuthorizationError('TOOL_NOT_AUTHORIZED', 403)
    return original


def _candidate(row, auth, placement, original):
    if row is None or row['session_id'] != auth.owner:
        raise KeyError('TASK_NOT_FOUND')
    if row['state'] != 'orphaned' or row['started_at'] is None:
        _conflict()
    if row['service_id'] != 'zagent_arcmap' or row['tool_name'] != ORIGINAL:
        _conflict()
    if not nonblocking_probe(row):
        _conflict()
    ctx = json.loads(row['execution_context_json'])
    placement.validate(row['target_device_id'])
    if (ctx.get('principal_id') != auth.principal_id
            or ctx.get('workspace_id') != auth.workspace_id
            or ctx.get('device_id') != placement.device_id
            or ctx.get('installation_id') != placement.installation_id
            or ctx.get('policy_revision') != auth.policy_revision
            or ctx.get('public_tool') != ORIGINAL
            or ctx.get('required_scope') != original['scope']
            or ctx.get('task_id') != row['task_id']
            or ctx.get('request_id') != row['request_id']
            or ctx.get('trace_id') != row['trace_id']
            or row['executed_on'] != placement.device_id
            or row['access_mode'] not in ('read', 'write')):
        raise AuthorizationError('AUTHORIZATION_CHANGED', 403)
    return ctx


async def recover(orch, arguments, auth, placement, get_authorizer, policy_lookup):
    # Keep the same lock ordering as existing task_recovery.recover().
    async with orch.locks._cond:
        async with orch.journal._lock:
            row = orch.journal.conn.execute(
                'SELECT * FROM tasks WHERE task_id=?', (arguments['task_id'],)).fetchone()
            row = dict(row) if row else None
            if row is None or row['session_id'] != auth.owner:
                raise KeyError('TASK_NOT_FOUND')
            original = require_available(auth, get_authorizer, policy_lookup)
            conn = orch.journal.conn
            conn.execute('BEGIN IMMEDIATE')
            try:
                latest = conn.execute('SELECT * FROM tasks WHERE task_id=?',
                                      (row['task_id'],)).fetchone()
                latest = dict(latest) if latest else None
                _candidate(latest, auth, placement, original)
                _idle(orch, latest)
                plan = digest({
                    'version': 1, 'action': 'orphaned_arcmap_health_to_failed',
                    'row': latest, 'grant': get_authorizer().current_grant(auth),
                    'original_policy': original,
                })
                result = {'ok': True, 'task_id': latest['task_id'],
                          'plan_only': arguments.get('plan_only', True),
                          'expected_plan': plan, 'from_state': 'orphaned',
                          'state': 'failed', 'classification': 'no_effect_health_probe'}
                if result['plan_only']:
                    conn.rollback()
                    return result
                if arguments.get('expected_plan') != plan:
                    _conflict()
                conn.execute("""CREATE TABLE IF NOT EXISTS arcmap_probe_recovery_audit (
                    task_id TEXT PRIMARY KEY, plan_digest TEXT NOT NULL,
                    actor_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                    recovered_at REAL NOT NULL, before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL)""")
                stamp = time.time()
                fields = ' AND '.join('"' + col + '" IS ?' for col in latest)
                cur = conn.execute(
                    'UPDATE tasks SET state=?,updated_at=?,recovered_at=? WHERE '+fields,
                    ('failed', stamp, stamp, *latest.values()))
                if cur.rowcount != 1:
                    _conflict()
                after = dict(conn.execute(
                    'SELECT * FROM tasks WHERE task_id=?', (latest['task_id'],)).fetchone())
                expected = dict(latest, state='failed',
                                updated_at=stamp, recovered_at=stamp)
                if after != expected:
                    _conflict()
                conn.execute(
                    'INSERT INTO arcmap_probe_recovery_audit VALUES (?,?,?,?,?,?,?)',
                    (latest['task_id'], plan, auth.principal_id,
                     auth.workspace_id, stamp,
                     json.dumps(latest, sort_keys=True),
                     json.dumps(after, sort_keys=True)))
                conn.commit()
                remaining = conn.execute(
                    """SELECT COUNT(*) FROM tasks WHERE session_id=?
                         AND service_id='zagent_arcmap'
                         AND tool_name=? AND state='orphaned'""",
                    (auth.owner, ORIGINAL)).fetchone()[0]
                return dict(result, audit_recorded=True,
                            remaining_owned_health_orphans=remaining)
            except BaseException:
                conn.rollback()
                raise

"""Narrow immediate control for interrupted read-only Files searches.

No executor call, console prerequisite, alternate DB connection or WAL handling.
"""
import json
import time

from .access import AuthorizationError, digest
from .execution_context import policy_resources
from .files_policy import validate_files_tool_scope

TOOL = 'zagent_task_recover'
ORIGINAL = 'files_search'
SCHEMA = {'type': 'object', 'properties': {
    'task_id': {'type': 'string', 'pattern': '^tsk_[0-9a-f]{32}$'},
    'plan_only': {'type': 'boolean', 'default': True},
    'expected_plan': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}},
    'required': ['task_id'], 'additionalProperties': False,
    'allOf': [{'if': {'properties': {'plan_only': {'const': False}}, 'required': ['plan_only']},
               'then': {'required': ['expected_plan']}}]}


def require_available(auth, authorizer, policy_lookup):
    # Like owned receipts, original-tool membership is the authority. Requiring
    # a new grant tool here would make recovery inaccessible to existing owners.
    auth.require('files:read', ORIGINAL)
    auth.require('files:write')
    grant = authorizer.current_grant(auth)
    if not {'files:read', 'files:write'} <= set(grant.get('scopes', [])) or ORIGINAL not in grant.get('tools', []):
        raise AuthorizationError('TOOL_NOT_AUTHORIZED', 403)
    for name, scope in ((ORIGINAL, 'files:read'), (TOOL, 'files:write')):
        policy = policy_lookup(name)
        if policy.get('scope') != scope or policy.get('enabled', True) is not True:
            raise AuthorizationError('TOOL_NOT_AUTHORIZED', 403)


def _conflict():
    raise AuthorizationError('RESOURCE_RECONCILIATION_REQUIRED', 409)


def _candidate(row, auth, placement, authorizer):
    if row is None or row['session_id'] != auth.owner:
        raise KeyError('TASK_NOT_FOUND')
    context = json.loads(row['execution_context_json'])
    args = json.loads(row['arguments_json'])
    # Scheduler uses an installation WRITE lease even for read-only Files
    # searches. Read-only classification comes from canonical tool/context,
    # never the scheduler's access_mode column.
    if (row['state'] != 'orphaned' or row['started_at'] is None
            or row['service_id'] not in {'zagent_files', 'zagent_files_v3'}
            or row['tool_name'] != ORIGINAL or context.get('public_tool') != ORIGINAL
            or type(context.get('context_version')) is not int or context.get('context_version') != 1
            or not isinstance(context.get('scopes'), list) or 'files:read' not in context['scopes']
            or context.get('required_scope') != 'files:read'
            or context.get('effective_access') != 'read'):
        _conflict()
    placement.validate(row['target_device_id'])
    if (context.get('principal_id') != auth.principal_id or context.get('workspace_id') != auth.workspace_id
            or context.get('device_id') != placement.device_id
            or context.get('installation_id') != placement.installation_id
            or row['executed_on'] != placement.device_id
            or context.get('policy_revision') != auth.policy_revision
            or context.get('task_id') != row['task_id']
            or context.get('request_id') != row['request_id'] or context.get('trace_id') != row['trace_id']
            or row['resource_key'] != 'installation:'+placement.installation_id
            or row['access_mode'] != 'write'):
        raise AuthorizationError('AUTHORIZATION_CHANGED', 403)
    validate_files_tool_scope(ORIGINAL, 'files:read', auth.scopes)
    resources = context.get('effective_resources')
    if not isinstance(resources, list) or len(resources) != 1 or not isinstance(resources[0], dict):
        raise AuthorizationError('AUTHORIZATION_CHANGED', 403)
    selected = resources[0].get('profile_id')
    if (not isinstance(args, dict) or args.get('profile_id', selected) != selected
            or set(args) - {'path', 'profile_id', 'query', 'max_results', 'case_sensitive', 'glob'}
            or not isinstance(args.get('path'), str) or not isinstance(args.get('query'), str)):
        _conflict()
    # Recovery changes only the owner's historical read-task state, not Files
    # data or profile grants. Bind current local grant placement/membership; do
    # not require a live backend or today's historical generation token. Every
    # future Files operation still performs its normal live generation check.
    if set(resources[0]) - {'resource_id', 'kind', 'profile_id', 'profile_generation'}:
        raise AuthorizationError('AUTHORIZATION_CHANGED', 403)
    current = policy_resources(auth, placement, 'files:read', authorizer,
                               selected_profile_id=selected)
    historical = [{k: v for k, v in resources[0].items() if k != 'profile_generation'}]
    if historical != current:
        raise AuthorizationError('AUTHORIZATION_CHANGED', 403)
    return context


def _idle(orch, row):
    key = row['resource_key']
    # Actual ResourceLockManager lease state, not heartbeat guesses.
    if key in orch.locks._writers or orch.locks._readers.get(key, 0):
        _conflict()
    conn = orch.journal.conn
    if conn.execute("SELECT 1 FROM tasks WHERE resource_key=? AND state NOT IN ('succeeded','failed','cancelled','orphaned') LIMIT 1", (key,)).fetchone():
        _conflict()
    for task_id, runner in orch._active_tasks.items():
        if not runner.done():
            active = conn.execute('SELECT resource_key FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            if active is None or active['resource_key'] == key:
                _conflict()
    for queue in (orch.interactive_queue, orch.background_queue):
        for item in queue._queue:
            queued = conn.execute('SELECT resource_key FROM tasks WHERE task_id=?', (item.task_id,)).fetchone()
            if queued is None or queued['resource_key'] == key:
                _conflict()


async def recover(orch, arguments, auth, placement, get_authorizer, policy_lookup):
    # Same lock order as a scheduler lease release followed by journal access.
    # Holding the condition prevents new resource leases during validation/CAS.
    async with orch.locks._cond:
        async with orch.journal._lock:
            conn = orch.journal.conn
            row = conn.execute('SELECT * FROM tasks WHERE task_id=?', (arguments['task_id'],)).fetchone()
            row = dict(row) if row else None
            if row is None or row['session_id'] != auth.owner:
                raise KeyError('TASK_NOT_FOUND')
            # No backend/network awaits while holding scheduler/journal locks.
            authorizer = get_authorizer()
            require_available(auth, authorizer, policy_lookup)
            conn.execute('BEGIN IMMEDIATE')
            try:
                latest = dict(conn.execute('SELECT * FROM tasks WHERE task_id=?', (row['task_id'],)).fetchone())
                # The same immediate control provides authenticated readback,
                # even when ordinary owned receipts still need a broken backend.
                if latest['state'] == 'failed' and arguments.get('plan_only', True):
                    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_recovery_audit'").fetchone():
                        _conflict()
                    audit = conn.execute('SELECT * FROM task_recovery_audit WHERE task_id=?', (latest['task_id'],)).fetchone()
                    if not audit:
                        _conflict()
                    before = json.loads(audit['before_json'])
                    after = json.loads(audit['after_json'])
                    _candidate(before, auth, placement, authorizer)
                    expected = dict(before, state='failed', updated_at=audit['recovered_at'], recovered_at=audit['recovered_at'])
                    if (after != latest or after != expected or audit['actor_id'] != auth.principal_id
                            or audit['workspace_id'] != auth.workspace_id):
                        _conflict()
                    remaining = conn.execute("SELECT COUNT(*) FROM tasks WHERE resource_key=? AND state='orphaned' AND started_at IS NOT NULL", (latest['resource_key'],)).fetchone()[0]
                    conn.rollback()
                    return {'ok': True, 'task_id': latest['task_id'], 'plan_only': True, 'state': 'failed',
                            'expected_plan': audit['plan_digest'], 'audit_verified': True,
                            'remaining_resource_orphans': remaining}
                context = _candidate(latest, auth, placement, authorizer)
                _idle(orch, latest)
                plan = digest({'version': 1, 'action': 'orphaned_read_search_to_failed',
                    'row': latest, 'grant': authorizer.current_grant(auth),
                    'original_policy': policy_lookup(ORIGINAL), 'control_policy': policy_lookup(TOOL)})
                result = {'ok': True, 'task_id': latest['task_id'], 'plan_only': arguments.get('plan_only', True),
                          'expected_plan': plan, 'from_state': 'orphaned', 'state': 'failed',
                          'classification': 'read_only_search_no_replay'}
                if result['plan_only']:
                    conn.rollback()
                    return result
                if arguments.get('expected_plan') != plan:
                    _conflict()
                conn.execute('''CREATE TABLE IF NOT EXISTS task_recovery_audit (
                    task_id TEXT PRIMARY KEY, plan_digest TEXT NOT NULL, actor_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL, recovered_at REAL NOT NULL,
                    before_json TEXT NOT NULL, after_json TEXT NOT NULL)''')
                stamp = time.time()
                # Full-row CAS, including original evidence and every nullable field.
                where = ' AND '.join('"'+column+'" IS ?' for column in latest)
                changed = conn.execute('UPDATE tasks SET state=\'failed\', updated_at=?, recovered_at=? WHERE '+where,
                                       (stamp, stamp, *latest.values()))
                if changed.rowcount != 1:
                    _conflict()
                after = dict(conn.execute('SELECT * FROM tasks WHERE task_id=?', (latest['task_id'],)).fetchone())
                expected = dict(latest, state='failed', updated_at=stamp, recovered_at=stamp)
                if after != expected:
                    _conflict()
                conn.execute('INSERT INTO task_recovery_audit VALUES (?,?,?,?,?,?,?)', (
                    latest['task_id'], plan, context['principal_id'], context['workspace_id'], stamp,
                    json.dumps(latest, sort_keys=True), json.dumps(after, sort_keys=True)))
                # Exact same quarantine predicate used by server._executor.
                remaining = conn.execute("SELECT COUNT(*) FROM tasks WHERE resource_key=? AND state='orphaned' AND started_at IS NOT NULL", (latest['resource_key'],)).fetchone()[0]
                conn.commit()
                persisted = dict(conn.execute('SELECT * FROM tasks WHERE task_id=?', (latest['task_id'],)).fetchone())
                if persisted != after:
                    _conflict()
                return {**result, 'audit_recorded': True, 'remaining_resource_orphans': remaining}
            except BaseException:
                conn.rollback()
                raise

"""Offline owner-console recovery, NOT an MCP tool or scheduler auto-repair.

Only the closed files_search shape is eligible. Scheduler 'write' is its shared
installation lock, not evidence of a write: effective_access must still be read.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path


class RecoveryDenied(ValueError):
    """Public messages are fixed guard codes, never private exception text."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RecoveryDenied('TASK_SHAPE')
            result[key] = value
        return result
    try:
        if not isinstance(text, str) or len(text) > 1048576:
            raise ValueError()
        return json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError) as exc:
        raise RecoveryDenied('TASK_SHAPE') from exc


def validate(row, authority):
    try:
        ctx = strict_json(row['execution_context_json'])
        args = strict_json(row['arguments_json'])
        context_keys = {'context_version','principal_id','workspace_id','device_id','installation_id',
                        'request_id','trace_id','task_id','operation_id','deadline','scopes',
                        'policy_revision','effective_resources','effective_access','required_scope','public_tool'}
        if (not isinstance(ctx, dict) or set(ctx) != context_keys or not isinstance(args, dict)
                or set(args) != {'path', 'profile_id', 'query', 'max_results'}
                or type(args['max_results']) is not int or not 1 <= args['max_results'] <= 100
                or any(not isinstance(args[k], str) or not args[k] or len(args[k]) > 1024 for k in ('path', 'profile_id', 'query'))
                or args['path'] != 'phyton_zagent_multiplatform'
                or args['query'] != 'allowedExecutables'
                or args['profile_id'] != 'agentRoot'
                or row['state'] != 'orphaned' or row['started_at'] is None
                or row['recovered_at'] is not None
                or (row['finished_at'] is not None and (
                    type(row['finished_at']) not in (int, float)
                    or not math.isfinite(row['finished_at'])
                    or row['finished_at'] < row['started_at']))
                or row['result_json'] is not None
                or row['tool_name'] != 'files_search'
                or row['service_id'] not in {'zagent_files', 'zagent_files_v3'}
                or row['access_mode'] != 'write'
                or row['resource_key'] != 'installation:' + authority['installation_id']
                or row['session_id'] != 'owner_v1_' + digest([authority['principal_id'], authority['workspace_id']])
                or any(ctx.get(k) != authority[k] for k in ('principal_id','workspace_id','device_id','installation_id'))
                or type(ctx.get('context_version')) is not int or ctx.get('context_version') != 1
                or ctx.get('effective_access') != 'read' or ctx.get('required_scope') != 'files:read'
                or ctx.get('public_tool') != 'files_search'
                or not isinstance(ctx.get('scopes'), list) or 'files:read' not in ctx['scopes']
                or any(row[k] != ctx.get(k) for k in ('task_id','request_id','trace_id'))
                or row['target_device_id'] != authority['device_id'] or row['executed_on'] != authority['device_id']):
            raise RecoveryDenied('TASK_SHAPE')
        resources = ctx.get('effective_resources')
        if (not isinstance(resources, list) or len(resources) != 1 or not isinstance(resources[0], dict)
                or resources[0].get('kind') != 'files' or resources[0].get('profile_id') != args['profile_id']
                or resources[0].get('resource_id') != authority['resource_id']
                or set(resources[0]) - {'kind','profile_id','resource_id','profile_generation'}):
            raise RecoveryDenied('TASK_SHAPE')
    except (KeyError, TypeError) as exc:
        raise RecoveryDenied('TASK_SHAPE') from exc


def recover(path, task_id, *, guard, apply=False, expected_plan=None):
    """guard is an internal seam, never caller-selectable via command line/MCP.

    It checks Windows owner/console, enrollment, all private paths and stopped
    producers, returning the same authority/config snapshot at every checkpoint.
    """
    authority = guard()
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise RecoveryDenied('JOURNAL_PATH')
    # immutable read guarantees PlanOnly cannot create WAL/SHM or alter a journal.
    # A nonempty WAL requires normal shutdown/checkpoint, NOT deletion by this tool.
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise RecoveryDenied('JOURNAL_WAL_REQUIRES_CLEAN_STOP')
    identity = (path.stat().st_dev, path.stat().st_ino)
    uri = path.resolve().as_uri() + ('?mode=rw' if apply else '?mode=ro&immutable=1')
    conn = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA trusted_schema=OFF')
        if apply:
            conn.execute('BEGIN EXCLUSIVE')
        raw = conn.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if raw is None:
            raise RecoveryDenied('TASK_NOT_FOUND')
        row = dict(raw)
        validate(row, authority)
        # Conservatively reject queued/recovering/unknown states anywhere, not just writers.
        if conn.execute("SELECT 1 FROM tasks WHERE state NOT IN ('succeeded','failed','cancelled','orphaned') LIMIT 1").fetchone():
            raise RecoveryDenied('ACTIVE_TASKS')
        token = digest({'row': row, 'authority': authority, 'journal_identity': identity})
        if not apply:
            if guard() != authority:
                raise RecoveryDenied('AUTHORITY_CHANGED')
            return {'state': 'plan_only', 'task_id': task_id, 'plan_sha256': token}
        if not expected_plan or token != expected_plan:
            raise RecoveryDenied('PLAN_CHANGED')
        if guard() != authority or (path.stat().st_dev, path.stat().st_ino) != identity:
            raise RecoveryDenied('AUTHORITY_CHANGED')
        # No triggers may run side effects beyond this explicit scoped transition.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' LIMIT 1").fetchone():
            raise RecoveryDenied('JOURNAL_SCHEMA')
        stamp = time.time()
        changed = conn.execute("UPDATE tasks SET state='failed', updated_at=?, finished_at=COALESCE(finished_at, ?), recovered_at=? WHERE task_id=? AND state='orphaned'", (stamp, stamp, stamp, task_id))
        if changed.rowcount != 1:
            raise RecoveryDenied('TASK_CHANGED')
        after = dict(conn.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone())
        conn.execute('''CREATE TABLE IF NOT EXISTS owner_search_recovery_audit (
            task_id TEXT PRIMARY KEY, recovered_at REAL NOT NULL, owner_sid TEXT NOT NULL,
            plan_sha256 TEXT NOT NULL, reason TEXT NOT NULL,
            before_json TEXT NOT NULL, after_json TEXT NOT NULL)''')
        conn.execute('INSERT INTO owner_search_recovery_audit VALUES (?,?,?,?,?,?,?)',
                     (task_id, stamp, authority['owner_sid'], token,
                      'OWNER_LOCAL_READ_ONLY_SEARCH_OUTCOME_UNKNOWN_FAILED', canonical(row), canonical(after)))
        if guard() != authority or (path.stat().st_dev, path.stat().st_ino) != identity:
            raise RecoveryDenied('AUTHORITY_CHANGED')
        conn.execute('COMMIT')
        actual = dict(conn.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone())
        audit = conn.execute('SELECT after_json FROM owner_search_recovery_audit WHERE task_id=?', (task_id,)).fetchone()
        if actual != after or not audit or strict_json(audit[0]) != after:
            raise RecoveryDenied('COMMITTED_READBACK_FAILED')
        remaining = conn.execute("SELECT COUNT(*) FROM tasks WHERE resource_key=? AND state='orphaned' AND started_at IS NOT NULL", (row['resource_key'],)).fetchone()[0]
        return {'state': 'failed', 'task_id': task_id, 'audit_verified': True, 'remaining_quarantine_tasks': remaining}
    finally:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        conn.close()


def windows_guard(install_root, data_root, principal, powershell):
    import os
    import subprocess
    if os.name != 'nt':
        raise RecoveryDenied('OWNER_CONSOLE')
    # Do not trust redirected/service callers or an attestation passed in argv.
    import ctypes
    mode = ctypes.c_ulong()
    kernel = ctypes.windll.kernel32
    kernel.GetStdHandle.restype = ctypes.c_void_p
    if not kernel.GetConsoleMode(ctypes.c_void_p(kernel.GetStdHandle(-10)), ctypes.byref(mode)):
        raise RecoveryDenied('OWNER_CONSOLE')
    script = Path(__file__).with_name('Assert-OwnerSearchRecovery.ps1')
    if Path(install_root).resolve() != Path(__file__).resolve().parents[2]:
        raise RecoveryDenied('SOURCE_PATH')
    host = Path(powershell)
    if not host.is_absolute() or not host.is_file() or host.name.lower() != 'pwsh.exe':
        raise RecoveryDenied('POWERSHELL_HOST')
    try:
        proc = subprocess.run([str(host), '-NoLogo', '-NoProfile', '-File', str(script),
            '-InstallRoot', str(install_root), '-DataRoot', str(data_root),
            '-OwnerPrincipal', principal, '-RecoveryPid', str(os.getpid())],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        answer = strict_json(proc.stdout.decode('utf-8-sig').strip())
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise RecoveryDenied('WINDOWS_GUARD') from exc
    stages = {'OWNER_CONSOLE','SOURCE_PATH','DATAROOT_ACL','STOPPED_PRODUCERS','ENROLLMENT','JOURNAL_ACL'}
    if proc.returncode:
        code = answer.get('denied') if isinstance(answer, dict) else None
        raise RecoveryDenied(code if code in stages else 'WINDOWS_GUARD')
    if (not isinstance(answer, dict) or set(answer) != {'principal_id','workspace_id','device_id',
            'installation_id','resource_id','owner_sid','config_snapshots'}
            or any(not isinstance(answer[k], str) or not answer[k] for k in set(answer)-{'config_snapshots'})
            or answer['principal_id'] != principal or not isinstance(answer['config_snapshots'], list)
            or len(answer['config_snapshots']) != 3):
        raise RecoveryDenied('WINDOWS_GUARD')
    return answer


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-root', required=True, type=Path)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--owner-principal', required=True)
    parser.add_argument('--powershell', required=True, type=Path, help='Exact owner-selected PowerShell 7 pwsh.exe')
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--apply', action='store_true', help='Explicit offline owner-local apply, never through MCP')
    parser.add_argument('--expected-plan', help='Unchanged plan_sha256 from PlanOnly')
    args = parser.parse_args()
    guard = lambda: windows_guard(args.install_root, args.data_root, args.owner_principal, args.powershell)
    try:
        result = recover(args.data_root / 'tunnel/runtime/tasks.db', args.task_id,
                         guard=guard, apply=args.apply, expected_plan=args.expected_plan)
        print(canonical(result))
        return 0
    except RecoveryDenied as exc:
        print(canonical({'state':'denied','guard':str(exc)}))
        return 2
    except Exception:
        # Includes SQLite/schema/lock failures; no raw private exception diagnostics.
        print(canonical({'state':'denied','guard':'JOURNAL_IO_OR_SCHEMA'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Agent-local execution. Global scheduling and task ownership stay in Tunnel."""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import inspect
import json
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from app.core import fsops
from app.core.execution_context import VerifiedContext, owner_key
from app.profiles import manager
from app.paths import CONFIG_DIR, RUNTIME_DIR
READ = {'ping','runtime_info','get_root','exists','list','tree','stat','read',
        'read_bytes_b64','search','hash','diff','syntax_check','backup_list',
        'cross_profile_capabilities','profile_list','profile_get','profile_default_get','profile_reload',
        'profile_pending_list','profile_request_status'}
CONTROL = {'ping','runtime_info','get_root','profile_list','profile_get','profile_default_get','profile_reload',
           'profile_pending_list','profile_request_status','cross_profile_capabilities'}
BACKGROUND = {'tree','search','hash','diff','copy','move','delete','backup','restore',
              'zip','unzip','copy_between_profiles','copy_batch_between_profiles'}
WORK = contextvars.ContextVar('zagent_work', default=None)


def uid(prefix):
    return prefix + '_' + uuid.uuid4().hex


def canonical(path):
    return os.path.normcase(str(Path(path).resolve())).replace('\\', '/').rstrip('/')


def overlap(a, b):
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')


class Locks:
    """Atomic multi-path reader/writer locks; ancestors conflict with descendants."""
    def __init__(self):
        self.condition = asyncio.Condition()
        self.active = []
        self.waiters = []

    @staticmethod
    def conflicts(a, b):
        return any(overlap(x, y) and (xm == 'write' or ym == 'write')
                   for x, xm in a for y, ym in b)

    @asynccontextmanager
    async def acquire(self, resources):
        ticket = (object(), resources)
        start = time.monotonic()
        async with self.condition:
            self.waiters.append(ticket)
            try:
                await self.condition.wait_for(lambda:
                    not any(self.conflicts(resources, r) for _, r in self.active)
                    and not any(self.conflicts(resources, r)
                                for _, r in self.waiters[:self.waiters.index(ticket)]))
                self.active.append(ticket)
            finally:
                self.waiters.remove(ticket)
                self.condition.notify_all()
        try:
            yield (time.monotonic() - start) * 1000
        finally:
            async with self.condition:
                self.active.remove(ticket)
                self.condition.notify_all()


class Journal:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.instance = path.with_suffix('.owner').open('a+b')
        self.instance.seek(0)
        self.instance.write(b'0')
        self.instance.flush()
        self.instance.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(self.instance.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (
          session_id TEXT PRIMARY KEY, mounts TEXT NOT NULL, active TEXT NOT NULL,
          updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS operations (
          operation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, idem TEXT NOT NULL,
          fingerprint TEXT NOT NULL, operation TEXT NOT NULL, state TEXT NOT NULL,
          metadata TEXT NOT NULL, result TEXT, error TEXT, checkpoint TEXT NOT NULL DEFAULT '{}',
          updated REAL NOT NULL, UNIQUE(session_id, idem));
        ''')
        # An interrupted generic mutation may have committed before the crash.
        # Never blindly replay it. Only the checkpointed batch is resumable.
        self.db.execute("UPDATE operations SET state=CASE WHEN operation='copy_batch_between_profiles' THEN 'recovering' ELSE 'orphaned' END WHERE state IN ('running','waiting_lock','waiting_capacity')")
        self.db.commit()

    def close(self):
        self.db.close()
        self.instance.close()

    def get(self, opid, session_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM operations WHERE operation_id=? AND session_id=?',
                                  (opid, session_id)).fetchone()
            if not row:
                raise KeyError('Operation not found in this session')
            result = dict(row)
            for key in ('metadata','result','checkpoint'):
                result[key] = json.loads(result[key]) if result[key] else None
            return result

    def find_by_task(self, task_id, session_id):
        wanted = str(task_id or '')
        if not wanted:
            raise ValueError('task_id is required when operation_id is omitted')
        with self.lock:
            rows = self.db.execute(
                'SELECT operation_id,metadata FROM operations WHERE session_id=? ORDER BY updated DESC',
                (session_id,),
            ).fetchall()
            for row in rows:
                try:
                    meta = json.loads(row['metadata'] or '{}')
                except Exception:
                    meta = {}
                if str(meta.get('task_id') or '') == wanted:
                    opid = str(row['operation_id'])
                    break
            else:
                raise KeyError('Operation not found for this task in this session')
        return self.get(opid, session_id)

    def update(self, opid, **fields):
        for key in ('metadata','result','checkpoint'):
            if key in fields:
                fields[key] = json.dumps(fields[key], ensure_ascii=False)
        fields['updated'] = time.time()
        with self.lock:
            self.db.execute('UPDATE operations SET '+','.join(k+'=?' for k in fields)+' WHERE operation_id=?',
                            [*fields.values(), opid])
            self.db.commit()

    def claim(self, op, session, idem, fingerprint, meta):
        with self.lock:
            row = self.db.execute('SELECT * FROM operations WHERE session_id=? AND idem=?', (session, idem)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint:
                    raise ValueError('Idempotency key reused with different operation, arguments or profile')
                return row['operation_id'], False
            opid = uid('op')
            self.db.execute('INSERT INTO operations(operation_id,session_id,idem,fingerprint,operation,state,metadata,updated) VALUES(?,?,?,?,?,?,?,?)',
                            (opid, session, idem, fingerprint, op, 'waiting_capacity', json.dumps(meta), time.time()))
            self.db.commit()
            return opid, True


class Engine:
    def __init__(self, operations, runtime=None):
        self.operations = operations
        self.runtime = runtime or RUNTIME_DIR
        self.journal = Journal(self.runtime / 'operations.db')
        self.locks = Locks()
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='zagent-files')
        self.capacity = asyncio.Semaphore(2)
        self.background = asyncio.Semaphore(6)
        self.running = {}
        self.cancel_flags = {}

    def approved(self, name):
        p = manager.get_profile(name)
        if not p.get('enabled', True) or not p.get('authorized_by_user'):
            raise PermissionError('Profile disabled or not approved')
        return p

    def session(self, session_id, profiles=None, active=None):
        if not session_id or len(session_id) > 256:
            raise ValueError('A stable session_id is required')
        with self.journal.lock:
            row = self.journal.db.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
            if profiles is not None:
                if not profiles or len(profiles) > 64:
                    raise ValueError('Provide 1..64 approved profiles')
                profiles = list(dict.fromkeys(profiles))
                for name in profiles:
                    self.approved(name)
                active = active or profiles[0]
                if active not in profiles:
                    raise ValueError('Active profile must be mounted')
                self.journal.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)',
                    (session_id, json.dumps(profiles), active, time.time()))
                self.journal.db.commit()
                return {'session_id': session_id, 'profiles': profiles, 'active_profile': active}
            if not row:
                raise KeyError('Session has not been created yet')
            return {'session_id': session_id, 'profiles': json.loads(row['mounts']), 'active_profile': row['active']}

    def session_list(self):
        with self.journal.lock:
            rows = self.journal.db.execute(
                "SELECT session_id,mounts,active,updated FROM sessions WHERE session_id <> 'legacy' ORDER BY updated DESC"
            ).fetchall()
        return [
            {
                'session_id': row['session_id'],
                'profiles': json.loads(row['mounts']),
                'active_profile': row['active'],
                'updated': row['updated'],
            }
            for row in rows
        ]

    def ensure_session(self, session_id, seed_profile_id=None):
        """Open or recover a durable session without silently changing its active root.

        seed_profile_id is used only when the session does not yet exist. Once a
        session exists, its active profile is authoritative until an explicit
        session switch occurs.
        """
        try:
            return self.session(session_id)
        except KeyError:
            requested = seed_profile_id or manager.default_profile_name()
            self.approved(requested)
            return self.session(session_id, [requested], requested)

    def mount_profile(self, session_id, profile_id):
        """Mount an approved profile for cross-profile work without making it active."""
        current = self.ensure_session(session_id)
        self.approved(profile_id)
        if profile_id not in current['profiles']:
            current = self.session(
                session_id,
                [*current['profiles'], profile_id],
                current['active_profile'],
            )
        return current

    def switch_session(self, session_id, profile_id):
        """Explicitly switch one session. This never changes the global default."""
        current = self.ensure_session(session_id)
        self.approved(profile_id)
        if profile_id not in current['profiles']:
            current = self.session(
                session_id,
                [*current['profiles'], profile_id],
                current['active_profile'],
            )
        return self.session(session_id, current['profiles'], profile_id)

    def bind(self, session_id, seed_profile_id=None):
        session = self.ensure_session(session_id, seed_profile_id)
        name = session['active_profile']
        if name not in session['profiles']:
            raise PermissionError('Active profile is not mounted in this session')
        return self.approved(name)

    def bind_named(self, session_id, profile_id):
        session = self.mount_profile(session_id, profile_id)
        if profile_id not in session['profiles']:
            raise PermissionError('Profile not mounted in this session')
        return self.approved(profile_id)

    def resources(self, op, args, profile, session_id):
        mode = 'read' if op in READ else 'write'
        if op.startswith('profile_'):
            return [(canonical(CONFIG_DIR), mode)]
        if op == 'copy_batch_between_profiles' or op == 'copy_between_profiles':
            sp = self.bind_named(session_id, args['source_profile'])
            dp = self.bind_named(session_id, args['destination_profile'])
            fsops.require_write(dp)
            if op == 'copy_between_profiles':
                entries = [(sp, args['source_path'], 'read'), (dp, args['destination_path'], 'write')]
            else:
                entries = [(sp, p, 'read') for p in args['paths']]
                entries += [(dp, args['destination_dir'], 'write')]
            return [(canonical(fsops.resolve(p, pr)), m) for pr, p, m in entries]
        paths = []
        for key in ('path','path_a','path_b','src','dst','source','zip_path','dest_dir'):
            if key in args:
                m = mode
                if op in {'copy','zip','unzip'} and key in {'src','source'}:
                    m = 'read'
                if op == 'unzip' and key == 'zip_path':
                    m = 'read'
                paths.append((canonical(fsops.resolve(args[key], profile)), m))
        if op == 'restore':
            bid = args['backup_id']
            if not bid or any(c not in '0123456789_' for c in bid):
                raise ValueError('Invalid backup ID')
            data = json.loads((fsops.BACKUP_ROOT / bid / 'metadata.json').read_text())
            if data['profile'] != profile['name']:
                raise PermissionError('Backup belongs to another profile')
            paths.append((canonical(fsops.resolve(data['original_path'], profile)), 'write'))
        return paths or [(canonical(profile['root']), mode)]

    def preflight(self, op, args, profile):
        if op == 'copy_between_profiles':
            sp, dp = manager.get_profile(args['source_profile']), manager.get_profile(args['destination_profile'])
            src = fsops.resolve(args['source_path'], sp)
            dst = fsops.resolve(args['destination_path'], dp)
            fsops.guard_root_delete(dst, dp)
            if overlap(canonical(src), canonical(dst)):
                raise ValueError('Source and destination must not overlap')
            for path, p in ((src,sp),(dst,dp)):
                fsops.guard_secret(path)
                if path.is_dir():
                    for child in path.rglob('*'):
                        fsops.guard_secret(fsops.resolve(str(child), p))
        if op not in READ and not op.startswith('profile_') and op not in {'copy_between_profiles','copy_batch_between_profiles','backup'}:
            fsops.require_write(profile)
        for key in ('path','path_a','path_b','src','dst','source','zip_path','dest_dir'):
            if key in args:
                path = fsops.resolve(args[key], profile)
                fsops.guard_secret(path)
                if key in {'dst','dest_dir','zip_path'} and op not in READ:
                    fsops.guard_root_delete(path, profile)
                # Recursive legacy operations must not dereference links out of sandbox.
                if path.is_dir() and op in {'copy','move','delete','backup','zip'}:
                    for child in path.rglob('*'):
                        fsops.guard_secret(fsops.resolve(str(child), profile))
        if 'src' in args and 'dst' in args:
            a, b = canonical(fsops.resolve(args['src'], profile)), canonical(fsops.resolve(args['dst'], profile))
            if overlap(a,b):
                raise ValueError('Source and destination must not overlap')

    def capability(self, op):
        return {'execution_type': 'background' if op in BACKGROUND else 'fast',
                'read_only': op in READ, 'supports_resume': op == 'copy_batch_between_profiles',
                'supports_progress': op == 'copy_batch_between_profiles',
                'supports_cancel': op == 'copy_batch_between_profiles',
                'resource_key': 'canonical absolute path; derived by agent',
                'recovery': 'checkpoint_resume' if op == 'copy_batch_between_profiles' else 'completed_result_replay_or_manual_reconciliation'}

    async def execute(self, op, args=None, metadata=None):
        if not isinstance(metadata, VerifiedContext):
            raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
        args, meta = dict(args or {}), dict(metadata)
        if time.time() >= meta['expires_at']:
            raise PermissionError('CONTEXT_EXPIRED')
        if op.startswith('files_'):
            op = op[6:]
        if op not in READ and meta['effective_access'] != 'write':
            raise PermissionError('WRITE_SCOPE_REQUIRED')
        # Root approval is local; resource membership comes from trusted Router.
        allowed = {r.get('profile_id') for r in meta['effective_resources'] if r['kind'] == 'files'}
        if not allowed or None in allowed:
            raise PermissionError('FILES_PROFILE_SCOPE_REQUIRED')
        for name in ('profile_id', 'source_profile', 'destination_profile'):
            requested = meta.get(name) if name == 'profile_id' else args.get(name)
            if requested and requested not in allowed:
                raise PermissionError('PROFILE_NOT_IN_RESOURCE_SCOPE')
        meta.setdefault('profile_id', sorted(allowed)[0])
        if op.startswith('profile_') and op != 'profile_switch':
            raise PermissionError('PROFILE_ADMINISTRATION_IS_MANAGEMENT_PLANE')
        if op == 'profile_switch' and args.get('name') not in allowed:
            raise PermissionError('PROFILE_NOT_IN_RESOURCE_SCOPE')
        if op.startswith('files_'):
            op = op[6:]
        if op not in self.operations:
            raise ValueError('Unknown operation: '+op)
        inspect.signature(self.operations[op]).bind(**args)
        sid = owner_key(meta)
        self.ensure_session(sid, meta.get('profile_id'))
        # Resource selection is explicit and cannot silently change another root.
        profile = self.bind_named(sid, meta['profile_id'])
        if profile['name'] not in allowed:
            raise PermissionError('ACTIVE_PROFILE_NOT_IN_RESOURCE_SCOPE')
        meta.update(session_id=sid, profile_id=profile['name'])
        for key, prefix in [('request_id','req'),('task_id','tsk'),('trace_id','trc')]:
            meta[key] = str(meta.get(key) or uid(prefix))
        if op == 'profile_switch':
            current = self.switch_session(sid, args['name'])
            meta['profile_id'] = current['active_profile']
            return self.envelope({
                **current,
                'scope': 'session',
                'global_default_profile': manager.default_profile_name(),
            }, meta)
        resources = self.resources(op, args, profile, sid)
        # Caller-supplied lock labels/access_mode can never weaken agent locks.
        meta['resources'] = [list(r) for r in resources]
        if op in CONTROL:
            token = manager.BOUND_PROFILE.set(profile)
            try:
                value = self.operations[op](**args)
                return self.envelope(value, meta)
            finally:
                manager.BOUND_PROFILE.reset(token)
        fingerprint = hashlib.sha256(json.dumps([op,args,profile,resources], sort_keys=True).encode()).hexdigest()
        idem = str(meta.get('idempotency_key') or meta['operation_id'])
        opid, created = self.journal.claim(op, sid, idem, fingerprint, meta)
        meta['parent_operation_id'] = meta['operation_id']
        meta['operation_id'], meta['idempotency_key'] = opid, idem
        if not created:
            if opid in self.running:
                return await asyncio.shield(self.running[opid])
            row = self.journal.get(opid, sid)
            if row['state'] == 'succeeded':
                return row['result']
            if row['state'] != 'recovering' or op != 'copy_batch_between_profiles':
                raise RuntimeError('Operation '+row['state']+'; inspect files_operation_status before reconciliation')
        if len(self.running) >= 128:
            self.journal.update(opid, state='failed', error='Backpressure: too many pending operations')
            raise RuntimeError('Agent capacity exceeded')
        flag = threading.Event()
        self.cancel_flags[opid] = flag
        runner = asyncio.create_task(self._run(op, args, meta, profile, resources, flag))
        self.running[opid] = runner
        def finished(task):
            self.running.pop(opid, None)
            self.cancel_flags.pop(opid, None)
            if not task.cancelled():
                task.exception()  # retrieve exception if the requester disconnected
        runner.add_done_callback(finished)
        # Keep the worker alive if an HTTP waiter disconnects. For resumable batch
        # operations, a Tunnel cancellation also becomes a cooperative local cancel.
        try:
            return await asyncio.shield(runner)
        except asyncio.CancelledError:
            if op == 'copy_batch_between_profiles':
                flag.set()
            raise

    @staticmethod
    def envelope(value, meta):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        return {'ok': True, 'data': value, '_meta': {'zagent.'+k: v for k,v in meta.items()}}

    async def _run(self, op, args, meta, profile, resources, flag):
        opid = meta['operation_id']
        started = time.monotonic()
        try:
            self.journal.update(opid, state='waiting_lock')
            async with self.locks.acquire(resources) as lock_ms:
                self.journal.update(opid, state='waiting_capacity', metadata=meta)
                async with self.background if op in BACKGROUND else self.capacity:
                    # Background pool is capped at 6, preserving two threads for short calls.
                    self.journal.update(opid, state='running')
                    def work():
                        if time.time() >= meta['expires_at']:
                            raise PermissionError('CONTEXT_EXPIRED_WHILE_QUEUED')
                        p = self.bind_named(meta['session_id'], profile['name'])
                        if p != profile:
                            raise PermissionError('Profile changed while operation was queued')
                        token = manager.BOUND_PROFILE.set(profile)
                        worktoken = WORK.set((self, meta, flag))
                        try:
                            if flag.is_set():
                                raise InterruptedError('Cancelled before execution')
                            self.preflight(op, args, profile)
                            return self.operations[op](**args)
                        finally:
                            WORK.reset(worktoken)
                            manager.BOUND_PROFILE.reset(token)
                    result = await asyncio.get_running_loop().run_in_executor(self.pool, work)
                    meta.update(lock_wait_ms=round(lock_ms,3), duration_ms=round((time.monotonic()-started)*1000,3))
                    output = self.envelope(result, meta)
                    self.journal.update(opid, state='succeeded', result=output)
                    return output
        except asyncio.CancelledError:
            self.journal.update(opid, state='cancelled', error='Cancelled before worker thread started')
            raise
        except InterruptedError as exc:
            self.journal.update(opid, state='cancelled', error=str(exc))
            raise
        except Exception as exc:
            self.journal.update(opid, state='failed', error=str(exc))
            raise

    def cancel(self, operation_id=None, session_id=None, task_id=None):
        if not session_id:
            raise ValueError('session_id is required')
        row = (self.journal.get(operation_id, session_id)
               if operation_id else self.journal.find_by_task(task_id, session_id))
        operation_id = row['operation_id']
        if row['operation'] != 'copy_batch_between_profiles':
            raise ValueError('Operation does not support cooperative cancellation')
        if row['state'] in {'succeeded','failed','cancelled','orphaned'}:
            return {'operation_id': operation_id, 'task_id': task_id,
                    'cancel_requested': False, 'state': row['state'], 'terminal': True}
        runner = self.running.get(operation_id)
        flag = self.cancel_flags.get(operation_id)
        mode = 'none'
        requested = False
        if row['state'] in {'waiting_lock','waiting_capacity'} and runner and not runner.done():
            runner.cancel()
            requested = True
            mode = 'cancel_waiter'
        elif flag:
            flag.set()
            requested = True
            mode = 'cooperative'
        elif row['state'] == 'recovering':
            self.journal.update(operation_id, state='cancelled', error='Cancelled during recovery')
            requested = True
            mode = 'cancel_recovery'
        return {'operation_id': operation_id, 'task_id': task_id,
                'cancel_requested': requested, 'state': row['state'], 'mode': mode}

    async def close(self):
        if self.running:
            await asyncio.gather(*list(self.running.values()), return_exceptions=True)
        self.pool.shutdown(wait=True)
        self.journal.close()


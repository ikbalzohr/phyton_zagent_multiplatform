"""Actual scheduler + AST-isolated Router executor pre-dispatch regression tests.
Imports are sandboxed by the test runner before loading router modules.
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock
from router import orchestration as m
from router.access import AuthorizationError, owner_key

SERVER = Path(__file__).resolve().parents[1] / 'router/server.py'


class PreDispatchTests(unittest.IsolatedAsyncioTestCase):
    def executor(self, *, isolated=False, preflight_error=None, invoke_error=None):
        lock = asyncio.Lock()
        conn = SimpleNamespace(execute=lambda *_args: SimpleNamespace(fetchone=lambda: (1,) if isolated else None))
        auth = SimpleNamespace(owner='owner')
        revalidate = AsyncMock(return_value=auth, side_effect=preflight_error)
        invoke = AsyncMock(return_value={'ok': True}, side_effect=invoke_error)
        registry = SimpleNamespace(get_mapping=lambda _: ('zagent_files', 'files_write'), invoke=invoke)
        space = dict(asyncio=asyncio, Any=object, orchestrator=SimpleNamespace(journal=SimpleNamespace(_lock=lock, conn=conn)),
                     _FILES_IMMEDIATE_CONTROLS=frozenset(), AuthorizationError=AuthorizationError,
                     PreDispatchRejected=getattr(m,'PreDispatchRejected',RuntimeError), _revalidate=revalidate,
                     placement=SimpleNamespace(validate=lambda *_:None), _policy=lambda _:{'enabled':True}, registry=registry)
        node = next(n for n in ast.parse(SERVER.read_text(encoding='utf-8')).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_executor')
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(SERVER),'exec'),space)
        ctx=SimpleNamespace(resource_key='installation:fixture',task_id='current',session_id='owner',target_device_id='device',execution_context={'public_tool':'files_write'})
        return space['_executor'],ctx,invoke

    async def test_invalid_token_is_explicitly_pre_dispatch(self):
        execute,ctx,invoke=self.executor(preflight_error=AuthorizationError('invalid_token',401))
        with self.assertRaises(getattr(m,'PreDispatchRejected',RuntimeError)):
            await execute('zagent_files','files_write',{},ctx)
        invoke.assert_not_awaited()

    async def test_existing_isolation_rejection_does_not_dispatch(self):
        execute,ctx,invoke=self.executor(isolated=True)
        with self.assertRaises(getattr(m,'PreDispatchRejected',RuntimeError)):
            await execute('zagent_files','files_write',{},ctx)
        invoke.assert_not_awaited()

    async def test_error_after_backend_dispatch_is_not_reclassified(self):
        error=AuthorizationError('UPSTREAM_UNKNOWN',403)
        execute,ctx,invoke=self.executor(invoke_error=error)
        with self.assertRaises(AuthorizationError) as caught:
            await execute('zagent_files','files_write',{},ctx)
        self.assertIs(caught.exception,error)
        invoke.assert_awaited_once()

    async def run_job(self,orchestrator):
        receipt=await orchestrator.submit('zagent_files','files_write',{}, {'session_id':owner_key('fixture','workspace'),'resource_key':'installation:fixture','access_mode':'write','priority':2})
        await orchestrator._run_task(receipt['task_id'],0,'background')
        return await orchestrator.journal.get(receipt['task_id'])

    async def test_pre_dispatch_failure_does_not_poison_next_writer(self):
        with tempfile.TemporaryDirectory() as root:
            attempts=0
            async def execute(*_args):
                nonlocal attempts
                attempts+=1
                if attempts==1:
                    raise getattr(m,'PreDispatchRejected',RuntimeError)('invalid_token')
                return {'ok':True}
            o=m.Orchestrator(execute,Path(root)/'tasks.db')
            try:
                first=await self.run_job(o)
                self.assertEqual(first['state'],'failed')
                self.assertEqual(first['error'],'invalid_token')
                second=await self.run_job(o)
                self.assertEqual(second['state'],'succeeded')
                self.assertEqual(o.journal.conn.execute("SELECT COUNT(*) FROM tasks WHERE state='orphaned' AND started_at IS NOT NULL").fetchone()[0],0)
            finally:o.journal.conn.close()

    async def test_uncertain_dispatched_writer_remains_orphaned(self):
        with tempfile.TemporaryDirectory() as root:
            async def execute(*_args):raise RuntimeError('unknown after backend dispatch')
            o=m.Orchestrator(execute,Path(root)/'tasks.db')
            try:self.assertEqual((await self.run_job(o))['state'],'orphaned')
            finally:o.journal.conn.close()


if __name__=='__main__':unittest.main()

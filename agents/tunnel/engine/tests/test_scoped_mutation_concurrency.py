"""Isolated source/journal tests; no live owner files are modified."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from router.resource_scope import scoped_write_key
from router.orchestration import Orchestrator

def ctx(path="one.txt", profile="agent-dev"):
    return {"context_version":1,"required_scope":"files:write",
            "effective_access":"write","public_tool":"files_write",
            "installation_id":"install","effective_resources":[{"kind":"files",
            "resource_id":"approved:files","profile_id":profile}],
            "path":path}

def meta(c, key):
    return {"session_id":"owner_v1_fixture", "resource_key":"installation:install",
            "access_mode":"write", "priority":2,
            "task_id":"tsk_"+key*32,"execution_context":c}

class ScopedContract(unittest.TestCase):
    def test_canonical_case_separator_and_same_file_exclusive(self):
        one=ctx()
        self.assertEqual(scoped_write_key(one,"zagent_files","files_write",{"path":"A/b.txt"}),
                         scoped_write_key(one,"zagent_files","files_write",{"path":"a\\B.TXT"}))

    def test_writes_only_and_dangerous_paths_fallback(self):
        c=ctx()
        for p in ("../other", "a/../b", "C:\\Windows\\file", "//server/share", "x:", "folder/", "a/./b",
                  "a//b", "a/<b", ""):
            with self.subTest(p=p):
                self.assertIsNone(scoped_write_key(c,"zagent_files","files_write",{"path":p}))
        for tool in ("files_exec_command","files_delete","files_copy","files_move","files_mkdir","qgis_make_map"):
            self.assertIsNone(scoped_write_key(dict(c,public_tool=tool),"zagent_files",tool,{"path":"foo.txt"}))
        self.assertIsNone(scoped_write_key(c,"zagent_arcmap","files_write",{"path":"a.txt"}))
        self.assertIsNone(scoped_write_key(dict(c,effective_access="read"),"zagent_files","files_write",{"path":"a.txt"}))

class ScopedScheduler(unittest.IsolatedAsyncioTestCase):
    async def test_disjoint_writers_parallel_same_file_serialized_and_global_blocks(self):
        entered=set();gate=asyncio.Event()
        async def work(service,tool,args,context):
            entered.add(args["path"] if "path" in args else "global")
            await gate.wait()
            return {"ok":True}
        with tempfile.TemporaryDirectory() as td:
            o=Orchestrator(work,Path(td)/"tasks.db")
            tasks=[]
            try:
                for i,p in (("1","a.txt"),("2","b.txt")):
                    c=ctx();c["task_id"]="tsk_"+i*32
                    receipt=await o.submit("zagent_files","files_write",{"path":p},meta(c,i))
                    tasks.append(asyncio.create_task(o._run_task(receipt["task_id"],0,"background")))
                await asyncio.wait_for(self._await_entered(entered,{"a.txt","b.txt"}),3)
                # Same file and non-scoped command must wait while readers own installation shared lease
                for i,p,tool in (("3","a.txt","files_write"),("4",None,"files_exec_command")):
                    c=ctx();c["task_id"]="tsk_"+i*32;c["public_tool"]=tool
                    args={"path":p} if p else {}
                    receipt=await o.submit("zagent_files",tool,args,meta(c,i))
                    tasks.append(asyncio.create_task(o._run_task(receipt["task_id"],1,"background")))
                await asyncio.sleep(.075)
                self.assertEqual(entered,{"a.txt","b.txt"})
                gate.set()
                await asyncio.wait_for(asyncio.gather(*tasks),3)
                self.assertIn("global",entered)
            finally:
                gate.set()
                for t in tasks:
                    if not t.done():t.cancel()
                if tasks: await asyncio.gather(*tasks,return_exceptions=True)
                o.journal.conn.close()

    async def _await_entered(self, entered, targets):
        while not targets.issubset(entered):
            await asyncio.sleep(.01)

    async def test_profile_alias_boundary_falls_back_to_global(self):
        with tempfile.TemporaryDirectory() as td:
            o=Orchestrator(lambda *a: asyncio.sleep(0),Path(td)/"tasks.db")
            try:
                from types import SimpleNamespace
                mk=lambda p: SimpleNamespace(access_mode="write",service_id="zagent_files",tool_name="files_write",
                    execution_context=ctx(profile=p))
                self.assertTrue(o._subresource(mk("a"),{"path":"x.txt"}))
                self.assertIsNone(o._subresource(mk("b"),{"path":"y.txt"}))
            finally:o.journal.conn.close()
if __name__=="__main__":unittest.main()

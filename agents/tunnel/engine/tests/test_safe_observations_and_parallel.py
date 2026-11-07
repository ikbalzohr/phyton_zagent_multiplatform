"""Red/green regression: orphan-aware safe observation and non-serialized reads.

Only local fixtures; never touches a live task journal, installed Core or user files.
"""
import asyncio
import json
import tempfile
import time
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from router.access import AuthContext
from router.execution_context import scheduler_meta
from router.identity import Placement
from router.orchestration import Orchestrator, PreDispatchRejected
from router.registry import MCPRegistry
from router.orphan_conflicts import nonblocking_probe, safe_read_target
from router import server


def context(tool="files_ping", access="read", scope="files:read"):
    return {
        "context_version": 1,
        "principal_id": "owner",
        "workspace_id": "workspace",
        "device_id": "device",
        "installation_id": "install",
        "task_id": "tsk_" + "1" * 32,
        "request_id": "req_" + "1" * 32,
        "trace_id": "trc_" + "1" * 32,
        "effective_resources": [{"kind": "files", "resource_id": "workspace:files", "profile_id": "dev"}],
        "effective_access": access,
        "required_scope": scope,
        "public_tool": tool,
    }


def orphan_file_command():
    ctx = context("files_exec_command", "write", "files:execute")
    return {
        "service_id": "zagent_files",
        "tool_name": "files_exec_command",
        "resource_key": "installation:install",
        "target_device_id": "device",
        "executed_on": "device",
        "execution_context_json": json.dumps(ctx),
        "arguments_json": json.dumps({"executable": "python", "args": ["--version"]}),
    }


class ReadOnlyObservationContract(unittest.TestCase):
    def test_safe_files_ping_read_survives_uncertain_command(self):
        c = context()
        self.assertTrue(safe_read_target("zagent_files", "files_ping", c))
        self.assertTrue(safe_read_target("zagent_files", "files_read", dict(c, public_tool="files_read")))
        self.assertTrue(safe_read_target("zagent_files", "files_search", dict(c, public_tool="files_search")))

    def test_trusted_scope_and_exact_service_required(self):
        c = context()
        for bad in (
            dict(c, required_scope="files:execute"),
            dict(c, effective_access="write"),
            dict(c, public_tool="files_delete"),
            dict(c, effective_resources=[{"kind": "arcmap", "resource_id": "installation:install"}]),
            dict(c, context_version=2),
        ):
            with self.subTest(bad=bad):
                self.assertFalse(safe_read_target("zagent_files", "files_ping", bad))
        self.assertFalse(safe_read_target("zagent_arcmap", "files_ping", c))
        self.assertFalse(safe_read_target("zagent_files", "files_exec_command", context("files_exec_command", "write", "files:execute")))
        self.assertFalse(safe_read_target("zagent_qgis", "qgis_process", context("qgis_process", "write", "files:execute")))

    def test_legacy_arcmap_capabilities_orphan_is_nonblocking(self):
        ctx = context("arcmap_execution_capabilities", "write", "arcmap:inspect")
        ctx["effective_resources"] = [{"kind": "arcmap", "resource_id": "installation:install"}]
        row = {
            "service_id": "zagent_arcmap",
            "tool_name": "arcmap_execution_capabilities",
            "resource_key": "installation:install",
            "target_device_id": "device",
            "executed_on": "device",
            "execution_context_json": json.dumps(ctx),
            "arguments_json": "{}",
        }
        self.assertTrue(nonblocking_probe(row))
        self.assertTrue(safe_read_target("zagent_arcmap", "arcmap_execution_capabilities", ctx))
        self.assertFalse(nonblocking_probe(dict(row, arguments_json='{"mode":"attached"}')))
        self.assertFalse(nonblocking_probe(dict(row, executed_on="wrong")))

    def test_scheduler_read_parallel_and_writer_exclusive(self):
        c = context()
        self.assertEqual(scheduler_meta(c, "owner")["access_mode"], "read")
        self.assertEqual(scheduler_meta(context("files_exec_command", "write", "files:execute"), "owner")["access_mode"], "write")
        self.assertEqual(scheduler_meta(c, "owner")["resource_key"], "installation:install")


class ExecutorIsolation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.orch = Orchestrator(AsyncMock(), Path(self.temp.name) / "tasks.db")
        self.addCleanup(self.orch.journal.conn.close)
        o = orphan_file_command()
        await self.orch.journal.create({
            "task_id": "tsk_" + "a" * 32,
            "session_id": "owner_v1_test",
            "request_id": "req_test",
            "trace_id": "trc_test",
            "service_id": o["service_id"],
            "tool_name": o["tool_name"],
            "resource_key": o["resource_key"],
            "access_mode": "write",
            "priority": 2,
            "state": "orphaned",
            "created_at": 1,
            "updated_at": 1,
            "started_at": 1,
            "arguments_json": o["arguments_json"],
            "execution_context_json": o["execution_context_json"],
            "target_device_id": "device",
            "executed_on": "device",
        })
        self.auth = SimpleNamespace(owner="owner_v1_test")
        self.c = context()
        self.c["task_id"] = "tsk_" + "b" * 32
        self.ctx = self.orch.context("zagent_files", "files_ping",
                                     scheduler_meta(self.c, self.auth.owner),
                                     task_id=self.c["task_id"])
        self.patches = [
            patch.object(server, "orchestrator", self.orch),
            patch.object(server, "_revalidate", AsyncMock(return_value=self.auth)),
            patch.object(server, "placement", Placement("device", "install")),
            patch.object(server, "_policy", lambda name: {"scope": "files:read", "enabled": True}),
            patch.object(server.registry, "get_mapping", lambda name: ("zagent_files", name)),
            patch.object(server.registry, "invoke", AsyncMock(return_value={"ok": True})),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_read_runs_despite_uncertain_files_command(self):
        result = await server._executor("zagent_files", "files_ping", {}, self.ctx)
        self.assertEqual(result, {"ok": True})
        server.registry.invoke.assert_awaited_once()

    async def test_mutation_still_blocks_without_replaying(self):
        c = context("files_write", "write", "files:write")
        c["task_id"] = "tsk_" + "c" * 32
        ctx = self.orch.context("zagent_files", "files_write",
            scheduler_meta(c, self.auth.owner), task_id=c["task_id"])
        with self.assertRaisesRegex(PreDispatchRejected, "RESOURCE_RECONCILIATION_REQUIRED"):
            await server._executor("zagent_files", "files_write", {"path":"x", "content":"y"}, ctx)
        server.registry.invoke.assert_not_awaited()


class GenuineReaderConcurrency(unittest.IsolatedAsyncioTestCase):
    async def test_two_authenticated_reads_run_in_parallel_but_writer_waits(self):
        """Exercise real durable scheduler leases, not a mocked lock helper."""
        with tempfile.TemporaryDirectory() as folder:
            active = 0
            peak = 0
            both_entered = asyncio.Event()
            release_reads = asyncio.Event()
            write_entered = asyncio.Event()

            async def execute(service, tool, arguments, ctx):
                nonlocal active, peak
                if tool == "files_write":
                    write_entered.set()
                    return {"ok": True}
                active += 1
                peak = max(peak, active)
                if active == 2:
                    both_entered.set()
                await release_reads.wait()
                active -= 1
                return {"ok": True}

            orch = Orchestrator(execute, Path(folder) / "tasks.db")
            jobs = []
            try:
                for key in ("d", "e"):
                    ctx = context()
                    ctx["task_id"] = "tsk_" + key * 32
                    ctx["request_id"] = "req_" + key * 32
                    receipt = await orch.submit(
                        "zagent_files", "files_ping", {}, scheduler_meta(ctx, "owner_v1_test"))
                    jobs.append(asyncio.create_task(orch._run_task(receipt["task_id"], 0, "fast")))

                await asyncio.wait_for(both_entered.wait(), 3)
                self.assertEqual(peak, 2)
                writer_ctx = context("files_write", "write", "files:write")
                writer_ctx["task_id"] = "tsk_" + "f" * 32
                writer = await orch.submit("zagent_files", "files_write", {},
                                            scheduler_meta(writer_ctx, "owner_v1_test"))
                write_task = asyncio.create_task(orch._run_task(writer["task_id"], 1, "general"))
                jobs.append(write_task)
                await asyncio.sleep(.06)
                self.assertFalse(write_entered.is_set(), "writer bypassed active reader leases")
                release_reads.set()
                await asyncio.wait_for(asyncio.gather(*jobs), 5)
                self.assertTrue(write_entered.is_set())
                for task_id in [writer["task_id"], "tsk_"+"d"*32, "tsk_"+"e"*32]:
                    self.assertEqual((await orch.journal.get(task_id))["state"], "succeeded")
            finally:
                release_reads.set()
                for job in jobs:
                    if not job.done():
                        job.cancel()
                if jobs:
                    await asyncio.gather(*jobs, return_exceptions=True)
                orch.journal.conn.close()


class UpstreamPreDispatchContract(unittest.IsolatedAsyncioTestCase):
    async def test_initialized_failure_never_marks_effect_started_or_orphans(self):
        """Failure during MCP initialize/list occurs before tools/call dispatch."""
        reg = MCPRegistry.__new__(MCPRegistry)
        reg.states = {"zagent_arcmap": object()}
        reg.ensure_initialized = AsyncMock(side_effect=RuntimeError("upstream offline"))
        with self.assertRaisesRegex(PreDispatchRejected, "UPSTREAM_INITIALIZATION_UNAVAILABLE"):
            await reg.invoke("zagent_arcmap", "arcmap_execution_capabilities", {}, SimpleNamespace())

        with tempfile.TemporaryDirectory() as folder:
            orch = Orchestrator(reg.invoke, Path(folder) / "tasks.db")
            try:
                meta = {"session_id": "owner_v1_test", "resource_key": "installation:install",
                        "access_mode": "write", "priority": 2}
                receipt = await orch.submit("zagent_arcmap", "arcmap_execution_capabilities", {}, meta)
                await orch._run_task(receipt["task_id"], 0, "background")
                row = await orch.journal.get(receipt["task_id"])
                self.assertEqual(row["state"], "failed")
                self.assertEqual(row["error"], "UPSTREAM_INITIALIZATION_UNAVAILABLE")
            finally:
                orch.journal.conn.close()


if __name__ == "__main__":
    unittest.main()

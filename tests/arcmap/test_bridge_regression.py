"""Regression tests against real ArcMap source; never touches a live MXD.

Only ArcPy/transport are simulated. Authentication and safety functions are real;
synthetic in-process issuer metadata is fixture authority, not private credentials.
Module fixtures are deferred until execution and restored for same-process suites.
"""
import asyncio
from contextlib import contextmanager, ExitStack
import importlib
import json
import os
import pathlib
import shutil
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / "agents/arcmap/engine"
_PREFIXES = ("arcpy", "core", "features", "mcp_server", "stage3", "orchestrator")


def _fixture_module(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _PREFIXES)


def setUpModule():
    global TEMP, frame, document, arcpy, bridge_state, ipc, current_map
    global inspection, export_feature, ipc_client, visual_store, services
    global request_context, execution_context, CHANNEL
    stack = ExitStack()
    unittest.addModuleCleanup(stack.close)
    saved = {k: v for k, v in sys.modules.items() if _fixture_module(k)}

    def restore_modules():
        for key in list(sys.modules):
            if _fixture_module(key):
                del sys.modules[key]
        sys.modules.update(saved)

    stack.callback(restore_modules)
    for key in saved:
        del sys.modules[key]
    old_path = sys.path[:]
    stack.callback(setattr, sys, "path", old_path)
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    stack.callback(setattr, sys, "dont_write_bytecode", old_bytecode)
    (ROOT / "_validation").mkdir(exist_ok=True)
    TEMP = tempfile.TemporaryDirectory(
        prefix="arcmap-regression-", dir=ROOT / "_validation")
    stack.enter_context(TEMP)
    fixture = pathlib.Path(TEMP.name)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(("ZAGENT_", "ARCMAP_"))}
    environment.update({
        "ZAGENT_ARCMAP_ENGINE_ROOT": str(fixture / "engine"),
        "ZAGENT_ARCMAP_DATA_ROOT": str(fixture / "data"),
        "ZAGENT_ARCMAP_CONFIG_DIR": str(fixture / "config"),
        "ZAGENT_ARCMAP_IPC_ROOT": str(fixture / "ipc"),
        "ZAGENT_VISUAL_ROOT": str(fixture / "visual"),
        "ZAGENT_DEVICE_ID": "fixture-device",
        # Constructor-only, deliberately unused endpoint; no network call is made.
        "ZAGENT_WORKFLOW_RUNTIME_URL": "http://127.0.0.1:1",
    })
    stack.enter_context(mock.patch.dict(os.environ, environment, clear=True))
    sys.path[:0] = [str(ENGINE / "arcmap_bridge"), str(ENGINE)]
    frame = types.SimpleNamespace(name="Layers", extent=types.SimpleNamespace(
        XMin=0, YMin=0, XMax=1, YMax=1))
    document = types.SimpleNamespace(filePath="fixture.mxd", title="Fixture",
        activeDataFrame=frame, activeView="PAGE_LAYOUT",
        pageSize=types.SimpleNamespace(width=8.27, height=11.69))
    arcpy = types.ModuleType("arcpy")
    arcpy.mapping = types.SimpleNamespace(MapDocument=lambda p: document,
        ListDataFrames=lambda m: [frame], ListLayers=lambda *args: [],
        ListLayoutElements=lambda *args: [])
    sys.modules["arcpy"] = arcpy
    for name in ("core", "features"):
        package = types.ModuleType(name)
        package.__path__ = [str(ENGINE / "arcmap_bridge" / name)]
        sys.modules[name] = package
    # Execute unchanged config source with an isolated __file__: its runtime
    # locator is relative to __file__, not the ENGINE_ROOT environment variable.
    config = types.ModuleType("core.config")
    config.__file__ = str(fixture / "bridge/core/config.py")
    config.__package__ = "core"
    sys.modules["core.config"] = config
    source = ENGINE / "arcmap_bridge/core/config.py"
    exec(compile(source.read_bytes(), str(source), "exec"), config.__dict__)
    bridge_state = importlib.import_module("core.bridge_state")
    ipc = importlib.import_module("core.ipc")
    current_map = importlib.import_module("core.current_map")
    inspection = importlib.import_module("features.inspection")
    export_feature = importlib.import_module("features.export")
    ipc_client = importlib.import_module("mcp_server.ipc_client")
    visual_store = importlib.import_module("mcp_server.visual_store")
    services = importlib.import_module("mcp_server.services")
    request_context = importlib.import_module("mcp_server.request_context")
    execution_context = importlib.import_module("mcp_server.execution_context")
    CHANNEL = ipc_client._channel(ipc_client.IPC_ROOT, ipc_client.DATA_ROOT)
    assert pathlib.Path(config.RUNTIME_LOCATOR).is_relative_to(fixture)
    assert pathlib.Path(ipc.INBOX) == CHANNEL["inbox"]
    assert not services._UPSTREAM_READ_ONLY


def fixture_context(session="default", principal="fixture-principal",
                    workspace="fixture-workspace", resource="fixture-arcmap"):
    raw = {
        "context_version": 1, "principal_id": principal, "workspace_id": workspace,
        "device_id": "fixture-device", "operation_id": "op-" + session,
        "request_id": "req-" + session, "trace_id": "trace-" + session,
        "deadline": time.time() + 60, "effective_access": "write",
        "effective_resources": [{"kind": "arcmap", "resource_id": resource}],
    }
    # TrustedMetadata models an authenticated issuer at the in-process boundary.
    # No request_meta/verify/current/safety function is replaced or weakened.
    context = execution_context.verify(execution_context.TrustedMetadata(
        {"zagent.execution_context": raw}), "arcmap_ping", {})
    context["resource_id"] = resource
    return context


@contextmanager
def bound_context(context):
    authority = execution_context.CURRENT.set(context)
    correlation = request_context.correlation.set(context)
    try:
        yield
    finally:
        request_context.correlation.reset(correlation)
        execution_context.CURRENT.reset(authority)


def png():
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


class Regression(unittest.TestCase):
    def setUp(self):
        self.enterContext(bound_context(fixture_context()))
        ipc.ensure_dirs()
        for folder in (ipc.INBOX, ipc.OUTBOX):
            for path in pathlib.Path(folder).glob("*"):
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        document.filePath = "fixture.mxd"
        bridge_state.document_changed()

    def command(self, **kw):
        item = {"action": "inspect_current_map", "expires_at_epoch": time.time() + 10,
                "_expected_context": bridge_state.context()}
        item.update(kw)
        return item

    def test_expired_and_missing_deadline_never_execute(self):
        for command in ({}, self.command(expires_at_epoch=time.time() - 1)):
            self.assertEqual("COMMAND_EXPIRED", bridge_state.validate(command)["code"])

    def test_document_switch_and_reopen_fail_closed(self):
        command = self.command()
        bridge_state.document_changed()
        self.assertEqual("CURRENT_MXD_CHANGED", bridge_state.validate(command)["code"])
        command = self.command()
        document.filePath = "other.mxd"
        self.assertEqual("CURRENT_MXD_CHANGED", bridge_state.validate(command)["code"])

    def test_bridge_restart_fail_closed(self):
        command = self.command()
        command["_expected_context"]["bridge_instance_id"] = "previous"
        self.assertEqual("CURRENT_MXD_CHANGED", bridge_state.validate(command)["code"])

    def test_valid_context_accepts(self):
        self.assertIsNone(bridge_state.validate(self.command()))

    def test_startup_quarantines_2341_legacy_commands(self):
        for i in range(2341):
            pathlib.Path(ipc.INBOX, str(i) + ".json").write_text('{"action":"set_scale"}')
        self.assertEqual(2341, ipc.quarantine_stale())
        self.assertEqual([], ipc.list_commands())

    def test_runner_rejects_expired_without_dispatch(self):
        fake = types.ModuleType("core.dispatcher")
        fake.dispatch = mock.Mock(return_value={"ok": True})
        with mock.patch.dict(sys.modules, {"core.dispatcher": fake}):
            sys.modules.pop("core.runner", None)
            runner = importlib.import_module("core.runner")
            pathlib.Path(ipc.INBOX, "expired.json").write_text(json.dumps(
                self.command(request_id="expired", expires_at_epoch=0)))
            self.assertTrue(runner.process_next())
            fake.dispatch.assert_not_called()
            result = json.loads(pathlib.Path(ipc.OUTBOX, "expired.json").read_text(encoding="utf-8"))
            self.assertEqual("COMMAND_EXPIRED", result["code"])

    def test_timeout_removes_queued_work(self):
        with self.assertRaisesRegex(ipc_client.ArcMapBridgeError, "not executed"):
            ipc_client.send_command("ping", timeout=.1)
        self.assertEqual([], list(CHANNEL["inbox"].glob("*.json")))

    def test_offline_write_is_not_queued(self):
        with self.assertRaisesRegex(ipc_client.ArcMapBridgeError, "BRIDGE_OFFLINE"):
            ipc_client.send_command("set_scale", scale=100)
        self.assertEqual([], list(CHANNEL["inbox"].glob("*.json")))

    def test_bad_scale_returns_partial_state(self):
        class BadScale:
            name = "Layers"
            extent = frame.extent
            @property
            def scale(self):
                raise RuntimeError("DataFrameObject: Error in getting scale")
        with mock.patch.object(arcpy.mapping, "ListDataFrames", return_value=[BadScale()]):
            result = inspection.inspect_current_map({"correlation": {
                "session_id": "S", "request_id": "R", "trace_id": "T"}})
        self.assertTrue(result["ok"])
        self.assertTrue(result["partial"])
        self.assertIsNone(result["frames"][0]["scale"])
        self.assertEqual("R", result["request_id"])

    def test_default_dataframe_is_active(self):
        self.assertIs(frame, current_map.get_dataframe(document))

    def test_mutation_does_not_switch_after_observation(self):
        svc = services.AgentServices()
        observed = {"bridge_instance_id": "A", "document_id": "old"}
        with mock.patch.dict(services.AGENT, {"allow_live_write": True}), \
             mock.patch.object(services, "send_command", return_value={
                 "ok": True, "context": {"document_id": "new"}}) as send:
            result = svc.call("set_scale", "live_write", _expected_context=observed)
        self.assertEqual("CURRENT_MXD_CHANGED", result["code"])
        self.assertEqual(1, send.call_count)
        self.assertEqual("ping", send.call_args.args[0])

    def test_visual_session_provenance_and_recovery(self):
        image = pathlib.Path(TEMP.name, "fixture.png")
        image.write_bytes(png())
        ids = {}
        captured = {}
        for session in ("one", "two"):
            with bound_context(fixture_context(session)) as _:
                # latest() orders capture timestamps, not publication calls.
                # Real clocks may tie; give this ordering fixture distinct instants.
                stamp = visual_store._dt.datetime(2026, 1, 1, 0, 0, 0,
                    100000 if session == "one" else 200000)
                clock = types.SimpleNamespace(
                    datetime=types.SimpleNamespace(utcnow=lambda: stamp),
                    timezone=visual_store._dt.timezone)
                with mock.patch.object(visual_store, "_dt", clock):
                    item = visual_store.publish(str(image))
                ids[session] = item["id"]
                captured[session] = item["capturedAt"]
                self.assertEqual("req-" + session, item["provenance"]["requestId"])
                self.assertEqual("fixture-principal", item["provenance"]["principalId"])
                self.assertEqual("fixture-workspace", item["provenance"]["workspaceId"])
                with self.assertRaisesRegex(ValueError, "MISMATCH"):
                    visual_store.publish(str(image), session_id="foreign")
        self.assertLess(captured["one"], captured["two"])
        # Same principal/workspace owns artifacts across sessions and resources.
        with bound_context(fixture_context("one", resource="another-arcmap")):
            importlib.reload(visual_store)
            self.assertEqual(ids["two"], visual_store.latest(source="arcmap")["id"])
            self.assertEqual(set(ids.values()), {x["id"] for x in visual_store.list_artifacts()})
            owner_root = pathlib.Path(visual_store.visual_root())
            owner_items = visual_store.list_artifacts()
        # Neither a different principal nor a different workspace can list owner
        # artifacts, even if foreign manifests are copied into its manifest dir.
        for changes in ({"principal": "foreign"}, {"workspace": "foreign"}):
            with self.subTest(owner=changes), bound_context(fixture_context("foreign", **changes)):
                self.assertIsNone(visual_store.latest(source="arcmap"))
                self.assertEqual([], visual_store.list_artifacts(_all_sessions=True))
                foreign_root = pathlib.Path(visual_store.visual_root())
                self.assertNotEqual(owner_root, foreign_root)
                for item in owner_items:
                    (foreign_root / "manifests" / (item["id"] + ".json")).write_text(
                        json.dumps(item), encoding="utf-8")
                self.assertEqual([], visual_store.list_artifacts(_all_sessions=True))
                foreign = visual_store.publish(str(image))
                self.assertEqual([foreign["id"]], [x["id"] for x in visual_store.list_artifacts()])
        with bound_context(fixture_context("one")):
            self.assertEqual({"removed": 1, "retained": 1}, visual_store.prune(max_artifacts=1))
            self.assertEqual([ids["two"]], [x["id"] for x in visual_store.list_artifacts()])
        with bound_context(fixture_context("two")):
            self.assertEqual(ids["two"], visual_store.latest(source="arcmap")["id"])
        for changes in ({"principal": "foreign"}, {"workspace": "foreign"}):
            with bound_context(fixture_context("foreign", **changes)):
                self.assertEqual(1, len(visual_store.list_artifacts()))

    def test_export_validates_png_pdf_and_rejects_partial_files(self):
        path = pathlib.Path(TEMP.name, "out.png")
        path.write_bytes(png())
        self.assertEqual([1, 1], export_feature.verify_output(str(path), "png")["dimensions"])
        path.write_bytes(b"%PDF-1.7\nfixture\n%%EOF\n")
        self.assertGreater(export_feature.verify_output(str(path), "pdf")["bytes"], 16)
        path.write_bytes(b"%PDF-1.7\ntruncated-file-data")
        with self.assertRaisesRegex(RuntimeError, "incomplete PDF"):
            export_feature.verify_output(str(path), "pdf")

    def test_stage3_appref_is_primary_arcobjects_application_path(self):
        source = (ENGINE / "stage3/bridge.py").read_text(encoding="utf-8")
        appref_win32 = source.find('Dispatch("esriFramework.AppRef")')
        appref_comtypes = source.find('CreateObject("esriFramework.AppRef", dynamic=True)')
        legacy_rot = source.find('GetActiveObject("esriArcMap.Application")')
        self.assertGreaterEqual(appref_win32, 0)
        self.assertGreaterEqual(appref_comtypes, 0)
        self.assertTrue(legacy_rot < 0 or appref_win32 < legacy_rot)
        self.assertIn("win32com:esriFramework.AppRef", source)

    def test_owner_heartbeat_publish_is_atomic(self):
        source = (ENGINE / "arcmap_bridge/live_bridge.py").read_text(encoding="utf-8")
        self.assertIn("MoveFileExW", source)
        self.assertIn("_replace_file_atomic(temp, _OWNER_FILE)", source)
        self.assertNotIn("os.remove(_OWNER_FILE)", source)

    def test_owner_status_retries_transient_read_lock(self):
        owner = {"running": True, "updated_at_epoch": time.time(), "context": {
            "bridge_instance_id": "fixture", "document_id": "fixture"}}
        with mock.patch.object(ipc_client, "_read_json", side_effect=[None, None, owner]) as read_json, \
             mock.patch.object(ipc_client.time, "sleep", return_value=None):
            result = ipc_client._read_owner_json(CHANNEL["owner"], attempts=3, delay=0)
        self.assertEqual(owner, result)
        self.assertEqual(3, read_json.call_count)
        self.assertEqual([mock.call(CHANNEL["owner"])] * 3, read_json.call_args_list)

    def test_stale_owner_fails_closed_and_write_is_not_queued(self):
        owner = {"running": True, "updated_at_epoch": time.time() - 999, "context": {
            "bridge_instance_id": "stale", "document_id": "stale"}}
        with mock.patch.object(ipc_client, "_read_owner_json", return_value=owner):
            status = ipc_client.owner_status()
            self.assertFalse(status["healthy"])
            with self.assertRaisesRegex(ipc_client.ArcMapBridgeError, "BRIDGE_OFFLINE"):
                ipc_client.send_command("set_scale", scale=100)
        self.assertEqual([], list(CHANNEL["inbox"].glob("*.json")))

    def test_unknown_outcome_timeout_is_never_auto_replayed(self):
        with mock.patch.object(ipc_client, "_write_atomic", return_value=None) as write, \
             mock.patch.object(ipc_client, "_read_json", return_value=None), \
             mock.patch.object(ipc_client.time, "sleep", return_value=None), \
             mock.patch.object(ipc_client.time, "monotonic", side_effect=[0.0, 1.0]):
            with self.assertRaisesRegex(ipc_client.ArcMapBridgeError,
                    "execution outcome unknown.*No automatic replay"):
                ipc_client.send_command("ping", timeout=0.1)
        self.assertEqual(1, write.call_count)
        self.assertEqual("ping", write.call_args.args[1]["action"])
        self.assertEqual([], list(CHANNEL["inbox"].glob("*.json")))

    def test_live_bridge_keeps_exclusive_named_mutex_guard(self):
        source = (ENGINE / "arcmap_bridge/live_bridge.py").read_text(encoding="utf-8")
        for marker in ("CreateMutexW", "_ERROR_ALREADY_EXISTS",
                       "Dual bridge ownership is not allowed", "_release_owner_mutex()"):
            self.assertIn(marker, source)

    def test_arcmap_lock_is_global_and_shared_by_live_tools(self):
        services_source = (ENGINE / "mcp_server/services.py").read_text(encoding="utf-8")
        export_source = (ENGINE / "mcp_server/tools/export.py").read_text(encoding="utf-8")
        window_source = (ENGINE / "mcp_server/tools/window_capture.py").read_text(encoding="utf-8")
        self.assertEqual(1, services_source.count("_ARCMAP_LOCK = threading.RLock()"))
        self.assertIn("with _ARCMAP_LOCK:", services_source)
        for source in (export_source, window_source):
            self.assertIn("from ..services import _ARCMAP_LOCK", source)
            self.assertIn("with _ARCMAP_LOCK:", source)

    def test_two_session_mutations_are_serialized_by_global_arcmap_lock(self):
        # Distinct service instances must still share the single ArcMap lock.
        context = {"pid": 1, "document_path": "fixture.mxd",
                   "document_id": "doc", "bridge_instance_id": "bridge"}
        state_lock = threading.Lock()
        active_mutations, max_active = [0], [0]
        seen_sessions, results, errors = [], [], []
        start = threading.Barrier(2)

        def fake_send(action, **payload):
            if action in ("ping", "inspect_current_map"):
                return {"ok": True, "context": dict(context)}
            with state_lock:
                active_mutations[0] += 1
                max_active[0] = max(max_active[0], active_mutations[0])
                seen_sessions.append(request_context.current()["request_id"])
            try:
                time.sleep(0.05)
                return {"ok": True, "context": dict(context)}
            finally:
                with state_lock:
                    active_mutations[0] -= 1

        def worker(session, scale):
            try:
                with bound_context(fixture_context(session)):
                    start.wait(timeout=5)
                    results.append(services.AgentServices().call("set_scale", "live_write", scale=scale))
            except Exception as exc:
                errors.append(repr(exc))

        with mock.patch.dict(services.AGENT, {"allow_live_write": True}), \
             mock.patch.object(services, "send_command", side_effect=fake_send):
            threads = [threading.Thread(target=worker, args=("chat-one", 1000)),
                       threading.Thread(target=worker, args=("chat-two", 2000))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([], errors)
        self.assertEqual(2, len(results))
        self.assertTrue(all(item.get("ok") for item in results))
        self.assertEqual(1, max_active[0])
        self.assertEqual({"req-chat-one", "req-chat-two"}, set(seen_sessions))
        # Expiry must be rechecked after waiting for the same global lock.
        waiting = threading.Event()
        expired_errors = []
        expiring = fixture_context("queued-expiry")
        expiring["expires_at"] = time.time() + .1

        def expired_worker():
            try:
                with bound_context(expiring):
                    waiting.set()
                    services.AgentServices().call("set_scale", "live_write", scale=3000)
            except Exception as exc:
                expired_errors.append(str(exc))

        with mock.patch.object(services, "send_command") as send:
            with services._ARCMAP_LOCK:
                thread = threading.Thread(target=expired_worker)
                thread.start()
                self.assertTrue(waiting.wait(5))
                time.sleep(max(0, expiring["expires_at"] - time.time()) + .03)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(["CONTEXT_EXPIRED_WHILE_QUEUED"], expired_errors)
            send.assert_not_called()

    def test_timing_claim_epoch_is_preserved(self):
        source = (ENGINE / "arcmap_bridge/core/runner.py").read_text(encoding="utf-8")
        for marker in ('claim_epoch = time.time()', 'timing = command.setdefault("timing", {})',
                       'timing["addin_claim_epoch"] = claim_epoch'):
            self.assertIn(marker, source)
        self.assertLess(source.find('claim_epoch = time.time()'),
                        source.find('timing["addin_claim_epoch"] = claim_epoch'))

    def test_full_timing_instrumentation_markers_exist(self):
        groups = {
            "mcp_server/request_context.py": ("mcp_receive_epoch", "mcp_tool_name"),
            "mcp_server/ipc_client.py": ("mcp_send_enter_epoch", "owner_checked_epoch",
                "owner_heartbeat_epoch", "owner_heartbeat_age_ms", "ipc_enqueue_epoch",
                "mcp_result_read_epoch", "mcp_total_ms"),
            "arcmap_bridge/core/runner.py": ("addin_claim_epoch", "addin_command_read_epoch",
                "current_mxd_validate_start_epoch", "current_mxd_validate_end_epoch",
                "dispatch_start_epoch", "dispatch_end_epoch", "result_write_epoch"),
            "arcmap_bridge/live_bridge.py": ("timer_started_epoch", "timer_callback_epoch",
                "timer_interval_ms", "heartbeat_sequence"),
        }
        for path, markers in groups.items():
            source = (ENGINE / path).read_text(encoding="utf-8")
            for marker in markers:
                self.assertIn(marker, source)

    def test_stage3_pagelayout_uses_typed_arcobjects_interfaces(self):
        source = (ENGINE / "stage3/bridge.py").read_text(encoding="utf-8")
        for marker in ("def _typed_arcobjects_modules():", 'GetInstallInfo()',
                '"esriFramework.olb"', '"esriArcMapUI.olb"', '"esriCarto.olb"',
                'interface=framework.IApplication', 'QueryInterface(arcmapui.IMxDocument)',
                'QueryInterface(carto.IPageLayout)', 'QueryInterface(carto.IPage)',
                '"comtypes:esriFramework.AppRef+IApplication+IMxDocument+IPageLayout"',
                '"PutCustomSize"'):
            self.assertIn(marker, source)
        self.assertNotIn("def _query_interface_dispatch(", source)
        self.assertFalse((ENGINE / "vendor27/comtypes/gen").exists())

    def test_export_timeout_budget_supports_long_running_renders(self):
        export_source = (ENGINE / "mcp_server/tools/export.py").read_text(encoding="utf-8")
        export_qa_source = (ENGINE / "mcp_server/tools/export_qa.py").read_text(encoding="utf-8")
        core_options = (ROOT / "src/Zagent.Core/Agents/ArcMap/ArcMapIntegrationModels.cs").read_text(encoding="utf-8")
        manager_host = (ROOT / "src/Zagent.Core/Manager/ManagerCoreHost.cs").read_text(encoding="utf-8")
        static_config = json.loads((ENGINE / "config/agent_config.json").read_text(encoding="utf-8"))
        self.assertIn("int CommandTimeoutSeconds = 15", core_options)
        self.assertIn("CommandTimeoutSeconds: 15", manager_host)
        self.assertNotIn("CommandTimeoutSeconds: 2", manager_host)
        self.assertEqual(15, int(static_config["command_timeout_seconds"]))
        self.assertGreaterEqual(export_source.count("timeout=60"), 4)
        self.assertGreaterEqual(export_qa_source.count("timeout=60"), 2)
        self.assertIn("timeout=120", export_qa_source)

    def test_real_arcmap_window_capture_is_registered_and_guarded(self):
        backend = (ENGINE / "mcp_server/window_capture.py").read_text(encoding="utf-8")
        wrapper = (ENGINE / "mcp_server/tools/window_capture.py").read_text(encoding="utf-8")
        for marker in ("PrintWindow", "BitBltFallback", "ARCMAP_PROCESS_MISMATCH",
                       "ARCMAP_WINDOW_MINIMIZED", "ARCMAP_WINDOW_CAPTURE_BLANK", "arcmap.exe"):
            self.assertIn(marker.lower(), backend.lower())
        self.assertIn("confirm_current_arcmap_window", wrapper)
        self.assertIn('kind="arcmap_application_window"', wrapper)
        # Import actual source registration and enumerate the actual SDK registry;
        # never manufacture or require an ignored installed runtime snapshot.
        server = importlib.import_module("mcp_server.server")
        names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
        self.assertIn("arcmap_window_capture", names)
        self.assertEqual(len(names), server.MCP_TOOL_COUNT)
        self.assertIn(importlib.import_module("mcp_server.tools.window_capture"), server.TOOL_MODULES)
        registered = server.mcp._tool_manager._tools["arcmap_window_capture"].fn
        with mock.patch.object(server.services, "call") as call, \
             mock.patch("mcp_server.tools.window_capture.capture_arcmap_window") as capture:
            self.assertEqual("WINDOW_CAPTURE_CONFIRMATION_REQUIRED", registered()["code"])
            self.assertEqual("SESSION_IDENTITY_MISMATCH", registered(
                confirm_current_arcmap_window=True, session_id="foreign")["code"])
            call.assert_not_called()
            capture.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)

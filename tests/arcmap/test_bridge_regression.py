"""Regression tests for ArcMap bridge protocol; never opens or changes a real MXD."""
import os
import sys
import tempfile
import pathlib
import types
import unittest
import time
import json
import struct
import zlib
import importlib
import threading
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / "agents/arcmap/engine"
TEMP = tempfile.TemporaryDirectory(prefix="arcmap-regression-", dir=ROOT / "_validation")
os.environ["ZAGENT_ARCMAP_DATA_ROOT"] = TEMP.name
os.environ["ZAGENT_ARCMAP_CONFIG_DIR"] = str(pathlib.Path(TEMP.name) / "config")
os.environ["ZAGENT_ARCMAP_IPC_ROOT"] = str(pathlib.Path(TEMP.name) / "ipc")
os.environ["ZAGENT_ARCMAP_ENGINE_ROOT"] = str(ENGINE)
os.environ["ZAGENT_VISUAL_ROOT"] = str(pathlib.Path(TEMP.name) / "visual")
sys.path[:0] = [str(ENGINE / "arcmap_bridge"), str(ENGINE)]
frame = types.SimpleNamespace(name="Layers", extent=types.SimpleNamespace(XMin=0,YMin=0,XMax=1,YMax=1))
document = types.SimpleNamespace(filePath="fixture.mxd", title="Fixture", activeDataFrame=frame,
    activeView="PAGE_LAYOUT", pageSize=types.SimpleNamespace(width=8.27,height=11.69))
arcpy = types.ModuleType("arcpy")
arcpy.mapping = types.SimpleNamespace(MapDocument=lambda p: document,
    ListDataFrames=lambda m: [frame], ListLayers=lambda *args: [], ListLayoutElements=lambda *args: [])
sys.modules["arcpy"] = arcpy
from core import bridge_state, ipc
from core import current_map
from features import inspection
from features import export as export_feature
from mcp_server import ipc_client, visual_store, services, request_context

def png():
    def chunk(kind, data):
        return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(b"\x00\xff\x00\x00"))+chunk(b"IEND",b"")

class Regression(unittest.TestCase):
    def setUp(self):
        ipc.ensure_dirs()
        for folder in (ipc.INBOX, ipc.OUTBOX):
            for p in pathlib.Path(folder).glob("*"):
                p.unlink()
        document.filePath="fixture.mxd"
        bridge_state.document_changed()

    def command(self, **kw):
        item = {"action":"inspect_current_map","expires_at_epoch":time.time()+10,
                "_expected_context":bridge_state.context()}
        item.update(kw)
        return item

    def test_expired_and_missing_deadline_never_execute(self):
        for command in ({},self.command(expires_at_epoch=time.time()-1)):
            self.assertEqual("COMMAND_EXPIRED", bridge_state.validate(command)["code"])

    def test_document_switch_and_reopen_fail_closed(self):
        command=self.command()
        bridge_state.document_changed()
        self.assertEqual("CURRENT_MXD_CHANGED",bridge_state.validate(command)["code"])
        command=self.command()
        document.filePath="other.mxd"
        self.assertEqual("CURRENT_MXD_CHANGED",bridge_state.validate(command)["code"])

    def test_bridge_restart_fail_closed(self):
        command=self.command()
        command["_expected_context"]["bridge_instance_id"]="previous"
        self.assertEqual("CURRENT_MXD_CHANGED",bridge_state.validate(command)["code"])

    def test_valid_context_accepts(self):
        self.assertIsNone(bridge_state.validate(self.command()))

    def test_startup_quarantines_2341_legacy_commands(self):
        for i in range(2341):
            pathlib.Path(ipc.INBOX, str(i)+".json").write_text('{"action":"set_scale"}')
        self.assertEqual(2341,ipc.quarantine_stale())
        self.assertEqual([],ipc.list_commands())

    def test_runner_rejects_expired_without_dispatch(self):
        fake=types.ModuleType("core.dispatcher")
        fake.dispatch=mock.Mock(return_value={"ok":True})
        with mock.patch.dict(sys.modules,{"core.dispatcher":fake}):
            sys.modules.pop("core.runner",None)
            runner=importlib.import_module("core.runner")
            pathlib.Path(ipc.INBOX,"expired.json").write_text(json.dumps(self.command(request_id="expired",expires_at_epoch=0)))
            self.assertTrue(runner.process_next())
            fake.dispatch.assert_not_called()
            result=json.loads(pathlib.Path(ipc.OUTBOX,"expired.json").read_text())
            self.assertEqual("COMMAND_EXPIRED",result["code"])

    def test_timeout_removes_queued_work(self):
        with self.assertRaisesRegex(ipc_client.ArcMapBridgeError,"not executed"):
            ipc_client.send_command("ping",timeout=.1)
        self.assertEqual([],list(ipc_client.INBOX.glob("*.json")))

    def test_offline_write_is_not_queued(self):
        with self.assertRaisesRegex(ipc_client.ArcMapBridgeError,"BRIDGE_OFFLINE"):
            ipc_client.send_command("set_scale",scale=100)
        self.assertEqual([],list(ipc_client.INBOX.glob("*.json")))

    def test_bad_scale_returns_partial_state(self):
        class BadScale:
            name="Layers"
            extent=frame.extent
            @property
            def scale(self): raise RuntimeError("DataFrameObject: Error in getting scale")
        bad=BadScale()
        with mock.patch.object(arcpy.mapping,"ListDataFrames",return_value=[bad]):
            result=inspection.inspect_current_map({"correlation":{"session_id":"S","request_id":"R","trace_id":"T"}})
        self.assertTrue(result["ok"])
        self.assertTrue(result["partial"])
        self.assertIsNone(result["frames"][0]["scale"])
        self.assertEqual("R",result["request_id"])

    def test_default_dataframe_is_active(self):
        self.assertIs(frame,current_map.get_dataframe(document))

    def test_mutation_does_not_switch_after_observation(self):
        svc=services.AgentServices()
        observed={"bridge_instance_id":"A","document_id":"old"}
        with mock.patch.object(svc.safety,"guard",return_value=None), mock.patch.object(services,"send_command",return_value={"ok":True,"context":{"document_id":"new"}}) as send:
            result=svc.call("set_scale","live_write",_expected_context=observed)
        self.assertEqual("CURRENT_MXD_CHANGED",result["code"])
        self.assertEqual(1,send.call_count)

    def test_visual_session_provenance_and_recovery(self):
        image=pathlib.Path(TEMP.name,"fixture.png")
        image.write_bytes(png())
        ids={}
        for session in ("one","two"):
            token=request_context.correlation.set({"session_id":session,"request_id":"req-"+session,"trace_id":"trace-"+session,"device_id":"fixture"})
            try:
                item=visual_store.publish(str(image))
                ids[session]=item["id"]
                self.assertEqual("req-"+session,item["provenance"]["requestId"])
                with self.assertRaisesRegex(ValueError,"MISMATCH"):
                    visual_store.publish(str(image),session_id="foreign")
            finally: request_context.correlation.reset(token)
        token=request_context.correlation.set({"session_id":"one"})
        try:
            importlib.reload(visual_store)
            self.assertEqual(ids["one"],visual_store.latest(source="arcmap")["id"])
            self.assertTrue(all(x["provenance"]["sessionId"]=="one" for x in visual_store.list_artifacts()))
            visual_store.prune(max_artifacts=1)
        finally: request_context.correlation.reset(token)
        token=request_context.correlation.set({"session_id":"two"})
        try: self.assertEqual(ids["two"],visual_store.latest(source="arcmap")["id"])
        finally: request_context.correlation.reset(token)

    def test_export_validates_png_pdf_and_rejects_partial_files(self):
        path=pathlib.Path(TEMP.name,"out.png")
        path.write_bytes(png())
        self.assertEqual([1,1],export_feature.verify_output(str(path),"png")["dimensions"])
        path.write_bytes(b"%PDF-1.7\nfixture\n%%EOF\n")
        self.assertGreater(export_feature.verify_output(str(path),"pdf")["bytes"],16)
        path.write_bytes(b"%PDF-1.7\ntruncated-file-data")
        with self.assertRaisesRegex(RuntimeError,"incomplete PDF"):
            export_feature.verify_output(str(path),"pdf")


    def test_stage3_appref_is_primary_arcobjects_application_path(self):
        source = (ENGINE / "stage3" / "bridge.py").read_text(encoding="utf-8")
        appref_win32 = source.find('Dispatch("esriFramework.AppRef")')
        appref_comtypes = source.find('CreateObject("esriFramework.AppRef", dynamic=True)')
        legacy_rot = source.find('GetActiveObject("esriArcMap.Application")')
        self.assertGreaterEqual(appref_win32, 0)
        self.assertGreaterEqual(appref_comtypes, 0)
        self.assertTrue(legacy_rot < 0 or appref_win32 < legacy_rot)
        self.assertIn("win32com:esriFramework.AppRef", source)
    def test_owner_heartbeat_publish_is_atomic(self):
        source = (ENGINE / "arcmap_bridge" / "live_bridge.py").read_text(encoding="utf-8")
        self.assertIn("MoveFileExW", source)
        self.assertIn("_replace_file_atomic(temp, _OWNER_FILE)", source)
        self.assertNotIn("os.remove(_OWNER_FILE)", source)

    def test_owner_status_retries_transient_read_lock(self):
        owner = {
            "running": True,
            "updated_at_epoch": time.time(),
            "context": {"bridge_instance_id": "fixture", "document_id": "fixture"},
        }
        with mock.patch.object(ipc_client, "_read_json", side_effect=[None, None, owner]) as read_json, \
             mock.patch.object(ipc_client.time, "sleep", return_value=None):
            result = ipc_client._read_owner_json(attempts=3, delay=0)
        self.assertEqual(owner, result)
        self.assertEqual(3, read_json.call_count)

    def test_stale_owner_fails_closed_and_write_is_not_queued(self):
        owner = {
            "running": True,
            "updated_at_epoch": time.time() - 999,
            "context": {"bridge_instance_id": "stale", "document_id": "stale"},
        }
        with mock.patch.object(ipc_client, "_read_owner_json", return_value=owner):
            status = ipc_client.owner_status()
            self.assertFalse(status["healthy"])
            with self.assertRaisesRegex(ipc_client.ArcMapBridgeError, "BRIDGE_OFFLINE"):
                ipc_client.send_command("set_scale", scale=100)
        self.assertEqual([], list(ipc_client.INBOX.glob("*.json")))

    def test_unknown_outcome_timeout_is_never_auto_replayed(self):
        with mock.patch.object(ipc_client, "_write_atomic", return_value=None), \
             mock.patch.object(ipc_client, "_read_json", return_value=None), \
             mock.patch.object(ipc_client.time, "sleep", return_value=None), \
             mock.patch.object(ipc_client.time, "monotonic", side_effect=[0.0, 1.0]):
            with self.assertRaisesRegex(
                ipc_client.ArcMapBridgeError,
                "execution outcome unknown.*No automatic replay",
            ):
                ipc_client.send_command("ping", timeout=0.1)
        self.assertEqual([], list(ipc_client.INBOX.glob("*.json")))

    def test_live_bridge_keeps_exclusive_named_mutex_guard(self):
        source = (ENGINE / "arcmap_bridge" / "live_bridge.py").read_text(encoding="utf-8")
        self.assertIn("CreateMutexW", source)
        self.assertIn("_ERROR_ALREADY_EXISTS", source)
        self.assertIn("Dual bridge ownership is not allowed", source)
        self.assertIn("_release_owner_mutex()", source)

    def test_arcmap_lock_is_global_and_shared_by_live_tools(self):
        services_source = (ENGINE / "mcp_server" / "services.py").read_text(encoding="utf-8")
        export_source = (ENGINE / "mcp_server" / "tools" / "export.py").read_text(encoding="utf-8")
        window_source = (ENGINE / "mcp_server" / "tools" / "window_capture.py").read_text(encoding="utf-8")
        self.assertEqual(1, services_source.count("_ARCMAP_LOCK = threading.RLock()"))
        self.assertIn("with _ARCMAP_LOCK:", services_source)
        self.assertIn("from ..services import _ARCMAP_LOCK", export_source)
        self.assertIn("with _ARCMAP_LOCK:", export_source)
        self.assertIn("from ..services import _ARCMAP_LOCK", window_source)
        self.assertIn("with _ARCMAP_LOCK:", window_source)

    def test_two_session_mutations_are_serialized_by_global_arcmap_lock(self):
        svc = services.AgentServices()
        context = {
            "pid": 1,
            "document_path": "fixture.mxd",
            "document_id": "doc",
            "bridge_instance_id": "bridge",
        }
        state_lock = threading.Lock()
        active_mutations = [0]
        max_active = [0]
        seen_sessions = []
        results = []

        def fake_send(action, **payload):
            if action == "ping":
                return {"ok": True, "context": dict(context)}
            if action == "inspect_current_map":
                return {"ok": True, "context": dict(context)}
            with state_lock:
                active_mutations[0] += 1
                max_active[0] = max(max_active[0], active_mutations[0])
                seen_sessions.append(request_context.current().get("session_id"))
            time.sleep(0.05)
            with state_lock:
                active_mutations[0] -= 1
            return {"ok": True, "context": dict(context)}

        def worker(session, scale):
            token = request_context.correlation.set({
                "session_id": session,
                "request_id": "req-" + session,
                "trace_id": "trace-" + session,
                "device_id": "fixture",
            })
            try:
                results.append(svc.call("set_scale", "live_write", scale=scale))
            finally:
                request_context.correlation.reset(token)

        with mock.patch.object(svc.safety, "guard", return_value=None), \
             mock.patch.object(services, "send_command", side_effect=fake_send):
            threads = [
                threading.Thread(target=worker, args=("chat-one", 1000)),
                threading.Thread(target=worker, args=("chat-two", 2000)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(2, len(results))
        self.assertTrue(all(item.get("ok") for item in results))
        self.assertEqual(1, max_active[0])
        self.assertEqual({"chat-one", "chat-two"}, set(seen_sessions))

    def test_timing_claim_epoch_is_preserved(self):
        source = (ENGINE / "arcmap_bridge" / "core" / "runner.py").read_text(encoding="utf-8")
        self.assertIn('claim_epoch = time.time()', source)
        self.assertIn('timing = command.setdefault("timing", {})', source)
        self.assertIn('timing["addin_claim_epoch"] = claim_epoch', source)
        self.assertLess(
            source.find('claim_epoch = time.time()'),
            source.find('timing["addin_claim_epoch"] = claim_epoch')
        )

    def test_full_timing_instrumentation_markers_exist(self):
        request_context_source = (ENGINE / "mcp_server" / "request_context.py").read_text(encoding="utf-8")
        ipc_source = (ENGINE / "mcp_server" / "ipc_client.py").read_text(encoding="utf-8")
        runner_source = (ENGINE / "arcmap_bridge" / "core" / "runner.py").read_text(encoding="utf-8")
        live_source = (ENGINE / "arcmap_bridge" / "live_bridge.py").read_text(encoding="utf-8")
        for marker in ("mcp_receive_epoch", "mcp_tool_name"):
            self.assertIn(marker, request_context_source)
        for marker in (
            "mcp_send_enter_epoch", "owner_checked_epoch", "owner_heartbeat_epoch",
            "owner_heartbeat_age_ms", "ipc_enqueue_epoch", "mcp_result_read_epoch",
            "mcp_total_ms"
        ):
            self.assertIn(marker, ipc_source)
        for marker in (
            "addin_claim_epoch", "addin_command_read_epoch",
            "current_mxd_validate_start_epoch", "current_mxd_validate_end_epoch",
            "dispatch_start_epoch", "dispatch_end_epoch", "result_write_epoch"
        ):
            self.assertIn(marker, runner_source)
        for marker in (
            "timer_started_epoch", "timer_callback_epoch",
            "timer_interval_ms", "heartbeat_sequence"
        ):
            self.assertIn(marker, live_source)

    def test_stage3_pagelayout_uses_typed_arcobjects_interfaces(self):
        source = (ENGINE / "stage3" / "bridge.py").read_text(encoding="utf-8")
        for marker in (
            "def _typed_arcobjects_modules():",
            'GetInstallInfo()',
            '"esriFramework.olb"',
            '"esriArcMapUI.olb"',
            '"esriCarto.olb"',
            'interface=framework.IApplication',
            'QueryInterface(arcmapui.IMxDocument)',
            'QueryInterface(carto.IPageLayout)',
            'QueryInterface(carto.IPage)',
            '"comtypes:esriFramework.AppRef+IApplication+IMxDocument+IPageLayout"',
            '"PutCustomSize"',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("def _query_interface_dispatch(", source)
        self.assertFalse((ENGINE / "vendor27" / "comtypes" / "gen").exists())

    def test_export_timeout_budget_supports_long_running_renders(self):
        export_source = (ENGINE / "mcp_server" / "tools" / "export.py").read_text(encoding="utf-8")
        export_qa_source = (ENGINE / "mcp_server" / "tools" / "export_qa.py").read_text(encoding="utf-8")
        core_options = (ROOT / "src" / "Zagent.Core" / "Agents" / "ArcMap" / "ArcMapIntegrationModels.cs").read_text(encoding="utf-8")
        manager_host = (ROOT / "src" / "Zagent.Core" / "Manager" / "ManagerCoreHost.cs").read_text(encoding="utf-8")
        static_config = json.loads((ENGINE / "config" / "agent_config.json").read_text(encoding="utf-8"))
        self.assertIn("int CommandTimeoutSeconds = 15", core_options)
        self.assertIn("CommandTimeoutSeconds: 15", manager_host)
        self.assertNotIn("CommandTimeoutSeconds: 2", manager_host)
        self.assertEqual(15, int(static_config["command_timeout_seconds"]))
        self.assertGreaterEqual(export_source.count("timeout=60"), 4)
        self.assertGreaterEqual(export_qa_source.count("timeout=60"), 2)
        self.assertIn("timeout=120", export_qa_source)

    def test_real_arcmap_window_capture_is_registered_and_guarded(self):
        backend = (ENGINE / "mcp_server" / "window_capture.py").read_text(encoding="utf-8")
        wrapper = (ENGINE / "mcp_server" / "tools" / "window_capture.py").read_text(encoding="utf-8")
        server = (ENGINE / "mcp_server" / "server.py").read_text(encoding="utf-8")
        snapshot = json.loads((ROOT / "agents" / "arcmap" / "runtime-tools.snapshot.json").read_text(encoding="utf-8"))
        for marker in (
            "PrintWindow",
            "BitBltFallback",
            "ARCMAP_PROCESS_MISMATCH",
            "ARCMAP_WINDOW_MINIMIZED",
            "ARCMAP_WINDOW_CAPTURE_BLANK",
            "arcmap.exe",
        ):
            self.assertIn(marker.lower(), backend.lower())
        self.assertIn("confirm_current_arcmap_window", wrapper)
        self.assertIn('kind="arcmap_application_window"', wrapper)
        self.assertIn("window_capture", server)
        self.assertEqual(124, int(snapshot["count"]))
        self.assertIn("arcmap_window_capture", snapshot["tools"])

if __name__ == "__main__":
    try: unittest.main(verbosity=2)
    finally: TEMP.cleanup()

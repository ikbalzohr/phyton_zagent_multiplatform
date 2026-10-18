import unittest

from orchestrator.context import collect_live_context
from orchestrator.context.collector import _fingerprint

class FakeOfflineServices:
    def __init__(self):
        self.calls = []
        self.payloads = []
    def call(self, action, kind="read", **payload):
        self.calls.append(action)
        self.payloads.append(payload)
        return {"ok": False, "error": "BRIDGE_TIMEOUT"}

class FakeStaleOwnerServices(FakeOfflineServices):
    def bridge_owner_status(self):
        return {
            "running": True,
            "healthy": False,
            "heartbeat_age_seconds": 3600,
            "engine_root": r"D:\\stale\\engine",
        }

class FakeOnlineServices:
    def __init__(self):
        self.seq = 0
    def call(self, action, kind="read", **payload):
        self.seq += 1
        volatile = {"request_id":"req_%s" % self.seq, "duration_ms":self.seq * 10, "timestamp":self.seq}
        if action == "ping":
            return {"ok":True,"context":{"mxd":"fixture.mxd","pid":1234,"epoch":"doc-1"}, **volatile}
        if action == "status":
            return {"ok":True,"context":{"mxd":"fixture.mxd","pid":1234,"epoch":"doc-1"}, **volatile}
        if action == "inspect_current_map":
            return {"ok":True,"crs":"EPSG:32750","layer_count":4, **volatile}
        if action == "list_layers":
            return {"ok":True,"layers":[{"name":"JALAN"},{"name":"DESA"}], **volatile}
        if action == "list_layout_elements":
            return {"ok":True,"elements":[{"name":"Title"}], **volatile}
        if action == "get_dataframe_state":
            return {"ok":True,"data_frame":"Layers","spatial_reference":{"wkid":32651,"name":"WGS_1984_UTM_Zone_51N"}, **volatile}
        raise AssertionError(action)

class CollectorTests(unittest.TestCase):
    def test_offline_bridge_is_fail_fast(self):
        s = FakeOfflineServices()
        ctx = collect_live_context(s)
        self.assertFalse(ctx["available"])
        self.assertEqual(s.calls, ["ping"])
        self.assertEqual(s.payloads[0].get("timeout"), 3)
        self.assertEqual(ctx["errors"][0]["source"], "ping")

    def test_stale_owner_skips_ipc_and_lock(self):
        s = FakeStaleOwnerServices()
        ctx = collect_live_context(s)
        self.assertFalse(ctx["available"])
        self.assertEqual(s.calls, [])
        self.assertEqual(ctx["errors"][0]["source"], "bridge_owner")
        self.assertEqual(ctx["ping"]["code"], "BRIDGE_OFFLINE")

    def test_fingerprint_ignores_volatile_transport_metadata(self):
        a = collect_live_context(FakeOnlineServices())
        b = collect_live_context(FakeOnlineServices())
        self.assertTrue(a["available"])
        self.assertEqual(a["fingerprint"], b["fingerprint"])

    def test_fingerprint_ignores_sub_nanounit_arcobjects_float_noise(self):
        a = {
            "map": {"extent": {"XMax": 332426.83743008430}},
            "layout": {"elements": [{"width": 7.400600000000001}]},
        }
        b = {
            "map": {"extent": {"XMax": 332426.83743008436}},
            "layout": {"elements": [{"width": 7.400600000000850}]},
        }
        self.assertEqual(_fingerprint(a, {}), _fingerprint(b, {}))

if __name__ == "__main__":
    unittest.main()

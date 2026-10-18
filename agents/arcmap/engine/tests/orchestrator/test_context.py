import unittest

from orchestrator.context import collect_live_context


class FakeServices:
    def __init__(self, failures=None):
        self.failures = set(failures or ())
        self.calls = []

    def call(self, action, kind="read", **payload):
        self.calls.append((action, kind, dict(payload)))
        if action in self.failures:
            return {"ok": False, "code": "TEST_UNAVAILABLE", "error": action + " unavailable"}
        fixtures = {
            "ping": {"ok": True, "revision": "rev-1", "context": {"document": "fixture.mxd"}},
            "status": {"ok": True, "document_revision": "rev-1"},
            "inspect_current_map": {"ok": True, "crs": "EPSG:32750", "title": "Fixture"},
            "list_layers": {"ok": True, "layers": [{"name": "Jalan"}]},
            "list_layout_elements": {"ok": True, "elements": [{"name": "Title"}]},
            "get_dataframe_state": {"ok": True, "data_frame": "Layers", "spatial_reference": {"wkid": 32750}},
        }
        return fixtures[action]


class ContextCollectorTests(unittest.TestCase):
    def test_collector_calls_only_read_only_actions(self):
        services = FakeServices()
        ctx = collect_live_context(services)
        self.assertTrue(ctx["available"])
        self.assertEqual(
            [c[0] for c in services.calls],
            ["ping", "status", "inspect_current_map", "list_layers", "list_layout_elements", "get_dataframe_state"],
        )
        self.assertTrue(all(kind == "read" for _, kind, _ in services.calls))
        self.assertEqual([payload.get("timeout") for _, _, payload in services.calls], [3, 5, 10, 10, 10, 10])

    def test_failure_marks_context_unavailable(self):
        services = FakeServices({"list_layers"})
        ctx = collect_live_context(services)
        self.assertFalse(ctx["available"])
        self.assertTrue(any(e["source"] == "layers" for e in ctx["errors"]))

    def test_context_fingerprint_is_stable_for_same_state(self):
        a = collect_live_context(FakeServices())
        b = collect_live_context(FakeServices())
        self.assertEqual(a["fingerprint"], b["fingerprint"])

    def test_collector_never_raises_when_service_raises(self):
        class RaisingServices(FakeServices):
            def call(self, action, kind="read", **payload):
                if action == "status":
                    raise RuntimeError("fixture failure")
                return super().call(action, kind, **payload)

        ctx = collect_live_context(RaisingServices())
        self.assertFalse(ctx["available"])
        self.assertTrue(any(e["source"] == "status" for e in ctx["errors"]))


if __name__ == "__main__":
    unittest.main()

"""Offline acceptance for ArcMap 10.6 Multi Platform Add-In packaging."""
import ast
import hashlib
import imp
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "agents" / "arcmap" / "addin"
BUNDLE = ROOT / "agents" / "arcmap" / "artifacts" / "Zagent.MultiPlatform.ArcMap.esriaddin"
ADDIN_ID = "{6A9B7E2C-541F-4693-AB20-78D6E2C02111}"


class MultiPlatformArcMapAddInTests(unittest.TestCase):
    def test_addin_manifest_and_payload(self):
        self.assertTrue(BUNDLE.is_file())
        with zipfile.ZipFile(str(BUNDLE)) as archive:
            names = archive.namelist()
            self.assertEqual(
                ["config.xml", "Install/ZagentMultiPlatformToolbox.pyt",
                 "Install/zagent_arcmap_addin.py"],
                names,
            )
            root = ElementTree.fromstring(archive.read("config.xml"))
            namespace = {"esri": "http://schemas.esri.com/Desktop/AddIns"}
            self.assertEqual(ADDIN_ID, root.find("esri:AddInID", namespace).text)
            extension = root.find(
                "esri:AddIn/esri:ArcMap/esri:Extensions/esri:Extension", namespace
            )
            self.assertEqual("true", extension.attrib["autoLoad"])
            self.assertNotEqual("Zagent ArcMap", root.find("esri:Name", namespace).text)
            for name in names:
                if name.endswith((".pyt", ".py")):
                    ast.parse(archive.read(name).decode("utf-8-sig"), filename=name)
                    self.assertNotIn("Zagent Master", archive.read(name).decode("utf-8-sig"))

    def test_source_matches_packaged(self):
        with zipfile.ZipFile(str(BUNDLE)) as archive:
            self.assertEqual(
                (SOURCE / "config.xml").read_bytes(), archive.read("config.xml")
            )
            for name in (
                "Install/zagent_arcmap_addin.py",
                "Install/ZagentMultiPlatformToolbox.pyt",
            ):
                self.assertEqual((SOURCE / name).read_bytes(), archive.read(name))

    def test_locator_rejects_production_and_accepts_isolated_multi(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "local"
            locator = local / "Zagent" / "ArcMap" / "multi-platform.json"
            locator.parent.mkdir(parents=True)
            engine = Path(tmp) / "install" / "agents" / "arcmap" / "engine"
            bridge = engine / "arcmap_bridge"
            bridge.mkdir(parents=True)
            (bridge / "bootstrap.py").write_text("pass", encoding="utf-8")
            install = engine.parents[2]
            data = install / "data" / "arcmap"
            cfg = {
                "environment": "MULTI_PLATFORM",
                "engine_root": str(engine),
                "data_root": str(data),
                "config_dir": str(data / "config"),
                "ipc_root": str(data / "ipc"),
            }
            locator.write_text(json.dumps(cfg), encoding="utf-8")
            name = "zagent_multi_platform_addin_test_" + str(os.getpid())
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
                module = imp.load_source(
                    name, str(SOURCE / "Install" / "zagent_arcmap_addin.py")
                )
                self.assertEqual(str(engine), module._read_locator()["engine_root"])
                cfg["environment"] = "PRODUCTION"
                locator.write_text(json.dumps(cfg), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "foreign environment"):
                    module._read_locator()
                cfg["environment"] = "MULTI_PLATFORM"
                cfg["ipc_root"] = str(Path(tmp) / "foreign-ipc")
                locator.write_text(json.dumps(cfg), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "path mismatch"):
                    module._read_locator()
            sys.modules.pop(name, None)

    def test_extension_lifecycle_dispatches_to_bridge(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": tempfile.gettempdir()}):
            name = "zagent_multi_platform_lifecycle_" + str(os.getpid())
            module = imp.load_source(
                name, str(SOURCE / "Install" / "zagent_arcmap_addin.py")
            )
            calls = []
            class Bridge:
                def start(self): calls.append("start")
                def document_changed(self): calls.append("changed")
                def stop(self): calls.append("stop")
            with mock.patch.object(module, "_load_bridge", return_value=Bridge()):
                instance = module.BridgeExtension()
                instance.startup()
                instance.openDocument()
                instance.newDocument()
                instance.shutdown()
            self.assertEqual(["start", "changed", "start", "changed", "start", "stop"], calls)
            sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()

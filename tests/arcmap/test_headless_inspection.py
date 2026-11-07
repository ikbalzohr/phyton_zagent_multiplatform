"""Read-only disk inspection: real file-worker protocol, fake ArcPy only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKERS = ROOT / 'agents/arcmap/engine/orchestrator/adapters/file_worker'
spec = importlib.util.spec_from_file_location('headless_client', WORKERS / 'arcgis_process.py')
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)

ARCPY = '''
from types import SimpleNamespace as NS
class Document:
    title = 'Peta \\u00e9'
    author = 'Fixture'
    description = 'Read only'
    def save(self):
        raise AssertionError('save forbidden')
def MapDocument(path):
    assert path != 'CURRENT'
    return Document()
def ListDataFrames(doc):
    return [NS(name='Layers', scale=25000.0, rotation=0.0,
               spatialReference=NS(name='WGS 84', factoryCode=4326),
               extent=NS(XMin=1.0, YMin=2.0, XMax=3.0, YMax=4.0))]
class Layer:
    name = 'Jalan \\u00e9'
    longName = 'Jalan \\u00e9'
    visible = True
    isGroupLayer = False
    isBroken = False
    dataSource = 'D:/fixture/roads.shp'
    def supports(self, key):
        return key == 'DATASOURCE'
def ListLayers(doc, wildcard, frame):
    return [Layer()]
mapping = NS(MapDocument=MapDocument, ListDataFrames=ListDataFrames, ListLayers=ListLayers)
'''

class HeadlessInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='headless_fixture_')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.mxd = self.directory / 'peta_\u00e9.MXD'
        self.mxd.write_bytes(b'disposable fixture; not a real MXD')
        (self.directory / 'arcpy.py').write_text(ARCPY, encoding='utf-8')
        # Reuse the real Stage2 disk opener; only ArcPy is substituted.
        wrapper = self.directory / 'worker_entry.py'
        wrapper.write_text('import runpy, sys\nsys.path.insert(0, ' + repr(str(self.directory)) + ')\nrunpy.run_path(' + repr(str(WORKERS / 'worker27.py')) + ", run_name='__main__')\n", encoding='utf-8')
        self.client = client_module.ArcGISProcessFileWorker(ROOT / 'agents/arcmap/engine', python_exe=sys.executable)
        self.client.entry = wrapper

    def test_invalid_disk_paths_are_rejected_before_arcpy(self):
        (self.directory / 'arcpy.py').write_text("raise AssertionError('invalid path reached ArcPy')\n", encoding='utf-8')
        not_mxd = self.directory / 'not_mxd.txt'
        not_mxd.write_text('fixture', encoding='utf-8')
        for path in ('', 'CURRENT', 'current', 'relative.mxd', None, 12, {}, str(not_mxd), str(self.directory), str(self.directory / 'missing.mxd')):
            with self.subTest(path=path):
                result = self.client.inspect_mxd(mxd_path=path)
                self.assertFalse(result.get('ok'), result)
                self.assertIn(result.get('code'), ('INVALID_MXD_PATH', 'MXD_NOT_FOUND'))
                self.assertNotIn('traceback', result)

    def test_unsupported_layer_property_is_partial_not_invented(self):
        source = ARCPY.replace("return key == 'DATASOURCE'", "return False")
        (self.directory / 'arcpy.py').write_text(source, encoding='utf-8')
        result = self.client.inspect_mxd(mxd_path=str(self.mxd))
        self.assertTrue(result.get('ok'), result)
        self.assertTrue(result['partial'])
        self.assertTrue(result['warnings'])
        frame = result['frames'][0]
        layer = frame['layers'][0]
        self.assertEqual(result['document']['author'], 'Fixture')
        self.assertEqual(frame['scale'], 25000.0)
        self.assertEqual(frame['spatial_reference']['factory_code'], 4326)
        self.assertEqual(frame['extent'], dict(xmin=1.0, ymin=2.0, xmax=3.0, ymax=4.0))
        self.assertEqual(layer['visible'], True)
        self.assertEqual(layer['is_broken'], False)
        self.assertNotIn('data_source', layer)

    def test_inventory_is_bounded_and_reports_truncation(self):
        source = ARCPY.replace("title = 'Peta \\u00e9'", "title = 'x' * 5000")
        source = source.replace("return [NS(name='Layers'", "return [NS(name='Layers'")
        source = source.replace('YMax=4.0))]', 'YMax=4.0))] * 40')
        source = source.replace('return [Layer()]', 'return [Layer()] * 501')
        source = source.replace("return key == 'DATASOURCE'", 'return False')
        (self.directory / 'arcpy.py').write_text(source, encoding='utf-8')
        result = self.client.inspect_mxd(mxd_path=str(self.mxd))
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(len(result['frames']), 32)
        self.assertEqual(sum(len(f['layers']) for f in result['frames']), 500)
        self.assertLessEqual(len(result['document']['title']), 2048)
        self.assertLessEqual(len(result['warnings']), 128)
        self.assertTrue(result['partial'])
        self.assertTrue(any('truncated' in warning for warning in result['warnings']))

    def test_non_object_json_is_a_protocol_failure_not_an_exception(self):
        entry = self.directory / 'malformed_entry.py'
        entry.write_text("import sys\nfrom pathlib import Path\nPath(sys.argv[2]).write_text('[]', encoding='utf-8')\n", encoding='utf-8')
        self.client.entry = entry
        result = self.client.inspect_mxd(mxd_path=str(self.mxd))
        self.assertFalse(result.get('ok'), result)
        self.assertEqual(result['code'], 'FILE_WORKER_NO_RESULT')

    def test_rooted_without_drive_is_not_an_absolute_windows_target(self):
        import os
        if os.name != 'nt':
            self.skipTest('Windows path semantics')
        path = str(self.mxd)[2:]
        result = self.client.inspect_mxd(mxd_path=path)
        self.assertFalse(result.get('ok'), result)
        self.assertEqual(result['code'], 'INVALID_MXD_PATH')

    def test_property_getter_failure_is_partial_without_default_value(self):
        source = ARCPY + "\nLayer.visible = property(lambda self: (_ for _ in ()).throw(RuntimeError('unavailable')))\n"
        (self.directory / 'arcpy.py').write_text(source, encoding='utf-8')
        result = self.client.inspect_mxd(mxd_path=str(self.mxd))
        self.assertTrue(result.get('ok'), result)
        self.assertTrue(result['partial'])
        self.assertNotIn('visible', result['frames'][0]['layers'][0])
        self.assertTrue(any('.visible: unavailable' in w for w in result['warnings']))

    def test_document_and_frame_enumeration_failures_are_not_success(self):
        before = hashlib.sha256(self.mxd.read_bytes()).hexdigest()
        for operation in ('MapDocument', 'ListDataFrames'):
            source = ARCPY + "\ndef fail(*args):\n    raise RuntimeError('fixture mandatory read failed')\nmapping." + operation + " = fail\n"
            (self.directory / 'arcpy.py').write_text(source, encoding='utf-8')
            with self.subTest(operation=operation):
                result = self.client.inspect_mxd(mxd_path=str(self.mxd))
                self.assertFalse(result.get('ok'), result)
                self.assertEqual(result['code'], 'FILE_WORKER_FAILED')
                self.assertNotEqual(result['exit_code'], 0)
                self.assertEqual(hashlib.sha256(self.mxd.read_bytes()).hexdigest(), before)
            cache = self.directory / '__pycache__'
            if cache.exists():
                for p in cache.iterdir():
                    p.unlink()

    def test_layer_enumeration_failure_is_partial_not_empty_success(self):
        source = ARCPY + "\ndef fail(*args):\n    raise RuntimeError('fixture layer enumeration failed')\nmapping.ListLayers = fail\n"
        (self.directory / 'arcpy.py').write_text(source, encoding='utf-8')
        result = self.client.inspect_mxd(mxd_path=str(self.mxd))
        self.assertTrue(result.get('ok'), result)
        self.assertTrue(result['partial'])
        self.assertEqual(result['frames'][0]['layers'], [])
        self.assertTrue(any('.layers: unavailable' in w for w in result['warnings']))

    def test_missing_or_unparseable_response_is_a_protocol_failure(self):
        for body in ("", "from pathlib import Path\nPath(sys.argv[2]).write_text('not-json', encoding='utf-8')\n"):
            entry = self.directory / 'bad_protocol.py'
            entry.write_text('import sys\n' + body, encoding='utf-8')
            self.client.entry = entry
            with self.subTest(body=body):
                result = self.client.inspect_mxd(mxd_path=str(self.mxd))
                self.assertFalse(result.get('ok'), result)
                self.assertEqual(result['code'], 'FILE_WORKER_NO_RESULT')

    def test_nonzero_exit_cannot_report_success(self):
        entry = self.directory / 'exit_failure.py'
        entry.write_text("import sys\nfrom pathlib import Path\nPath(sys.argv[2]).write_text('{\"ok\": true}', encoding='utf-8')\nsys.exit(7)\n", encoding='utf-8')
        self.client.entry = entry
        result = self.client.inspect_mxd(mxd_path=str(self.mxd))
        self.assertFalse(result.get('ok'), result)
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['code'], 'FILE_WORKER_EXIT_FAILED')

    def test_protocol_timeout_remains_enforced(self):
        entry = self.directory / 'timeout.py'
        entry.write_text('import time\ntime.sleep(3)\n', encoding='utf-8')
        self.client.entry = entry
        result = self.client._call('inspect_mxd', {'mxd_path': str(self.mxd)}, timeout=1)
        self.assertFalse(result.get('ok'), result)
        self.assertEqual(result['code'], 'DEADLINE_EXCEEDED')

    def test_disk_inspection_uses_real_protocol_without_changing_source(self):
        self.assertTrue(callable(getattr(self.client, 'inspect_mxd', None)), 'inspect_mxd client operation missing')
        before = hashlib.sha256(self.mxd.read_bytes()).hexdigest()
        result = self.client.inspect_mxd(mxd_path=str(self.mxd))
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(result['document_path'], str(self.mxd))
        self.assertEqual(result['document']['path'], str(self.mxd))
        self.assertEqual(result['document']['title'], 'Peta \u00e9')
        self.assertEqual(result['frames'][0]['layers'][0]['name'], 'Jalan \u00e9')
        self.assertFalse(result['partial'])
        self.assertEqual(result['warnings'], [])
        self.assertEqual(before, hashlib.sha256(self.mxd.read_bytes()).hexdigest())
        self.assertEqual(result['exit_code'], 0)

if __name__ == '__main__':
    unittest.main()

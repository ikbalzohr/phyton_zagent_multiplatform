"""Portable owner-private event-store contract; no production configuration."""
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest


class EventStoreTests(unittest.TestCase):
    def load_store(self):
        path = getattr(self, 'module_path', Path(__file__).parents[1] / 'router' / 'diagnostic_events.py')
        self.assertTrue(path.exists(), 'owner-private persistent event recorder is missing')
        spec = importlib.util.spec_from_file_location('diagnostic_store_fixture', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_static_schema_and_private_persistent_record(self):
        module = self.load_store()
        with tempfile.TemporaryDirectory() as root:
            store = module.EventStore('router', Path(root))
            request_id = module.new_request_id()
            self.assertTrue(store.emit(request_id, 'mcp.initialize', 'UNEXPECTED_ERROR'))
            path = Path(root) / 'logs/diagnostics/router.jsonl'
            event = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(set(event), {'version','timestampUtc','requestId','component','stage','code','severity','message'})
            self.assertEqual(event['requestId'], request_id)
            self.assertRegex(request_id, r'^[a-f0-9]{32}$')
            self.assertTrue(event['timestampUtc'].endswith('Z'))
            self.assertEqual(event['component'], 'router')
            self.assertEqual(event['version'], 1)
            self.assertEqual(event['code'], 'UNEXPECTED_ERROR')
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_untrusted_codes_cannot_become_dynamic_messages(self):
        module = self.load_store()
        with tempfile.TemporaryDirectory() as root:
            store = module.EventStore('router', root)
            self.assertTrue(store.emit(module.new_request_id(), 'mcp.initialize', 'Bearer secret /private/path'))
            event = json.loads((Path(root) / 'logs/diagnostics/router.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(event['code'], 'UNEXPECTED_ERROR')
            self.assertNotIn('secret', json.dumps(event))

    def test_rotation_bounded_and_symlinks_denied(self):
        module = self.load_store()
        with tempfile.TemporaryDirectory() as root:
            store = module.EventStore('router', root)
            module.MAX_BYTES = 1500
            for _ in range(30):
                self.assertTrue(store.emit(module.new_request_id(), 'mcp.initialize', 'UNEXPECTED_ERROR'))
            files = sorted((Path(root) / 'logs/diagnostics').iterdir())
            self.assertEqual([p.name for p in files], ['router.jsonl', 'router.jsonl.1'])
            for path in files:
                self.assertLessEqual(path.stat().st_size, module.MAX_BYTES)
                for line in path.read_text(encoding='utf-8').splitlines():
                    json.loads(line)
            target = Path(root) / 'outside'
            target.write_text('untouched', encoding='utf-8')
            files[0].unlink()
            files[0].symlink_to(target)
            self.assertFalse(store.emit(module.new_request_id(), 'mcp.initialize', 'UNEXPECTED_ERROR'))
            self.assertFalse(store.available)
            self.assertEqual(target.read_text(encoding='utf-8'), 'untouched')

    def test_disabled_store_bounds_memory_and_warns_once(self):
        from unittest.mock import patch
        import io
        module = self.load_store()
        store = module.EventStore('router')
        with patch.object(module.sys, 'stderr', io.StringIO()) as stream:
            for _ in range(100):
                self.assertFalse(store.emit(module.new_request_id(), 'auth.token', 'AUTH_REQUIRED'))
            self.assertEqual(len(store.fallback), 64)
            self.assertFalse(store.available)
            self.assertEqual(stream.getvalue().count('ZAGENT_DIAGNOSTICS_UNAVAILABLE'), 1)

    def test_symlink_directory_and_rotated_file_are_denied(self):
        module = self.load_store()
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            outside = base / 'outside'
            outside.mkdir()
            (base / 'private').mkdir()
            (base / 'private/logs').symlink_to(outside, target_is_directory=True)
            store = module.EventStore('router', base / 'private')
            self.assertFalse(store.emit(module.new_request_id(), 'mcp.request', 'UNEXPECTED_ERROR'))
            self.assertEqual(list(outside.iterdir()), [])
        with tempfile.TemporaryDirectory() as root:
            store = module.EventStore('router', root)
            store.emit(module.new_request_id(), 'mcp.request', 'UNEXPECTED_ERROR')
            rotated = Path(root) / 'logs/diagnostics/router.jsonl.1'
            rotated.symlink_to(Path(root) / 'outside')
            self.assertFalse(store.emit(module.new_request_id(), 'mcp.request', 'UNEXPECTED_ERROR'))
            self.assertFalse((Path(root) / 'outside').exists())

    def test_parallel_writes_produce_complete_bounded_records(self):
        from concurrent.futures import ThreadPoolExecutor
        module = self.load_store()
        with tempfile.TemporaryDirectory() as root:
            store = module.EventStore('router', root)
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: store.emit(module.new_request_id(), 'mcp.request', 'UNEXPECTED_ERROR'), range(120)))
            self.assertTrue(all(results))
            events = [json.loads(line) for line in (Path(root) / 'logs/diagnostics/router.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(events), 120)
            self.assertEqual(len({event['requestId'] for event in events}), 120)

    @unittest.skipIf(os.name == 'nt', 'Unix mode tightening; Windows uses inherited private DataRoot ACL')
    def test_owner_created_core_log_directory_is_tightened_before_writing(self):
        module = self.load_store()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'logs/diagnostics'
            directory.mkdir(parents=True, mode=0o755)
            (Path(root) / 'logs').chmod(0o755)
            directory.chmod(0o755)
            store = module.EventStore('router', root)
            self.assertTrue(store.emit(module.new_request_id(), 'mcp.request', 'UNEXPECTED_ERROR'))
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(directory.parent.stat().st_mode & 0o777, 0o700)


class FilesEventStoreTests(EventStoreTests):
    module_path = Path(__file__).parents[3] / 'files/engine/app/core/diagnostic_events.py'


if __name__ == '__main__':
    unittest.main()

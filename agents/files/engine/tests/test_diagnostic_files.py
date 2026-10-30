"""Real Files MCP handler fixture, with disposable local configuration only."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))


class FilesDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cfg = cls.root / 'config'
        cfg.mkdir()
        (cfg / 'settings.json').write_text(json.dumps({'host':'127.0.0.1','port':8011,'secret_names':['.env']}), encoding='utf-8')
        (cfg / 'profiles.json').write_text(json.dumps({'schema_version':'2.0','active_profile':'agentRoot','profiles':[]}), encoding='utf-8')
        cls.env = patch.dict(os.environ, {'ZAGENT_FILES_DATA_ROOT':str(cls.root),
                              'ZAGENT_CORE_DATA_ROOT':str(cls.root / 'private')})
        cls.env.start()
        cls.server = importlib.import_module('app.mcp.server')

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()

    async def test_tool_boundary_returns_sanitized_correlated_mcp_error(self):
        from mcp.types import CallToolRequest, CallToolRequestParams
        secret = 'Bearer raw-token /private/config owner-secret'
        # Invoke the registered low-level SDK handler, not just our helper.
        handler = self.server.mcp._mcp_server.request_handlers[CallToolRequest]
        with patch.object(self.server, 'request_meta', side_effect=PermissionError(secret)):
            result = await handler(CallToolRequest(method='tools/call', params=CallToolRequestParams(name='files_ping', arguments={})))
        body = result.root.model_dump(mode='json', exclude_none=True)
        self.assertTrue(body['isError'])
        self.assertNotIn(secret, json.dumps(body), 'Files SDK exposes raw boundary exception')
        correlation = body['structuredContent']['error']['data']['requestId']
        self.assertRegex(correlation, r'^[a-f0-9]{32}$')
        events = [json.loads(line) for line in (self.root / 'private/logs/diagnostics/files.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(any(e['requestId'] == correlation and e['stage'] == 'files.authentication' for e in events))
        self.assertNotIn(secret, json.dumps(events))

    async def test_operation_failure_journal_and_diagnostics_never_copy_exception_text(self):
        import threading
        from app.core import diagnostic_events
        engine = self.server.engine
        secret = 'Bearer raw-operation-token /private/operation/path'
        meta = {}
        operation_id, _ = engine.journal.claim('ping', 'fixture-owner', 'fixture-idem', 'fingerprint', meta)
        meta['operation_id'] = operation_id
        with patch.object(engine.locks, 'acquire', side_effect=RuntimeError(secret)):
            with self.assertRaises(RuntimeError):
                await engine._run_with_catalog('ping', {}, meta, {'name':'fixture'}, [], threading.Event())
        row = engine.journal.get(operation_id, 'fixture-owner')
        self.assertEqual(row['state'], 'failed')
        self.assertNotIn(secret, json.dumps(row))
        events = [json.loads(line) for line in (self.root / 'private/logs/diagnostics/files.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(any(e['stage'] == 'files.operation' for e in events))


if __name__ == '__main__':
    unittest.main()

"""Source-only assertions: never imports product code or exercises the runtime."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'agents/files/engine'


class ConsumerSource(unittest.TestCase):
    def source(self, name):
        text = (ROOT / name).read_text(encoding='utf-8')
        ast.parse(text)
        return text

    def test_operation_bound_authority(self):
        text = self.source('app/core/execution_context.py')
        for marker in ('CONTEXT_TOOL_MISMATCH', 'CANONICAL_SCOPE_REQUIRED',
                       'FILES_RESOURCE_MUST_BE_UNIQUE', 'CLIENT_AUTHORITY_NOT_ALLOWED',
                       'UNKNOWN_FILES_OPERATION', 'CROSS_PROFILE_COPY_DISABLED',
                       'def authorize_operation(', 'def validate_profile('):
            self.assertIn(marker, text)

    def test_engine_rechecks_effect_binding(self):
        text = self.source('app/core/execution.py')
        self.assertIn('authorize_operation(metadata, op, args)', text)
        self.assertIn('validate_profile(metadata, profile)', text)
        self.assertIn('CURRENT.set(VerifiedContext(meta))', text)

    def test_native_fs_no_predictable_temporary_writes(self):
        text = self.source('app/core/fsops.py')
        self.assertIn('FILE_ATTRIBUTE_REPARSE_POINT', text)
        self.assertIn('def guard_subtree(', text)
        self.assertIn('tempfile.mkstemp(', text)
        self.assertNotIn('tmp.write_bytes(raw)', text)
        self.assertNotIn('tmp.write_text(new_content', text)
        self.assertIn('guard_no_links(target)', text)

    def test_command_dispatch_contract_and_update_guard(self):
        text = self.source('app/mcp/server.py')
        self.assertIn('authorize_command_call(name, arguments or {}, authority)', text)
        self.assertIn('from app.mcp.managed_commands import COMMAND_TOOL_NAMES, authorize_command_call', text)
        self.assertIn("name.startswith('files_update_')", text)
        self.assertLess(text.index('authorize_command_call(name'), text.index('CURRENT.set(authority)'))

    def test_recovered_security_regressions(self):
        context = self.source('app/core/execution_context.py')
        filesystem = self.source('app/core/fsops.py')
        self.assertIn("context.get('public_tool') == 'files_execute'", context)
        self.assertIn("forbidden.discard('task_id')", context)
        self.assertIn("current().get('effective_access') != 'write'", filesystem)
        self.assertIn('def guard_no_overlap(', filesystem)

    def test_catalog_matches_consumer_scope_sets(self):
        policy_path = ROOT.parents[2] / 'agents/tunnel/engine/router/files_policy.py'
        policy_tree = ast.parse(policy_path.read_text(encoding='utf-8'))
        catalog = next(ast.literal_eval(n.value) for n in policy_tree.body
                       if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name)
                       and t.id == 'FILES_TOOL_SCOPES' for t in n.targets))
        tree = ast.parse(self.source('app/core/execution_context.py'))
        sets = {n.targets[0].id: ast.literal_eval(n.value.args[0]) for n in tree.body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name) and n.value.func.id == 'frozenset'}
        expected = {'files_' + op: 'files:read' for op in sets['NATIVE_READ'] | sets['READ_CONTROLS']}
        expected.update({'files_' + op: 'files:write' for op in sets['NATIVE_WRITE'] | sets['WRITE_CONTROLS']})
        expected['files_execute'] = 'files:write'
        expected.update({tool: 'files:execute' for tool in sets['COMMAND_TOOLS']})
        self.assertEqual(expected, catalog)
        self.assertEqual(len(catalog), 47)

    def test_batch_disabled_before_binding(self):
        text = self.source('app/core/batch.py')
        self.assertIn("raise PermissionError('CROSS_PROFILE_COPY_DISABLED')", text)
        self.assertNotIn("engine.bind(meta['session_id'], source_profile)", text)


if __name__ == '__main__':
    unittest.main()

"""AST-only Files authority guards. Never import product or Windows fixtures."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / 'agents/tunnel/engine/router'


def tree(path):
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def literal(module, name):
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('Missing literal authority catalog: ' + name)


class FilesAuthoritySource(unittest.TestCase):
    def test_exact_inventory_is_classified_without_prefix_publication(self):
        path = ROUTER / 'files_policy.py'
        self.assertTrue(path.exists(), 'Files canonical scope catalog is missing')
        module = tree(path)
        catalog = literal(module, 'FILES_TOOL_SCOPES')
        management = literal(module, 'MANAGEMENT_ONLY_TOOLS')
        inventory = set()
        for rel in ('mcp/server.py', 'mcp/legacy.py'):
            module_inventory = tree(ROOT / 'agents/files/engine/app' / rel)
            inventory.update(n.name for n in module_inventory.body
                             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('files_'))
        inventory.add('files_copy_batch_between_profiles')
        # Command functions are registered by the MCP adapter in the command phase.
        inventory.update({'files_command_capabilities', 'files_command_cancel', 'files_exec_command',
                          'files_powershell_run', 'files_node', 'files_npm', 'files_npx', 'files_git',
                          'files_build', 'files_test', 'files_process_list', 'files_process_start', 'files_process_stop'})
        self.assertEqual(set(catalog) | management, inventory)
        self.assertEqual(len(inventory), 71)
        for node in module.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                self.assertNotIn(None, node.value.keys, 'Catalog expansion is forbidden')
                keys = [ast.literal_eval(k) for k in node.value.keys if k is not None]
                self.assertEqual(len(keys), len(set(keys)), 'Duplicate catalog key')
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Set):
                names = [ast.literal_eval(item) for item in node.value.elts]
                self.assertEqual(len(names), len(set(names)), 'Duplicate management name')
        self.assertFalse(set(catalog) & management)
        self.assertTrue(set(catalog.values()) <= {'files:read', 'files:write', 'files:execute'})
        for name in inventory:
            if name.startswith(('files_update_', 'files_profile_')) or 'between_profiles' in name:
                self.assertIn(name, management)
        self.assertEqual(catalog['files_execute'], 'files:write')
        self.assertEqual(catalog['files_process_list'], 'files:execute')
        functions = {n.name: n for n in module.body if isinstance(n, ast.FunctionDef)}
        self.assertIn('scope_for_files_tool', functions)
        self.assertIn('validate_files_tool_scope', functions)
        self.assertNotIn('startswith', ast.unparse(functions['scope_for_files_tool']))

    def test_context_derives_access_and_revalidates_without_renewal(self):
        module = tree(ROUTER / 'execution_context.py')
        functions = {n.name: n for n in module.body if isinstance(n, ast.FunctionDef)}
        create = functions['new_context']
        validate = functions['validate_context']
        for node in (create, validate):
            calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == 'validate_files_tool_scope']
            self.assertEqual(len(calls), 1, node.name + ' must enforce the canonical Files catalog')
        fields = next(
            ast.literal_eval(n.value.args[0]) for n in module.body
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
            and any(isinstance(t, ast.Name) and t.id == 'AUTHORITY_FIELDS' for t in n.targets))
        self.assertTrue({'effective_access', 'required_scope', 'public_tool'} <= fields)
        self.assertNotIn('new_context(', ast.unparse(validate))
        self.assertFalse(any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript)
                         and ast.unparse(t) == "value['deadline']" for t in n.targets)
                         for n in ast.walk(validate)))
        scheduler = ast.unparse(functions['scheduler_meta'])
        self.assertIn("'access_mode': 'write'", scheduler)
        self.assertIn("'installation:' + context['installation_id']", scheduler)


if __name__ == '__main__':
    unittest.main()

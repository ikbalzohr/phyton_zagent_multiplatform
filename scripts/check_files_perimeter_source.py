"""Source-only perimeter publication/receipt guards; no product imports."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / 'agents/tunnel/engine/router/server.py').read_text()
TREE = ast.parse(TEXT)

def body(name):
    node = next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(TEXT, node) or ''

class FilesPerimeterSource(unittest.TestCase):
    def test_cancel_target_selector_is_narrowly_allowed(self):
        validation = body('_validate_tool')
        self.assertIn('name in {"files_command_cancel", "files_operation_cancel"}', validation)
        self.assertIn('if key != "task_id"', validation)
        consumer = (ROOT / 'agents/files/engine/app/core/execution_context.py').read_text()
        self.assertIn("op in {'operation_cancel', 'command_cancel'}", consumer)

    def test_command_controls_do_not_queue_behind_the_command_they_cancel(self):
        self.assertIn('if name in _FILES_IMMEDIATE_CONTROLS:', body('_dispatch'))
        self.assertIn('await _executor(service, upstream, arguments, control)', body('_dispatch'))
        self.assertIn('tool not in _FILES_IMMEDIATE_CONTROLS', body('_executor'))
        self.assertIn('auth = await _revalidate(ctx.execution_context)', body('_executor'))

    def test_queued_command_revalidates_fresh_dual_scope(self):
        self.assertIn('validate_files_tool_scope(context["public_tool"], context["required_scope"], auth.scopes)', body('_revalidate'))

    def test_wrong_scope_cannot_be_published(self):
        policy = body('_policy')
        self.assertIn('scope_for_files_tool(name)', policy)
        self.assertIn('FILES_TOOL_SCOPE_MISMATCH', policy)

    def test_discovery_and_receipts_validate_command_scope_intersection(self):
        self.assertIn('validate_files_tool_scope(name, policy["scope"], auth.scopes)', body('_visible'))
        self.assertIn('validate_files_tool_scope(public_tool, scope, auth.scopes)', body('_owned_task'))

if __name__ == '__main__':
    unittest.main()

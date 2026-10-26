"""AST/source guards only: no product imports or runtime execution."""
import ast
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'agents/tunnel/engine/router/server.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)

def function(name):
    return next(n for n in TREE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)

class TaskReadAuthorizationSource(unittest.TestCase):
    def test_read_controls_use_origin_authorization_before_control_policy(self):
        dispatch = function('_dispatch')
        branch = next((n for n in dispatch.body if isinstance(n, ast.If)
                       and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name)
                       and n.test.left.id == 'name' and isinstance(n.test.ops[0], ast.In)
                       and isinstance(n.test.comparators[0], (ast.Set, ast.Tuple))
                       and {e.value for e in n.test.comparators[0].elts if isinstance(e, ast.Constant)} ==
                       {'zagent_task_status', 'zagent_task_result', 'zagent_task_list'}), None)
        self.assertIsNotNone(branch, 'read controls must use task-origin authorization, not a separate tool grant')
        assert branch is not None
        generic = next(n for n in dispatch.body if isinstance(n, ast.Assign) and ast.unparse(n.value) == '_policy(name)')
        self.assertLess(branch.lineno, generic.lineno)
        self.assertIn('await _owned_task', (ast.get_source_segment(SOURCE, branch) or ""))
        self.assertIn('_validate_tool(name, arguments, auth)', (ast.get_source_segment(SOURCE, dispatch) or "").splitlines()[2])

    def test_owned_task_checks_owner_and_current_origin_grant(self):
        owned = ast.get_source_segment(SOURCE, function('_owned_task')) or ''
        self.assertIn('row.get("session_id") != auth.owner', owned)
        self.assertIn('policy = _policy(public_tool)', owned)
        self.assertIn("scope = policy['scope']", owned)
        self.assertIn("policy.get('enabled', True) is not True", owned)
        self.assertIn('require_profile_management(auth, placement, authorizer(), public_tool)', owned)
        self.assertIn('catalog=await _files_catalog(auth, authorizer())', owned)
        self.assertIn('auth.require(scope, public_tool)', owned)

if __name__ == '__main__':
    unittest.main()

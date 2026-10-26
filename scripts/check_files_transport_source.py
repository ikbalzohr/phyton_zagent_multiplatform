"""AST/source-only contract assertions. Windows seam fixtures NOT_RUN here."""
import ast
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class FilesTransportSource(unittest.TestCase):
    def test_files_registry_never_adds_legacy_metadata_argument(self):
        tree=ast.parse((ROOT/'agents/tunnel/engine/router/registry.py').read_text(encoding='utf-8'))
        invoke=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='invoke')
        conditions=[n for n in ast.walk(invoke) if isinstance(n,ast.If) and any(
            isinstance(x,ast.Assign) and any(isinstance(t,ast.Subscript) and
            isinstance(t.value,ast.Name) and t.value.id=='call_arguments' and
            isinstance(t.slice,ast.Constant) and t.slice.value=='metadata' for t in x.targets)
            for x in ast.walk(n))]
        self.assertTrue(any('service_id not in' in ast.unparse(n.test) and
                            'zagent_files' in ast.unparse(n.test) and
                            'zagent_files_v3' in ast.unparse(n.test) for n in conditions))
    def test_public_metadata_remains_forbidden(self):
        tree=ast.parse((ROOT/'agents/tunnel/engine/router/execution_context.py').read_text(encoding='utf-8'))
        fields=next(ast.literal_eval(n.value.args[0]) for n in tree.body if
                    isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and any(isinstance(t,ast.Name) and t.id=='AUTHORITY_FIELDS' for t in n.targets))
        self.assertIn('metadata',fields)
    def test_workspace_selector_exception_is_narrow_and_owner_checked(self):
        tree=ast.parse((ROOT/'agents/tunnel/engine/router/execution_context.py').read_text(encoding='utf-8'))
        functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        self.assertIn('authority_arguments',functions)
        body=ast.unparse(functions['authority_arguments'])
        self.assertIn('WORKSPACE_SCOPE_MISMATCH',body)
        self.assertIn("arguments['workspace_id'] != workspace_id",body)
        self.assertIn("key != 'workspace_id'",body)
        server=(ROOT/'agents/tunnel/engine/router/server.py').read_text(encoding='utf-8')
        self.assertIn('selected = authority_arguments(name, arguments, auth.workspace_id)',server)
        self.assertIn('for key, value in selected.items() if key != "task_id"',server)

    def test_consumer_does_not_exempt_metadata(self):
        tree=ast.parse((ROOT/'agents/files/engine/app/core/execution_context.py').read_text(encoding='utf-8'))
        op=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_operation')
        expr=next(n.value for n in ast.walk(op) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='forbidden' for t in n.targets))
        self.assertEqual(ast.unparse(expr),'set(AUTHORITY_ARGUMENTS)')

if __name__=='__main__':unittest.main()

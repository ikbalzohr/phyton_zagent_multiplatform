"""Run real PowerShell plans through the actual isolated Python consumer parser.

No product imports, runtime startup, private config or Windows ACL claims.
"""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CommandPolicyRebindTests(unittest.TestCase):
    def test_generated_plans_are_accepted_without_authority_changes(self):
        pwsh = shutil.which('pwsh') or '/opt/pwsh/pwsh'
        source = ROOT / 'agents/files/engine/app/mcp/managed_commands.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        nodes: list[ast.stmt] = [node for node in tree.body if
                 isinstance(node, ast.FunctionDef) and node.name == '_policy_profiles' or
                 isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                 t.id == '_POLICY_KEYS' for t in node.targets)]
        self.assertEqual(len(nodes), 2)
        namespace = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
        parse = namespace['_policy_profiles']
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as temp:
            output = Path(temp) / 'plans.json'
            result = subprocess.run([pwsh, '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-File', str(ROOT / 'packaging/scripts/Test-OwnerCommandPolicyRebind.ps1'),
                                     '-PlanOutput', str(output)], capture_output=True, text=True, timeout=90)
            print(result.stdout, end='')
            self.assertEqual(result.returncode, 0, result.stderr)
            plans = json.loads(output.read_text(encoding='utf-8'))
        for version in ('v1', 'v2'):
            with self.subTest(version=version):
                before = parse(plans['original_' + version])
                after = parse(plans[version])
                self.assertIn('agentRoot', after)
                self.assertNotIn('old', after)
                old = before.pop('old')
                new = after.pop('agentRoot')
                self.assertEqual(new.pop('profile_id'), 'agentRoot')
                self.assertEqual(old.pop('profile_id'), 'old')
                self.assertEqual(new.pop('root'), r'D:\3-Ikbalzohr\Agent')
                self.assertEqual(old.pop('root'), r'D:\old')
                self.assertEqual(new, old, 'authority fields must remain identical')
                self.assertEqual(after, before, 'sibling policies must remain identical')
        print('CONSUMER_ACCEPTANCE=PASS v1+v2; authority and sibling equality verified')


if __name__ == '__main__':
    unittest.main()

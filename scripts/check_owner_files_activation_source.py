"""Source-only owner activation contract; no PowerShell execution."""
from pathlib import Path
import unittest
import ast
import json

ROOT = Path(__file__).resolve().parents[1]
class OwnerFilesActivationSource(unittest.TestCase):
    def test_catalog_excludes_unimplemented_commands_and_accounts_for_all_tools(self):
        catalog = json.loads((ROOT / 'packaging/files-capabilities.json').read_text())
        router = ast.parse((ROOT / 'agents/tunnel/engine/router/files_policy.py').read_text())
        values = {n.targets[0].id: ast.literal_eval(n.value) for n in router.body
                  if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id in ('FILES_TOOL_SCOPES', 'MANAGEMENT_ONLY_TOOLS')}
        commands = ast.parse((ROOT / 'agents/files/engine/app/mcp/managed_commands.py').read_text())
        node = next(n for n in commands.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'UNSUPPORTED_COMMAND_TOOLS' for t in n.targets))
        assert isinstance(node.value, ast.Call)
        unsupported = set(ast.literal_eval(node.value.args[0]))
        self.assertEqual(set(catalog['unsupported']), unsupported)
        self.assertEqual(catalog['tools'], {k: v for k, v in values['FILES_TOOL_SCOPES'].items() if k not in unsupported})
        self.assertEqual(set(catalog['management_only']), values['MANAGEMENT_ONLY_TOOLS'])
        self.assertEqual(len(catalog['tools']) + len(catalog['management_only']) + len(unsupported), 71)
        self.assertFalse(set(catalog['tools']) & unsupported)

    def test_explicit_consent_preserves_existing_grant_lifetime(self):
        path = ROOT / 'packaging/scripts/Enable-OwnerFilesCapabilities.ps1'
        self.assertTrue(path.exists())
        text = path.read_text()
        for token in ('ALLOW READ WRITE', 'ALLOW OWNER ACCOUNT EXECUTION', 'Assert-CoreStopped',
                      'Assert-SnapshotUnchanged', 'Write-PrivateAtomic', 'FILES_CAPABILITIES_CONFIGURED',
                      'files:execute', 'remote_execution_policy.json', 'acknowledge_host_access',
                      'Get-Command', 'files-capabilities.json', 'Grant expired', 'expires_at',
                      'read-write', 'appBridge', 'owner-account'):
            self.assertIn(token, text)
        for forbidden in ('AddHours(', 'AddDays(', '$grant.expires_at =', '$grant.revoked =',
                          'SetEnvironmentVariable', 'Invoke-WebRequest', 'Start-Process'):
            self.assertNotIn(forbidden, text)

if __name__ == '__main__':
    unittest.main()

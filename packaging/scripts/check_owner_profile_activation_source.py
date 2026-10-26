"""Non-importing source contract guard; NOT PowerShell/Windows acceptance."""
from pathlib import Path
import ast
import re

base = Path(__file__).resolve().parent
entry = base / 'Activate-OwnerFilesProfile.ps1'
lib = base / 'Owner-ProfileActivation.ps1'
assert entry.is_file(), 'owner-local activation entry point missing'
assert lib.is_file(), 'activation implementation missing'
s = entry.read_text(encoding='utf-8')
l = lib.read_text(encoding='utf-8')
for literal in ('Assert-ZagentOwnerConsole', 'Assert-CoreStopped', 'device_identity.json',
                'internal-secrets.dpapi.json', 'D:\\3-Ikbalzohr\\Agent',
                'ALLOW OWNER ACCOUNT EXECUTION AT agentRoot', '1793539666'):
    assert literal in s, literal
for literal in ('active_profile', 'allowed_profile_ids', 'version = 2',
                'Concurrent configuration change', 'ACTIVATION_INCOMPLETE',
                'FileMode]::CreateNew', 'Assert-SnapshotUnchanged',
                'Assert-CoreStopped', 'Read-BoundedBytes', 'Read-StrictJson'):
    assert literal in s + l, literal
for prohibited in ('Remove-Item', 'Delete(', 'Start-Process', 'Stop-Process',
                   'Set-Content', 'Unprotect', 'New-SelfSignedCertificate', 'Invoke-RestMethod'):
    assert prohibited not in s + l, prohibited
assert l.index('# PREPARE ALL') < l.index('# COMMIT: grant last')
assert "@('profiles','commands','grant')" in l
assert 'Replace-ActivationToken' in l, 'preserve unrelated JSON tokens exactly'
fixture = (base / 'Test-OwnerProfileActivation.ps1').read_text(encoding='utf-8')
for literal in ('marker', 'concurrent', 'partial', 'revoked', 'unapproved', 'backup', '1793539666'):
    assert literal in fixture, literal
# Reconcile source literals without importing Files (imports can write runtime data).
repo = base.parent.parent
managed = ast.parse((repo / 'agents/files/engine/app/mcp/managed_commands.py').read_text(encoding='utf-8'))
values = {}
for node in managed.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
        if name in {'COMMAND_TOOL_NAMES', 'UNSUPPORTED_COMMAND_TOOLS', '_POLICY_KEYS'}:
            assert isinstance(node.value, ast.Call) and len(node.value.args) == 1
            values[name] = ast.literal_eval(node.value.args[0])
def ps_literal_array(name):
    match = re.search(r'\$' + name + r'\s*=\s*@\(([^)]*)\)', l)
    assert match, name
    return re.findall(r"'([^']+)'", match.group(1))
assert set(ps_literal_array('supported')) == values['COMMAND_TOOL_NAMES'] - values['UNSUPPORTED_COMMAND_TOOLS']
assert set(ps_literal_array('keys')) == values['_POLICY_KEYS']
manager = (repo / 'agents/files/engine/app/profiles/manager.py').read_text(encoding='utf-8')
assert 'data["active_profile"] = name' in manager, 'source-defined Files default changed'
print('PASS owner-profile source contract; command tools/keys + Files default reconciled (no product imports)')

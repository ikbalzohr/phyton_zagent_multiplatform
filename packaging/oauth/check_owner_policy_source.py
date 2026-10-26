"""Non-executing source guards; NOT Windows parser/behavioral acceptance."""
from pathlib import Path
s=(Path(__file__).resolve().parents[1]/'scripts/Configure-OwnerOAuth.ps1').read_text(encoding='utf-8')
assert '[switch]$ActivateReadOnlyGrant' in s
assert '$revoked = -not $ActivateReadOnlyGrant' in s, 'Explicit read-only activation gate missing'
assert 'Activation requires the exact staged policy' in s, 'Cannot activate an arbitrary policy'
assert "scopes = @('files:read'); tools = @('files_stat','files_read')" in s
assert 'files:write' not in s and 'files_exec' not in s
assert 'revoked = $revoked; expires_at' in s
assert 'installation_id = $identity.installation_id; revoked = $revoked' in s
assert "@('files:read')" in s and 'Files approval changed while waiting' in s
assert '[IO.File]::Replace($temp, $target, $backup)' in s
assert 'Read-back failed; preserve backup and stop' in s
print('PASS: source guards for explicit exact-profile read-only activation, backup and read-back.')
print('NOT_RUN: Windows parser/runtime, real policy activation and OAuth validation.')

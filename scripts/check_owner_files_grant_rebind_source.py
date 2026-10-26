"""Source assertions only; PowerShell parser/ACL/atomic-write behavior NOT_RUN (Windows-only).

Proves the noninteractive owner Files grant rebind entry is bounded: one file, two
tokens, no consent prompt, no authority/scope/expiry mutation.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'packaging/scripts/Rebind-OwnerFilesGrantProfile.ps1'
DEFERRED_ENTRY = ROOT / 'packaging/scripts/Activate-OwnerFilesProfile.ps1'


class GrantRebindSource(unittest.TestCase):
    def test_entry_exists_and_is_bounded(self):
        self.assertTrue(ENTRY.is_file(), 'Noninteractive grant rebind helper missing')
        text = ENTRY.read_text(encoding='utf-8')
        for required in (
            'Assert-ZagentOwnerConsole', 'Assert-CoreStopped', 'Set-StrictMode -Version Latest',
            'Read-BoundedBytes $path', 'Read-StrictJson $before',
            'Assert-SnapshotUnchanged $path $before', 'Assert-MigrationPrivatePath $backup',
            'Set-ZagentOwnerAcl $temp', '[IO.File]::Replace($temp, $path, $backup)',
            'PROFILE_GRANT_REBOUND', 'PROFILE_GRANT_ALREADY_CURRENT',
            'Get-ProfileAdminSpan', 'ProfileAdministrationBootstrap.ps1',
            'allowed_profile_ids', 'profile_id',
            '$grant.revoked -ne $false', '$entries.Count -ne 1',
            '$data = (Resolve-Path -LiteralPath $DataRoot).Path',
            'Unrelated configuration bytes changed',
            'Renew-OwnerFilesGrant.ps1',
        ):
            self.assertTrue(required in text, 'missing required literal: ' + required)
        for forbidden in (
            'Read-Host', 'Start-Process', 'Stop-Process', 'Set-Content', 'Remove-Item',
            'Unprotect', 'Invoke-RestMethod', 'Invoke-WebRequest',
            'Activate-OwnerFilesProfile',
            '$grant.revoked =', '$grant.tools =', '$grant.scopes =', '$grant.expires_at =',
            '$resource.revoked =', '$resource.kind =', '$grant.files_resource =',
            '$config.tool_policy =',
        ):
            self.assertTrue(forbidden not in text, 'forbidden literal present: ' + forbidden)
        # Single-document scope: the helper must never touch profiles.json or command policy.
        self.assertNotIn('profiles.json', text)
        self.assertNotIn('remote_execution_policy', text)
        # Exactly one write pair, and the byte-preservation proof must precede any write.
        self.assertEqual(text.count('[IO.File]::Open('), 1)
        self.assertEqual(text.count('[IO.File]::Replace('), 1)
        self.assertLess(text.index('Unrelated configuration bytes changed'), text.index('[IO.File]::Replace('))
        # Reverse edit must undo the allowlist change before the profile token.
        self.assertLess(text.index('$spanAllowBack'), text.index('$spanProfileBack'))

    def test_deferred_interactive_entry_still_excluded(self):
        # The legacy activation entry keeps its Read-Host consent; the new helper must not
        # depend on it, so the contract's "no local approval again" rule stays provable.
        legacy = DEFERRED_ENTRY.read_text(encoding='utf-8')
        self.assertIn('Read-Host', legacy)


if __name__ == '__main__':
    unittest.main()

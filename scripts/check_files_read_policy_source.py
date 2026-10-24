"""Source-contract checks, not PowerShell parsing or Windows execution."""
from pathlib import Path
import unittest

class ReadPolicySource(unittest.TestCase):
    def test_provisioner_writes_matching_read_policies(self):
        text = (Path(__file__).resolve().parents[1] / 'packaging/scripts/Configure-OwnerOAuth.ps1').read_text()
        self.assertIn("foreach ($name in @('files_stat','files_read'))", text)
        self.assertIn("-NotePropertyName tool_policy", text)
        self.assertIn("scope = 'files:read'", text)
        self.assertIn('Conflicting Files tool policy', text)

    def test_bounded_patch_preserves_authority(self):
        path = Path(__file__).resolve().parents[1] / 'packaging/scripts/Repair-OwnerFilesReadPolicy.ps1'
        self.assertTrue(path.exists())
        text = path.read_text()
        for required in ('Duplicate JSON member rejected', 'Assert-CoreStopped', 'Assert-ReviewedMetadata',
                         'Assert-SnapshotUnchanged $target $before', '[IO.File]::Replace',
                         'Assert-MigrationPrivatePath $backup', '$parsed.ToolPolicy', '$parsed.RootEnd',
                         "@('files_stat','files_read')", "scope = 'files:read'", 'Conflicting Files tool policy',
                         'FILES_READ_POLICY_REPAIRED', 'Backup mismatch', 'Read-back mismatch'):
            self.assertIn(required, text)
        for forbidden in ('AddHours(', 'AddDays(', '$resource.grants =', '$grant.revoked =',
                          '$grant.expires_at =', 'Invoke-WebRequest', 'Start-Process'):
            self.assertNotIn(forbidden, text)
        self.assertIn("$revision = 'files-read-policy-'", text)
        self.assertIn("$path[0] -ceq 'tool_policy'", text)

if __name__ == '__main__':
    unittest.main()

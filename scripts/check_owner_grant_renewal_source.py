"""Source assertions only; Windows parser/ACL/atomic-write behavior NOT_RUN."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]

class RenewalSource(unittest.TestCase):
    def test_expiry_only_private_renewal(self):
        p = ROOT / 'packaging/scripts/Renew-OwnerFilesGrant.ps1'
        self.assertTrue(p.exists(), 'Bounded owner renewal helper missing')
        text = p.read_text(encoding='utf-8')
        for required in ('[ValidateSet(7)]', 'Assert-CoreStopped', 'Read-StrictJson',
                         'Assert-SnapshotUnchanged $path $before',
                         '$grant.revoked -cne $false', '$entries.Count -ne 1',
                         '[IO.File]::Replace($temp, $path, $backup)',
                         'Set-ZagentOwnerAcl $temp', 'GRANT_RENEWED',
                         '$newExpiry = [DateTimeOffset]::UtcNow.AddDays($Days).ToUnixTimeSeconds()',
                         '$matches.Count -ne 1', '$check.grants',
                         'Read-BoundedBytes $backup', 'Read-BoundedBytes $path'):
            self.assertIn(required, text)
        for forbidden in ('$grant.revoked =', '$grant.tools =', '$grant.scopes =',
                          '$grant.files_resource =', 'Start-Process', 'Set-Content'):
            self.assertNotIn(forbidden, text)

if __name__ == '__main__':
    unittest.main()

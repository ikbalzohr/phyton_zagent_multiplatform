"""Nonexecuting source guards only; NOT Windows behavioral acceptance."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'packaging/scripts/Invoke-ZagentOwnerSetup.ps1'


class OwnerSetupSource(unittest.TestCase):
    def test_entry_is_bounded_noninteractive_composition(self):
        self.assertTrue(TARGET.is_file(), 'owner setup entry missing')
        source = TARGET.read_text(encoding='utf-8')
        for token in ("'Validate','ApplyCapability','ApplyCapabilityAndStart'", "= 'Validate'",
                      'New-ProfileAdministrationPlan', 'Enable-OwnerProfileAdministration.ps1',
                      'Start-OwnerCore.ps1', 'Assert-ProfileAdminCoreStopped',
                      'Assert-SnapshotUnchanged', 'Get-FileHash', 'CoreSha256',
                      'OWNER_SETUP_PREFLIGHT_ONLY', 'MIGRATION_NOT_APPLIED',
                      'DEPLOYMENT_NOT_PERFORMED', 'finally', '$previousFiles', '$previousTunnel'):
            self.assertIn(token, source)
        # No private API auth acquisition, generic shell, process termination, or offline profile writes.
        code = '\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('#'))
        for forbidden in ('Read-Host', 'Stop-Process', 'Start-Process', 'Invoke-Expression',
                          'Invoke-RestMethod', 'Remove-Item', 'Rebind-OwnerFilesGrantProfile',
                          'Activate-OwnerFilesProfile', 'Configure-OwnerOAuth', 'Renew-OwnerFilesGrant',
                          'ConvertTo-SecureString', 'Unprotect', 'profiles.json', 'identity.json',
                          '[IO.File]::Write', 'Set-Content'):
            self.assertNotIn(forbidden.lower(), code.lower())
        self.assertNotRegex(code, r'(?i)SetEnvironmentVariable|python\s+-m|pip\s+install')
        self.assertLess(source.index('New-ProfileAdministrationPlan'), source.index('& $enableHelper'))
        self.assertLess(source.index('& $enableHelper'), source.index('& $startHelper'))
        self.assertIn('Assert-SnapshotUnchanged $target $after', source)
        self.assertIn('Assert-SnapshotUnchanged $machinePath $machineBytes', source)
        self.assertRegex(source, re.escape("$Mode -ceq 'Validate'"))

    def test_helpers_and_launch_prerequisites_are_validated_before_mutation(self):
        source = TARGET.read_text(encoding='utf-8')
        self.assertIn('Assert-ZagentPlainPath $helper', source)
        boundary = source.index('& $enableHelper')
        for token in ('Assert-ZagentOwnerConsole', 'Assert-ZagentOwnerAcl $DataRoot',
                      '$machine.install_root -isnot [string]', '$machine.data_root -isnot [string]',
                      'Get-FileHash -LiteralPath $CoreExecutable', "'agents\\web\\engine\\dist\\index.js'",
                      "'config\\internal-secrets.dpapi.json'", 'Assert-SnapshotUnchanged $target $before'):
            self.assertLess(source.index(token), boundary)
        self.assertNotIn('Mandatory=$true', source)  # missing inputs throw rather than prompt
        self.assertIn("$env:ZAGENT_FILES_PYTHON = $previousFiles", source)
        self.assertIn("$env:ZAGENT_TUNNEL_PYTHON = $previousTunnel", source)


if __name__ == '__main__':
    unittest.main(verbosity=2)

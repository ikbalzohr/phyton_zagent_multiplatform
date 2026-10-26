"""Source-only lane C guards. NOT a C#/PowerShell runtime or compiler test."""
from pathlib import Path
import hashlib
import json
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
class DirectProfileCoreSource(unittest.TestCase):
    def test_bootstrap_rejects_collection_authority_before_comparison(self):
        text = (ROOT / 'packaging/scripts/ProfileAdministrationBootstrap.ps1').read_text()
        for field in ['rs.workspace_id', 'resource.kind', 'resource.device_id', 'resource.installation_id',
                      'resource.profile_id', 'cap.workspace_id', 'cap.device_id', 'cap.installation_id', 'existing.Value.scope']:
            self.assertIn('$' + field + ' -isnot [string]', text, field)
        for field in ['config', 'rs', 'grant', 'resource', 'existing.Value']:
            self.assertIn('$' + field + ' -isnot [pscustomobject]', text, field)

    def test_duplicate_editor_has_no_undefined_dereference(self):
        ui = (ROOT / 'src/Zagent.Core/wwwroot/dashboard.js').read_text()
        self.assertIn('if (!editor) return;', ui)

    def test_files_child_receives_trusted_core_placement(self):
        factory = (ROOT / 'src/Zagent.Core/Agents/Files/FilesProcessFactory.cs').read_text()
        self.assertIn('["ZAGENT_CORE_DATA_ROOT"] = string.IsNullOrEmpty(options.CoreDataRoot)', factory)
        self.assertIn('? "" : Path.GetFullPath(options.CoreDataRoot)', factory)
        self.assertNotIn('string.IsNullOrWhiteSpace(options.InstallationId) ||', factory)
        self.assertIn('["ZAGENT_INSTALLATION_ID"] = options.InstallationId', factory)
        host = (ROOT / 'src/Zagent.Core/Manager/ManagerCoreHost.cs').read_text()
        files = host.split('var filesOptions = new FilesIntegrationOptions(', 1)[1].split(');', 1)[0]
        self.assertIn('CoreDataRoot: data', files)
        self.assertIn('InstallationId: machineIdentity.InstallationId', files)

    def test_utf8_digest_matches_files_consumer(self):
        fixture = json.loads((ROOT / 'tests/contracts/profile-admin-wire-v1.json').read_text())
        consumer = (ROOT / 'agents/files/engine/app/profiles/administration.py').read_text()
        self.assertIn('ensure_ascii=False', consumer)
        self.assertEqual(fixture['canonical'], json.dumps(fixture['arguments'], sort_keys=True, separators=(',', ':'), ensure_ascii=False))
        channel = (ROOT / 'src/Zagent.Core/Manager/InternalManagementChannel.cs').read_text()
        self.assertNotIn("or > '~'", channel)

    def test_dashboard_uses_trusted_direct_backend(self):
        client = ROOT / 'src/Zagent.Core/Manager/ProfileAdministrationClient.cs'
        self.assertTrue(client.exists(), 'Missing typed private profile administration client')
        text = client.read_text()
        for literal in ['zagent.profile_admin_context', 'zagent.profile_catalog_context', 'payload_digest', 'bootstrap_resource', 'capability_revision']:
            self.assertIn(literal, text)
        self.assertNotIn('Environment.UserName', text)
        host = (ROOT / 'src/Zagent.Core/Dashboard/DashboardHost.cs').read_text()
        self.assertIn('MapProfileAdministration', host)
        self.assertNotIn('await Accept(operations, ctx, "profiles.add"', host)
        self.assertNotIn('await Accept(operations, ctx, "profiles.update"', host)
        ui = (ROOT / 'src/Zagent.Core/wwwroot/dashboard.js').read_text()
        self.assertIn('/default', ui)
        self.assertIn('description', ui)
    def test_legacy_profile_writers_are_not_administration(self):
        text = (ROOT / 'src/Zagent.Core/Manager/FilesManagerReadModel.cs').read_text()
        for writer in ['import request_add;', 'import request_delete;', 'import request_update;', 'import switch_default_profile;']:
            self.assertNotIn(writer, text)
        self.assertIn('Authenticated direct profile administration is required', text)
    def test_literal_wire_contract_and_exact_tool_actions(self):
        fixture = json.loads((ROOT / 'tests/contracts/profile-admin-wire-v1.json').read_text())
        canonical = json.dumps(fixture['arguments'], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        self.assertEqual(canonical, fixture['canonical'])
        self.assertEqual(hashlib.sha256(canonical.encode('utf-8')).hexdigest(), fixture['sha256'])
        client = (ROOT / 'src/Zagent.Core/Manager/ProfileAdministrationClient.cs').read_text()
        match = re.search(r'Actions = \[(.*?)\]', client)
        assert match is not None, 'Exact C# action declaration missing'
        self.assertEqual(re.findall(r'"([a-z_]+)"', match[1]), fixture['actions'])
        ps = (ROOT / 'packaging/scripts/ProfileAdministrationBootstrap.ps1').read_text()
        match = re.search(r'\$actions = @\((.*?)\)', ps)
        assert match is not None, 'Exact bootstrap action declaration missing'
        self.assertEqual(re.findall(r"'([a-z_]+)'", match[1]), fixture['actions'])
        self.assertIn('Math.Min(DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 300, binding.ExpiresAt)', client)
        dashboard = (ROOT / 'src/Zagent.Core/Dashboard/DashboardProfileAdministration.cs').read_text()
        self.assertIn('FindFirstValue(ClaimTypes.NameIdentifier)', dashboard)
        self.assertIn('[Microsoft.AspNetCore.Mvc.FromBody] JsonObject request', dashboard)
        self.assertIn('RequireAuthorization("Administrator").RequireRateLimiting("commands")', dashboard)
    def test_bootstrap_is_separate_and_noninteractive(self):
        path = ROOT / 'packaging/scripts/Enable-OwnerProfileAdministration.ps1'
        self.assertTrue(path.exists(), 'Missing bounded capability-only bootstrap')
        text = path.read_text() + (ROOT / 'packaging/scripts/ProfileAdministrationBootstrap.ps1').read_text()
        for token in ['OwnerPrincipal', 'Assert-ProfileAdminCoreStopped', 'Assert-SnapshotUnchanged', 'Read-StrictJson', 'File]::Replace', 'profile_management']:
            self.assertIn(token, text)
        for forbidden in ['Read-Host', 'Activate-OwnerFilesProfile', 'Owner-ProfileActivation.ps1', 'CryptUnprotectData', 'Start-Process']:
            self.assertNotIn(forbidden, text)
        self.assertNotIn('principal_v1_41d408', text)
if __name__ == '__main__': unittest.main()

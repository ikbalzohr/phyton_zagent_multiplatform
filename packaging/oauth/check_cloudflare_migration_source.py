#!/usr/bin/env python3
"""Source-only guard; never imports the product or executes PowerShell."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packaging/scripts/Migrate-OwnerCloudflareMcp.ps1"


def main():
    assert SCRIPT.is_file(), "migration helper missing"
    source = SCRIPT.read_text(encoding="utf-8")
    required = (
        "[Parameter(Mandatory=$true)][string]$InstallRoot",
        "WindowsDashboard-Provisioning.ps1", "Assert-ZagentOwnerConsole",
        "Assert-ZagentOwnerAcl", "Assert-ZagentPlainPath", "Win32_Process",
        "--data-root", "--root", "Stop Core", "Overview", "NOT Stop all agents",
        "https://vmi3669591.contaboserver.net/mcp",
        "https://zagent.ikbalzohr.web.id/mcp",
        "https://vmi3669591.contaboserver.net/realms/zagent",
        "zagent-resource-server", "ZAGENT_OAUTH_INTROSPECTION_SECRET",
        "oauth-introspection.dpapi.json", "CurrentUser", "protected_payload",
        "workspace-local", "7338141d-ab55-4d78-a97e-35336f970fb5",
        "7c82db6b-f6f2-4072-bd38-7ed763aa45d3", "appBridge", "read-only",
        "1048576", "Duplicate JSON member", "depth -gt 64",
        "[IO.FileMode]::CreateNew", ".Flush($true)", "[IO.File]::Replace",
        "Concurrent configuration change", "Read-back mismatch",
        "CLOUDFLARE_RESOURCE_MIGRATED", "CLOUDFLARE_RESOURCE_ALREADY_CURRENT",
        "Assert-CoreStopped", "Assert-ReviewedMetadata", "Assert-SnapshotUnchanged",
        "[StringComparer]::OrdinalIgnoreCase", "$s.Nodes -gt 32768",
        "$s.Clock.Elapsed.TotalSeconds -gt 15", "[Text.UTF8Encoding]::new($false, $true)",
        "$occurrences.Count -ne 1", "$processes.Count -ne 1",
        "[Convert]::ToBase64String($backupBytes) -cne [Convert]::ToBase64String($before)",
        "Set-ZagentOwnerAcl $temp", "Assert-MigrationPrivatePath $backup",
    )
    for text in required:
        assert text in source, f"missing source contract: {text}"
    # Content-preserving lexical replacement, not whole-document JSON serialization.
    assert "ConvertTo-Json" not in source, "round-trip serialization can lose grant content"
    assert "$edits = @($parsed.ResourceUri, $parsed.PolicyRevision)" in source
    assert "$next = $next.Remove($edit.Start, $edit.Length).Insert($edit.Start, $replacement)" in source
    assert "[Convert]::ToBase64String($readback) -cne [Convert]::ToBase64String($bytes)" in source
    assert source.index("$null = Read-Host") < source.index("[IO.FileMode]::CreateNew")
    assert source.index("Assert-SnapshotUnchanged $target $before") < source.index("[IO.File]::Replace")
    assert 'function Assert-MigrationPrivatePath' in source, 'Generated config must accept owner-only inherited ACL under private DataRoot'
    assert '$rules[0].IdentityReference.Value -cne $owner.Value' in source
    assert 'Assert-ZagentOwnerAcl $credentialPath' in source
    assert 'function Read-BoundedBytes' in source
    forbidden = (
        r"(?i)ProtectedData|Unprotect\(|SetEnvironmentVariable|Invoke-Expression|Stop-Process",
        r"(?i)AddHours|ToUnixTimeSeconds|ActivateReadOnlyGrant|Start-Process|Invoke-WebRequest",
        r"(?im)^\s*\$\w+(?:\.\w+)*\.(?:revoked|expires_at|scopes|tools|grants)\s*=",
    )
    for pattern in forbidden:
        assert not re.search(pattern, source), f"forbidden operation: {pattern}"
    print("PASS: Cloudflare migration source contracts (PowerShell parser/runtime NOT_RUN)")


if __name__ == "__main__":
    main()

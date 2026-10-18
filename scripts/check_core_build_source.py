#!/usr/bin/env python3
"""Source-only regression checks; never builds, imports or executes Zagent.

This is a narrow textual guard, NOT a C# compiler or runtime test.
Run from any directory: python3 scripts/check_core_build_source.py
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/Zagent.Core"
SHARED = ROOT / "src/Zagent.Shared"
failures = []


def check(condition, label):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    if not condition:
        failures.append(label)


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def record_parameters(source, name):
    match = re.search(r"public sealed record " + name + r"\s*\((.*?)\)", source, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


host = read("src/Zagent.Core/Dashboard/DashboardHost.cs")
contracts = read("src/Zagent.Shared/Manager/ManagerContracts.cs")
control = read("src/Zagent.Core/Manager/ManagerControlService.cs")
files = read("src/Zagent.Core/Manager/FilesManagerReadModel.cs")
visual = read("src/Zagent.Core/Manager/ManagerVisualReadModel.cs")
check("Microsoft.AspNetCore.Http.StaticFiles" not in host,
      "DashboardHost has no invalid Http.StaticFiles import")
check("app.UseStaticFiles(new StaticFileOptions" in host,
      "static-file middleware retained")

# Exact neutral integration schema from the pre-migration baseline; no chat DTOs.
expected = {
    "ManagerIntegrationSnapshot": "string ChromeExtensionStatus, string ChromeNativeBridgeStatus, bool ChromeConnected, bool ChromeAuthorized, bool ChromeNativeAttached, bool ChromeProfileBound, string ChromeProfile, string ArcMapDesktopStatus, string ArcMapAddInStatus, string ArcMapToolsStatus, string ArcMapMcpStatus, string ArcMapBridgeStatus, string ArcMapCurrentMxdStatus, DateTimeOffset CapturedAtUtc",
    "ManagerIntegrationActionRequest": "string Action, string? ChromeProfile = null",
    "ManagerIntegrationActionResult": "bool Success, string Action, string Message, ManagerIntegrationSnapshot Snapshot",
}
for name, parameters in expected.items():
    check(record_parameters(contracts, name) == parameters, f"{name} neutral schema intact")
# Property accessors contain braces; inspect the record section up to the next declaration.
snapshot_section = contracts.split("public sealed record ManagerIntegrationSnapshot", 1)[-1].split("public sealed record ManagerIntegrationActionRequest", 1)[0]
for property_declaration in (
    "public bool ChromePersistentConsent { get; init; }",
    "public bool ChromeReconnectAvailable { get; init; }",
    "public int ChromeApprovedTabCount { get; init; }",
    "public IReadOnlyList<string> ChromeProfileOptions { get; init; } = Array.Empty<string>();",
):
    check(property_declaration in snapshot_section, property_declaration)

manager_source = "\n".join((control, files, contracts))
for legacy in ("ManagerSessionProfileSwitchRequest", "SwitchSessionProfileAsync", '"profiles.session_switch"'):
    check(legacy not in manager_source, f"legacy session profile path removed: {legacy}")
check('"files_session_switch"' not in files, "Files manager cannot dispatch legacy session mutation")
check('$"Unknown Manager method' in control, "unknown legacy methods fail closed")

# These two fallback constructors previously supplied 14 arguments to a 13-field DTO.
empty_arguments = "Available: false, Id: null, Source: null, Kind: null, Label: null, CapturedAtUtc: null, MimeType: null, Bytes: 0, DeviceId: null, DeviceName: null, WorkspaceId: null, Sha256: null, Error: "
for label, source, error in (
    ("control unavailable visual", control, '"Visual store unavailable."'),
    ("visual empty result", visual, "error"),
):
    normalized = re.sub(r"\s+", " ", source)
    check(empty_arguments + error in normalized, label + " matches current named DTO fields")

# Broad lexical audit catches missing Manager DTO names across Core and Shared.
source = "\n".join(p.read_text(encoding="utf-8") for root in (CORE, SHARED) for p in root.rglob("*.cs"))
# Include raw tokens (not a C# parser); ManagerControl is a log-source label.
declared = set(re.findall(r"\b(?:class|record|interface|enum|struct)\s+(Manager\w+)", source))
referenced = set(re.findall(r"\bManager\w+", source))
missing = sorted(referenced - declared - {"ManagerControl"})
check(not missing, "Manager type lexical audit: " + (", ".join(missing) if missing else "no undefined tokens"))
check('.RequireAuthorization("Operator").RequireRateLimiting("commands")' in host and
      'request.Action is not ("chrome.check" or "arcmap.check")' in host,
      "connection action allowlist and role/rate guards retained")
print("Source-only result: " + ("FAIL" if failures else "PASS") + "; Windows compilation and runtime remain unverified.")
sys.exit(1 if failures else 0)

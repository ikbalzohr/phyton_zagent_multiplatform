using System.Text.Json;
using Zagent.Core.Dashboard;
using System.Text.Json.Nodes;
using Zagent.Core.Manager;
using Zagent.Shared;
using Zagent.Shared.Installation;

// Source authored first; execution is explicitly deferred to Windows.
static void Check(bool ok, string name) { if (!ok) throw new Exception(name); }
var options = new DashboardOptions("https://localhost:19443", "certificate", "workspace-1", "admin", "hash", "revision");
options.Validate();
foreach (var url in new[] { "http://localhost:19443", "https://0.0.0.0:19443", "https://example.org:19443", "https://localhost:19443/path" })
{
    try { (options with { Url = url }).Validate(); throw new Exception("Accepted unsafe listener"); }
    catch (ArgumentException) { }
}
// RemoteEnabled must independently fail even with an otherwise valid local URL.
try { (options with { RemoteEnabled = true }).Validate(); throw new Exception("Accepted remote management"); }
catch (ArgumentException) { }
Check(DashboardSecurity.IsSameOrigin("https://localhost:19443", options.Origin), "exact origin");
foreach (var origin in new[] { "null", "https://evil.example", "https://localhost:19444", "http://localhost:19443", "https://localhost:19443.evil.example" })
    Check(!DashboardSecurity.IsSameOrigin(origin, options.Origin), "reject origin " + origin);
Check(!DashboardSecurity.IsSameOrigin(null, options.Origin), "missing Origin rejected");
Environment.SetEnvironmentVariable("ZAGENT_INTERNAL_TOKEN", new string('k', 32));
Environment.SetEnvironmentVariable("ZAGENT_INTERNAL_CONTEXT_KEY", new string('s', 32));
Environment.SetEnvironmentVariable("ZAGENT_DEFAULT_WORKSPACE_ID", "workspace-1");
InternalManagementChannel.ValidateProvisioning();
Check(InternalManagementChannel.Canonicalize(JsonNode.Parse("{\"b\":2,\"a\":[true,null,1]}")) == "{\"a\":[true,null,1],\"b\":2}", "canonical JSON contract");
var profilesSnapshot = JsonElement.Parse("""
    {"profiles":[],"pendingApprovals":[],"defaultProfile":"workspace-1","capturedAtUtc":"2026-01-01T00:00:00Z"}
    """);
var revision = DashboardRevision.Profiles(profilesSnapshot);
Check(!string.IsNullOrEmpty(revision), "snapshot revision available");
Check(revision == DashboardRevision.Profiles(profilesSnapshot), "snapshot revision deterministic");
var changedDefault = JsonElement.Parse("""
    {"profiles":[],"pendingApprovals":[],"defaultProfile":"workspace-2"}
    """);
Check(revision != DashboardRevision.Profiles(changedDefault), "default profile mutation changes revision");
var changedProfiles = JsonElement.Parse("""
    {"profiles":[{"name":"workspace-1","mode":"read-only"}],"pendingApprovals":[],"defaultProfile":"workspace-1"}
    """);
Check(revision != DashboardRevision.Profiles(changedProfiles), "profile mutation changes revision");
var changedApprovals = JsonElement.Parse("""
    {"profiles":[],"pendingApprovals":[{"requestId":"approval-1","status":"pending"}],"defaultProfile":"workspace-1"}
    """);
Check(revision != DashboardRevision.Profiles(changedApprovals), "approval mutation changes revision");
var changedCaptureTime = JsonElement.Parse("""
    {"profiles":[],"pendingApprovals":[],"defaultProfile":"workspace-1","capturedAtUtc":"2026-01-02T00:00:00Z"}
    """);
Check(revision == DashboardRevision.Profiles(changedCaptureTime), "capture timestamp does not change revision");
try {
    DashboardRevision.Profiles(JsonElement.Parse("{}"));
    throw new Exception("Accepted incomplete profile snapshot");
}
catch (KeyNotFoundException) { }
Check(!DashboardSecurity.IsExpectedHost("evil.example:19443", options.Origin), "DNS rebinding rejected");
Check(DashboardSecurity.IsExpectedHost("localhost:19443", options.Origin), "configured Host");
Check(DashboardSecurity.Redact("Authorization: Bearer token12345 token=secret api_key=hidden").Contains("secret") == false, "redaction");
Check(!ZagentProductInfo.CoreVersion.StartsWith("0.", StringComparison.Ordinal), "Core1 product version");
Check(ZagentProductInfo.UiVersion == "1.0.0", "UI1 product version");
Check(ZagentInstallationProfile.Normalize("primary") == ZagentInstallationProfile.Primary, "neutral primary slot");
Check(ZagentInstallationProfile.Normalize("secondary") == ZagentInstallationProfile.Secondary, "neutral secondary slot");
var shutdown = new CoreShutdownCoordinator();
var called = 0;
shutdown.ShutdownRequested += (_, _) => Interlocked.Increment(ref called);
Parallel.For(0, 20, _ => shutdown.Request());
Check(called == 1 && shutdown.IsRequested, "shutdown once across adapters");
var gate = new CoreCommandGate();
var running = 0; var peak = 0;
await Task.WhenAll(Enumerable.Range(0, 10).Select(async _ => {
    await using var lease = await gate.EnterAsync();
    peak = Math.Max(peak, Interlocked.Increment(ref running));
    await Task.Delay(1); Interlocked.Decrement(ref running);
}));
Check(peak == 1, "cross-adapter commands serialized");
await using (var lease = await gate.EnterAsync()) gate.BeginShutdown();
try { await gate.EnterAsync(); throw new Exception("command after shutdown accepted"); }
catch (InvalidOperationException) { }
Console.WriteLine("Dashboard policy/coordinator/security source tests complete.");

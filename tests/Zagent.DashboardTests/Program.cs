using System.Text.Json;
using Zagent.Core.Dashboard;
using System.Text.Json.Nodes;
using Zagent.Core.Manager;
using Zagent.Shared;
using Zagent.Shared.Installation;
using Zagent.Shared.Manager;

// Source authored first; execution is explicitly deferred to Windows.
static void Check(bool ok, string name) { if (!ok) throw new Exception(name); }
var options = new DashboardOptions("https://localhost:19443", "certificate", "workspace-1", "admin", "hash", "revision");
options.Validate();
// The authenticated Windows owner sees the Dashboard without a browser login.
// No PasswordHash is necessary; enrollment stamp and HTTPS boundary still are.
(options with { PasswordHash = "" }).Validate();
try { (options with { SecurityStamp = "" }).Validate(); throw new Exception("Accepted missing local owner enrollment stamp"); }
catch (ArgumentException) { }
var chromeFixtureRoot = Path.Combine(Path.GetTempPath(), "Zagent-ChromeFixture-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(chromeFixtureRoot);
try
{
    var chrome = Path.Combine(chromeFixtureRoot, "chrome.exe");
    File.WriteAllBytes(chrome, []);
    var chromeStart = DashboardChromeBrowser.BuildStartInfo(chrome, new Uri("https://localhost:19444/"));
    Check(chromeStart.FileName == chrome && !chromeStart.UseShellExecute,
        "local dashboard opens explicit Chrome executable");
    Check(chromeStart.ArgumentList.SequenceEqual(new[] { "--new-tab", "https://localhost:19444/" }),
        "Chrome receives exact localhost tab URL without login data");
    try { DashboardChromeBrowser.BuildStartInfo(chrome, new Uri("https://example.com/")); throw new Exception("Accepted remote Dashboard"); }
    catch (ArgumentException) { }
    try { DashboardChromeBrowser.BuildStartInfo(chrome, new Uri("http://localhost:19444/")); throw new Exception("Accepted plaintext Dashboard"); }
    catch (ArgumentException) { }
}
finally { Directory.Delete(chromeFixtureRoot, true); }
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
// Ambient env is not authority; persisted startup provisioning is required.
try { InternalManagementChannel.ValidateProvisioning(); throw new Exception("Accepted unprovisioned channel"); }
catch (InvalidOperationException) { }
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
Check(ZagentInstanceScope.Key(@"C:\Zagent") == ZagentInstanceScope.Key(@"c:\zagent"), "instance scope path canonicalization");
Check(ZagentInstanceScope.PipeName(@"C:\Zagent") != ZagentInstanceScope.PipeName(@"C:\OtherZagent"), "distinct instance pipe");
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
var offlineProfiles = new ManagerProfilesSnapshot(
    [new ManagerProfileRow("appBridge", @"D:\Zagent Multi Platform\workspace",
        "read-only", true, true, true, "zagent_install", "disabled"),
     new ManagerProfileRow("agent-dev", @"D:\Zagent Multi Platform\project",
        "read-write", true, false, true, "oauth_owner_admin", "full"),
     new ManagerProfileRow("legacy", @"D:\Zagent Multi Platform\old",
        "read-write", true, false, true, "zagent_install")],
    [], [], "appBridge", DateTimeOffset.UtcNow);
var offlineInventoryJson = JsonSerializer.SerializeToElement(
    DashboardProfileAdministration.BuildLocalProfileInventory(offlineProfiles));
var offlineInventory = offlineInventoryJson.GetProperty("data");
Check(offlineInventory.GetProperty("source").GetString() == "local-config-read-only",
    "Fallback must be explicitly labeled read-only local config.");
Check(offlineInventory.GetProperty("administrativeAccess").GetBoolean() == false,
    "Display-only profile inventory must never grant administration.");
Check(offlineInventory.GetProperty("defaultProfile").GetString() == "appBridge",
    "Default profile must come from installed local configuration.");
Check(offlineInventory.GetProperty("profiles")[0].GetProperty("root").GetString() ==
    @"D:\Zagent Multi Platform\workspace", "Offline profile root is preserved.");
Check(offlineInventory.GetProperty("profiles")[0].GetProperty("execution_access").GetString() == "disabled",
    "Offline inventory displays Disabled without changing file access.");
Check(offlineInventory.GetProperty("profiles")[1].GetProperty("execution_access").GetString() == "full",
    "Offline inventory displays explicit Full mode.");
Check(offlineInventory.GetProperty("profiles")[2].GetProperty("execution_access").GetString() == "legacy",
    "Missing execution mode must remain labeled Legacy, not silently inferred Disabled.");
var localProfileFixture = Path.Combine(Path.GetTempPath(),
    "zagent-execution-inventory-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(Path.Combine(localProfileFixture, "config"));
try
{
    File.WriteAllText(Path.Combine(localProfileFixture, "config", "profiles.json"), """
        {"schema_version":"2.0","active_profile":"appBridge","profiles":[
          {"name":"appBridge","root":"D:\\fixture\\read","mode":"read-only",
            "enabled":true,"authorized_by_user":true,"execution_access":"disabled"},
          {"name":"agent-dev","root":"D:\\fixture\\dev","mode":"read-write",
            "enabled":true,"authorized_by_user":true,"execution_access":"full"},
          {"name":"legacy","root":"D:\\fixture\\legacy","mode":"read-write",
            "enabled":true,"authorized_by_user":true}]}
        """);
    var readModel = new FilesManagerReadModel(new Uri("http://127.0.0.1:19120/mcp"),
        new FilesLocalApprovalOptions("unused", "unused", new Dictionary<string, string> {
            ["ZAGENT_FILES_CONFIG_DIR"] = Path.Combine(localProfileFixture, "config"),
            ["ZAGENT_FILES_DATA_ROOT"] = localProfileFixture
        }));
    var loaded = await readModel.GetProfilesAsync(includeWorkspace: false);
    Check(loaded.Profiles.Select(p => p.ExecutionAccess)
        .SequenceEqual(new[] { "disabled", "full", "legacy" }),
        "Core local profile reader preserves explicit execution modes and legacy absence.");
}
finally { Directory.Delete(localProfileFixture, true); }
Console.WriteLine("Dashboard policy/coordinator/security/source and read-only profile inventory tests complete.");

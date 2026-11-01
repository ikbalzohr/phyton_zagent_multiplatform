using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Reflection;
using Zagent.Core.Dashboard;
using Zagent.Core.Manager;

// Windows-only, fixture credentials only. Does not launch Core or any agent.
if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows acceptance is required; no substitute PASS.");
var parent = Environment.GetEnvironmentVariable("ZAGENT_ACCEPTANCE_ROOT")
    ?? throw new InvalidOperationException("Set ZAGENT_ACCEPTANCE_ROOT to an approved disposable directory outside the source/install tree.");
if (!Path.IsPathFullyQualified(parent) || !Directory.Exists(parent))
    throw new InvalidOperationException("Acceptance root must be an existing absolute directory.");
var sourceRoot = Environment.GetEnvironmentVariable("ZAGENT_ACCEPTANCE_SOURCE_ROOT")
    ?? throw new InvalidOperationException("Set ZAGENT_ACCEPTANCE_SOURCE_ROOT to the repository root.");
var parentFull = Path.GetFullPath(parent).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
var sourceFull = Path.GetFullPath(sourceRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
if (parentFull.StartsWith(sourceFull, StringComparison.OrdinalIgnoreCase))
    throw new InvalidOperationException("Acceptance fixture root must be outside source tree.");
var root = Path.Combine(parent, "core-acceptance-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
var names = new[] { "ZAGENT_INTERNAL_TOKEN", "ZAGENT_INTERNAL_CONTEXT_KEY", "ZAGENT_DEFAULT_WORKSPACE_ID" };
var saved = names.ToDictionary(n => n, n => Environment.GetEnvironmentVariable(n));
var passed = 0;
void Check(bool condition, string label) { if (!condition) throw new Exception(label); passed++; Console.WriteLine("PASS " + label); }
void Reject<T>(Action action, string label) where T : Exception {
    try { action(); } catch (T) { passed++; Console.WriteLine("PASS " + label); return; }
    throw new Exception("Accepted invalid input: " + label);
}
try {
    Environment.SetEnvironmentVariable(names[0], new string('k', 64));
    Environment.SetEnvironmentVariable(names[1], new string('s', 64));
    Environment.SetEnvironmentVariable(names[2], "acceptance-workspace");
    Reject<InvalidOperationException>(InternalManagementChannel.ValidateProvisioning, "ambient environment is not provisioning authority");
    var configure = typeof(InternalManagementChannel).GetMethod("Configure", BindingFlags.Static | BindingFlags.NonPublic)
        ?? throw new Exception("Core Configure seam missing");
    void Configure(string token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", string workspace = "acceptance-workspace") {
        try { configure.Invoke(null, new object[] { token, new string('b', 64), workspace, "fixture-device", "fixture-installation", root }); }
        catch (TargetInvocationException ex) when (ex.InnerException is not null) {
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(ex.InnerException).Throw(); throw;
        }
    }
    Reject<InvalidOperationException>(() => Configure(token: ""), "empty private token rejected");
    Reject<InvalidOperationException>(() => Configure(token: new string(' ', 64)), "whitespace private token rejected");
    Reject<InvalidOperationException>(() => Configure(workspace: ""), "missing installation workspace rejected");
    Configure();
    InternalManagementChannel.ValidateProvisioning();
    Check(InternalManagementChannel.GetChildSecret("ZAGENT_INTERNAL_TOKEN") == new string('a', 64), "child gets provisioned token not ambient token");
    // Capture the actual production handler output without binding a port or sending HTTP.
    var handlerType = typeof(InternalManagementChannel).GetNestedType("ManagementHandler", BindingFlags.NonPublic)
        ?? throw new Exception("Management handler seam missing");
    var handler = (DelegatingHandler)Activator.CreateInstance(handlerType, nonPublic: true)!;
    var capture = new CaptureHandler(); handler.InnerHandler = capture;
    using var client = new HttpClient(handler);
    async Task Call(string tool, string arguments = "{}", string endpoint = "http://127.0.0.3:18820/mcp") {
        using var request = new HttpRequestMessage(HttpMethod.Post, endpoint) {
            Content = new StringContent("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"" + tool + "\",\"arguments\":" + arguments + "}}", Encoding.UTF8, "application/json") };
        using var response = await client.SendAsync(request);
        response.EnsureSuccessStatusCode();
    }
    async Task RejectCall(string tool, string label, string endpoint = "http://127.0.0.3:18820/mcp") {
        var before = capture.Calls;
        try { await Call(tool, endpoint: endpoint); } catch (InvalidOperationException) {
            Check(capture.Calls == before, label); return;
        }
        throw new Exception("Accepted forbidden channel call: " + label);
    }
    var profilePath = Path.Combine(root, "profiles.json");
    await File.WriteAllTextAsync(profilePath, "{\"active_profile\":\"approved-fixture\",\"profiles\":[{\"name\":\"approved-fixture\",\"enabled\":true,\"authorized_by_user\":true,\"mode\":\"read-only\"}]}");
    var beforeCall = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
    await Call("files_workspace_list", "{\"profile_id\":\"client-does-not-grant-authority\"}");
    var context = JsonNode.Parse(capture.Body!)!["params"]!["_meta"]!["zagent.execution_context"]!;
    Check(context["deadline"]!.GetValue<long>() > beforeCall && context["deadline"]!.GetValue<long>() <= beforeCall + 301 && context["expires_at"] is null, "consumer deadline shape and bounded effect window");
    Check(context["workspace_id"]!.GetValue<string>() == "acceptance-workspace" && context["device_id"]!.GetValue<string>() == "fixture-device" && context["installation_id"]!.GetValue<string>() == "fixture-installation", "context uses configured placement and workspace");
    Check(context["effective_access"]!.GetValue<string>() == "read", "read-only management does not mint write access");
    var resources = context["effective_resources"]!.AsArray();
    Check(resources.Count == 1 && resources[0]!["kind"]!.GetValue<string>() == "files" && resources[0]!["profile_id"]!.GetValue<string>() == "approved-fixture", "profile comes from approved local active state, not caller selector");
    Check(capture.Token == new string('a', 64), "authenticated child channel uses provisioned token");
    await File.WriteAllTextAsync(profilePath, "{\"active_profile\":\"approved-fixture\",\"profiles\":[{\"name\":\"approved-fixture\",\"enabled\":false,\"authorized_by_user\":true,\"mode\":\"read-only\"}]}");
    await RejectCall("files_workspace_list", "disabled profile rejected before dispatch");
    await File.WriteAllTextAsync(profilePath, "{\"profiles\":[]}");
    await RejectCall("files_workspace_list", "missing active approved profile has no fallback");
    await RejectCall("files_exec_command", "arbitrary shell absent from management allowlist");
    await RejectCall("files_workspace_list", "nonloopback channel rejected", "http://192.0.2.1:18820/mcp");
    var options = new DashboardOptions("https://localhost:19443/", "0000000000000000000000000000000000000000", "acceptance-workspace", "fixture-admin", "fixture-not-a-login-hash", "fixture-stamp");
    options.Validate();
    Reject<ArgumentException>(() => (options with { RemoteEnabled = true }).Validate(), "remote dashboard disabled");
    (options with { PasswordHash = "" }).Validate(); // Windows owner scheme does not require a browser password.
    Reject<ArgumentException>(() => (options with { SecurityStamp = "" }).Validate(), "missing enrollment stamp rejected");
    Reject<FileNotFoundException>(() => DashboardOptions.Load(Path.Combine(root, "missing-dashboard.json")), "missing dashboard config rejected");
    Reject<InvalidOperationException>(() => { using var cert = options.LoadCertificate(); }, "absent CurrentUser TLS certificate rejected");
    Check(!DashboardSecurity.IsSameOrigin(null, options.Origin), "missing mutating origin rejected");
    Check(!DashboardSecurity.IsSameOrigin("https://localhost:19444", options.Origin), "different origin port rejected");
    Check(!DashboardSecurity.IsExpectedHost("localhost:19443.evil.example", options.Origin), "rebinding host rejected");

    var path = Path.Combine(root, "transport.credentials.json");
    var store = new TunnelCredentialStore(path);
    Check(await store.LoadAsync() is null, "missing transport credentials are not configured");
    // These synthetic values are test fixtures, NEVER a bearer or authorization server.
    var credential = new TunnelCredentials("acceptance-fixture", "fixture-only-not-valid-for-service-" + Guid.NewGuid().ToString("N"));
    await store.SaveAsync(credential);
    Check(await store.LoadAsync() == credential, "CurrentUser DPAPI transport roundtrip");
    var envelope = await File.ReadAllTextAsync(path);
    Check(!envelope.Contains(credential.ApiKey, StringComparison.Ordinal), "transport secret is not plaintext on disk");
    using (var document = JsonDocument.Parse(envelope))
        Check(document.RootElement.GetProperty("protection").GetString() == "Windows DPAPI CurrentUser", "transport DPAPI scope declaration");
    await File.WriteAllTextAsync(path, "{\"protected_payload\":\"not-base64!\"}");
    try { await store.LoadAsync(); throw new Exception("Malformed envelope accepted"); }
    catch (FormatException) { passed++; Console.WriteLine("PASS malformed transport ciphertext rejected"); }
    // Exact packaging->Core envelope, under disposable owner-only ACLs.
    var sid = WindowsIdentity.GetCurrent().User!;
    void PrivateDirectory(string directory) {
        Directory.CreateDirectory(directory);
        var acl = new DirectorySecurity(); acl.SetOwner(sid); acl.SetAccessRuleProtection(true, false);
        acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
            InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        new DirectoryInfo(directory).SetAccessControl(acl);
    }
    PrivateDirectory(root);
    var config = Path.Combine(root, "config"); PrivateDirectory(config);
    var secretPath = Path.Combine(config, InternalSecretStore.FileName);
    void WriteEnvelope(string json) {
        File.WriteAllText(secretPath, json);
        var acl = new FileSecurity(); acl.SetOwner(sid); acl.SetAccessRuleProtection(true, false);
        acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, AccessControlType.Allow));
        new FileInfo(secretPath).SetAccessControl(acl);
    }
    // Uses Core's DPAPI primitive only to construct fixture ciphertext; loader is the behavior under test.
    var crypt = typeof(TunnelCredentialStore).GetMethod("Crypt", BindingFlags.Static | BindingFlags.NonPublic)
        ?? throw new Exception("DPAPI fixture primitive missing");
    string Envelope(string plaintext) {
        var clear = System.Text.Encoding.UTF8.GetBytes(plaintext);
        try {
            var cipher = (byte[])crypt.Invoke(null, new object[] { clear, true })!;
            return JsonSerializer.Serialize(new { version = 1, scope = "CurrentUser", protected_payload = Convert.ToBase64String(cipher) });
        } finally { Array.Clear(clear); }
    }
    var fixtureToken = new string('a', 64); var fixtureKey = new string('b', 64);
    var validEnvelope = Envelope(JsonSerializer.Serialize(new { internal_token = fixtureToken, internal_context_key = fixtureKey }));
    WriteEnvelope(validEnvelope);
    var loaded = InternalSecretStore.Load(root);
    Check(loaded.Token == fixtureToken && loaded.ContextKey == fixtureKey, "exact internal DPAPI envelope accepted under owner ACL");
    WriteEnvelope("{\"version\":1,\"scope\":\"LocalMachine\",\"protected_payload\":\"AA==\"}");
    Reject<InvalidDataException>(() => InternalSecretStore.Load(root), "wrong DPAPI scope rejected");
    WriteEnvelope("{\"version\":1,\"scope\":\"CurrentUser\",\"protected_payload\":\"AA==\"}");
    Reject<InvalidDataException>(() => InternalSecretStore.Load(root), "invalid DPAPI ciphertext rejected");
    WriteEnvelope(Envelope(JsonSerializer.Serialize(new { internal_token = fixtureToken, internal_context_key = fixtureToken })));
    Reject<InvalidDataException>(() => InternalSecretStore.Load(root), "identical internal keys rejected");
    WriteEnvelope(Envelope(JsonSerializer.Serialize(new { internal_token = fixtureToken, internal_context_key = fixtureKey, extra = "reject" })));
    Reject<InvalidDataException>(() => InternalSecretStore.Load(root), "unexpected internal payload key rejected");
    WriteEnvelope(validEnvelope);
    var broad = new FileInfo(secretPath).GetAccessControl();
    broad.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(WellKnownSidType.BuiltinUsersSid, null), FileSystemRights.Read, AccessControlType.Allow));
    new FileInfo(secretPath).SetAccessControl(broad);
    Reject<InvalidDataException>(() => InternalSecretStore.Load(root), "non-owner secret ACL rejected");
    WriteEnvelope(validEnvelope);
    File.Delete(secretPath);
    try { InternalSecretStore.Load(root); throw new Exception("Missing persisted secret accepted ambient environment"); }
    catch (FileNotFoundException) { passed++; Console.WriteLine("PASS missing persisted secret rejected despite ambient fixtures"); }
    // Preparing config must not reenable consent or replace the approved root/mode.
    var integrationRoot = Path.Combine(root, "writer-fixture"); Directory.CreateDirectory(integrationRoot);
    var pythonFixture = Path.Combine(integrationRoot, "not-executable-python.fixture");
    await File.WriteAllTextAsync(pythonFixture, "existence-only fixture, never executed");
    var writerConfig = Path.Combine(integrationRoot, "config"); Directory.CreateDirectory(writerConfig);
    var existingProfiles = "{\"schema_version\":\"2.0\",\"active_profile\":\"approved-fixture\",\"profiles\":[{\"name\":\"approved-fixture\",\"root\":\"C:\\\\owner-approved-only\",\"mode\":\"read-only\",\"enabled\":false,\"authorized_by_user\":false}]}";
    var writerProfiles = Path.Combine(writerConfig, "profiles.json");
    await File.WriteAllTextAsync(writerProfiles, existingProfiles);
    var proposedRoot = Path.Combine(integrationRoot, "not-approved-new-root");
    var writerOptions = new Zagent.Core.Agents.Files.FilesIntegrationOptions(
        PythonExecutable: pythonFixture, EngineRoot: integrationRoot, DataRoot: integrationRoot,
        ConfigRoot: writerConfig, RuntimeRoot: Path.Combine(integrationRoot, "runtime"),
        LogRoot: Path.Combine(integrationRoot, "logs"), BackupRoot: Path.Combine(integrationRoot, "backup"),
        UpdateStateRoot: Path.Combine(integrationRoot, "updates"), BindHost: "127.0.0.3", Port: 18820,
        DefaultProfileName: "approved-fixture", DefaultProfileRoot: proposedRoot, DefaultProfileMode: "read-write");
    await new Zagent.Core.Agents.Files.FilesConfigurationWriter().WriteAsync(writerOptions);
    Check(await File.ReadAllTextAsync(writerProfiles) == existingProfiles, "prepare preserves revoked/disabled/root/mode profile bytes");
    Check(!Directory.Exists(proposedRoot), "prepare does not create replacement root when profiles already exist");
    Console.WriteLine($"CORE_ACCEPTANCE_PASS assertions={passed}; NO MCP/auth/network readiness claim");
    return 0;
} finally {
    foreach (var entry in saved) Environment.SetEnvironmentVariable(entry.Key, entry.Value);
    Directory.Delete(root, recursive: true); // Only this uniquely-created fixture subtree.
}

sealed class CaptureHandler : HttpMessageHandler {
    public string? Body { get; private set; }
    public string? Token { get; private set; }
    public int Calls { get; private set; }
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) {
        Calls++;
        Body = await request.Content!.ReadAsStringAsync(cancellationToken);
        Token = request.Headers.GetValues("X-Zagent-Internal-Token").Single();
        return new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent("{}") };
    }
}

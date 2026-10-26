using System.Net;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Zagent.Core.Manager;

if (!OperatingSystem.IsWindows()) { Console.Error.WriteLine("WINDOWS_ONLY; NOT_RUN"); return 2; }
if (args.Length < 1) { Console.Error.WriteLine("Pass tests/contracts/profile-admin-wire-v1.json and optional emitted wire path."); return 2; }
void Assert(bool value, string label) { if (!value) throw new Exception(label); }
void Denies(Action action, string label) { try { action(); } catch (Exception e) when (e is InvalidDataException or InvalidOperationException or KeyNotFoundException or ArgumentException) { return; } throw new Exception("Did not deny: " + label); }
var fixture = JsonNode.Parse(File.ReadAllText(args[0]))!.AsObject();
var arguments = fixture["arguments"]!.AsObject();
Assert(InternalManagementChannel.Canonicalize(arguments) == fixture["canonical"]!.GetValue<string>(), "canonical UTF8 compact/sorted/Unicode parity");
Assert(ProfileAdministrationClient.PayloadDigest(arguments) == fixture["sha256"]!.GetValue<string>(), "SHA256 literal contract parity");
var policies = new JsonObject(); var tools = new JsonArray();
foreach (var action in ProfileAdministrationClient.Actions) { var tool = "files_profile_admin_"+action; tools.Add(tool); policies[tool] = new JsonObject { ["scope"] = action is "list" or "get" ? "files:read" : "files:write" }; }
var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
var config = new JsonObject { ["resource_server"] = new JsonObject { ["workspace_id"]="fixture-workspace", ["grants"] = new JsonObject {
    ["fixture-principal"] = new JsonObject { ["revoked"]=false, ["expires_at"]=now+3600,
        ["scopes"]=new JsonArray("files:read","files:write"), ["tools"]=tools,
        ["profile_management"] = new JsonObject { ["version"]=1, ["enabled"]=true, ["workspace_id"]="fixture-workspace",
            ["device_id"]="fixture-device", ["installation_id"]="fixture-installation", ["actions"]=new JsonArray(ProfileAdministrationClient.Actions.Select(x => (JsonNode?)JsonValue.Create(x)).ToArray()) },
        ["files_resource"] = new JsonObject { ["kind"]="files", ["revoked"]=false, ["resource_id"]="fixture-resource", ["profile_id"]="_-fixture",
            ["allowed_profile_ids"]=new JsonArray("_-fixture"), ["device_id"]="fixture-device", ["installation_id"]="fixture-installation" }
    } } }, ["tool_policy"]=policies };
OwnerProfileAdministrationBinding Parse(JsonObject value) { using var doc = JsonDocument.Parse(value.ToJsonString()); return OwnerProfileAdministrationBinding.Parse(doc.RootElement,"fixture-workspace","fixture-device","fixture-installation",now); }
var binding = Parse(config);
foreach (var path in new[] { "revoked", "expires_at", "profile_management", "scopes" }) {
    var broken = (JsonObject)config.DeepClone(); var grant = broken["resource_server"]!["grants"]!["fixture-principal"]!;
    grant[path] = path switch { "revoked" => JsonValue.Create(true), "expires_at" => JsonValue.Create(now), "scopes" => new JsonArray("files:write"), _ => null };
    Denies(() => Parse(broken), path);
}
var ambiguous = (JsonObject)config.DeepClone();
ambiguous["resource_server"]!["grants"]!["other"] = ambiguous["resource_server"]!["grants"]!["fixture-principal"]!.DeepClone();
Denies(() => Parse(ambiguous), "ambiguous owner");
var mismatched = (JsonObject)config.DeepClone(); mismatched["resource_server"]!["grants"]!["fixture-principal"]!["profile_management"]!["device_id"]="other";
Denies(() => Parse(mismatched), "placement");
Denies(() => new ProfileAdministrationClient(new Uri("http://example.test/mcp"),()=>binding), "public endpoint");
// Fixture-only private channel provisioning. No enrollment/credential files are read or written.
typeof(InternalManagementChannel).GetMethod("Configure", BindingFlags.Static|BindingFlags.NonPublic)!.Invoke(null,
    [new string('a',64),new string('b',64),"fixture-workspace","fixture-device","fixture-installation",Path.Combine(Environment.CurrentDirectory,"fixture","files","config")]);
var fixtureCoreRoot = Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "fixture"));
var fixtureFilesRoot = Path.Combine(fixtureCoreRoot, "files");
var processOptions = new Zagent.Core.Agents.Files.FilesIntegrationOptions(
    PythonExecutable: Path.Combine(fixtureCoreRoot, "python.exe"), EngineRoot: fixtureCoreRoot,
    DataRoot: fixtureFilesRoot, ConfigRoot: Path.Combine(fixtureFilesRoot, "config"),
    RuntimeRoot: Path.Combine(fixtureFilesRoot, "runtime"), LogRoot: Path.Combine(fixtureFilesRoot, "logs"),
    BackupRoot: Path.Combine(fixtureFilesRoot, "backups"), UpdateStateRoot: Path.Combine(fixtureFilesRoot, "updates"),
    BindHost: "127.0.0.1", Port: 18811, DefaultProfileName: "_-fixture", DefaultProfileRoot: fixtureCoreRoot,
    DeviceId: "fixture-device", InstallationId: "fixture-installation", CoreDataRoot: fixtureCoreRoot);
// Inspect the real launch definition only; never launch Python or read a credential store.
var definition = Zagent.Core.Agents.Files.FilesProcessFactory.Create(processOptions);
Assert(definition.EnvironmentVariables!["ZAGENT_CORE_DATA_ROOT"] == fixtureCoreRoot, "private Core root propagated");
Assert(definition.EnvironmentVariables["ZAGENT_INSTALLATION_ID"] == "fixture-installation", "trusted installation propagated");
var legacyDefinition = Zagent.Core.Agents.Files.FilesProcessFactory.Create(processOptions with { CoreDataRoot = "", InstallationId = "" });
Assert(legacyDefinition.EnvironmentVariables!["ZAGENT_CORE_DATA_ROOT"] == "" && legacyDefinition.EnvironmentVariables["ZAGENT_INSTALLATION_ID"] == "", "legacy caller cannot inherit admin placement");
Denies(() => Zagent.Core.Agents.Files.FilesProcessFactory.Create(processOptions with { CoreDataRoot = "relative" }), "relative Core root");
var handler = new CaptureHandler(); var reads = 0;
using (var client = new ProfileAdministrationClient(new Uri("http://127.0.0.1:18811/mcp"),()=>{reads++; return binding;},handler)) {
    var outcome = await client.AdminAsync("create",arguments,"dashboard-session-actor",CancellationToken.None);
    Assert(outcome["status"]!.GetValue<string>()=="committed", "terminal domain outcome");
    var wire = JsonNode.Parse(handler.Body!)!.AsObject(); var parameters = wire["params"]!;
    var context = parameters["_meta"]!["zagent.profile_admin_context"]!;
    Assert(context["actor_id"]!.GetValue<string>()=="dashboard-session-actor", "session actor not rewritten");
    Assert(context["principal_id"]!.GetValue<string>()=="fixture-principal", "configured OAuth owner mapping");
    Assert(context["deadline"]!.GetValue<long>()<=binding.ExpiresAt, "finite grant deadline");
    Assert(parameters["_meta"]!["zagent.execution_context"] is null, "not native context");
    Assert(context["payload_digest"]!.GetValue<string>()==fixture["sha256"]!.GetValue<string>(), "real serializer digest");
    if (args.Length > 1) File.WriteAllText(args[1],handler.Body!,new UTF8Encoding(false));
    await client.CatalogAsync("dashboard-session-actor",CancellationToken.None);
    var catalogWire = JsonNode.Parse(handler.Body!)!;
    Assert(catalogWire["params"]!["_meta"]!["zagent.profile_catalog_context"]!.AsObject().Count==8,"exact catalog envelope");
    Assert(reads==2,"binding revalidated every call");
}
Denies(() => ProfileAdministrationClient.DecodeResponse(Encoding.UTF8.GetBytes("{\"result\":{\"revision\":\"bad\"}}")), "missing valid revision");
Denies(() => ProfileAdministrationClient.DecodeResponse(Encoding.UTF8.GetBytes("{\"result\":{\"revision\":\"a\",\"revision\":\"b\"}}")), "duplicate response keys");
Console.WriteLine("PASS profile-admin C# serializer/binding/response fixture; live dashboard/backend activation NOT_APPLIED");
return 0;
sealed class CaptureHandler : HttpMessageHandler {
    public string? Body;
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken token) {
        if (request.Headers.GetValues("X-Zagent-Internal-Token").Single()!=new string('a',64)) throw new Exception("private token header");
        Body=await request.Content!.ReadAsStringAsync(token);
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(new JsonObject {
            ["jsonrpc"]="2.0", ["result"]=new JsonObject { ["structuredContent"]=new JsonObject { ["revision"]=new string('c',64), ["status"]="committed", ["access_sync"]="committed", ["profiles"]=new JsonArray() } }
        }.ToJsonString(), Encoding.UTF8,"application/json") };
    }
}

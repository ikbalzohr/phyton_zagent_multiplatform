using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Zagent.Core.Agents.ArcMap;
using Zagent.Core.Agents.Files;
using Zagent.Core.Agents.Tunnel;
using Zagent.Core.Agents.Web;
using Zagent.Core.Registry;
using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;

var devRoot = Environment.GetEnvironmentVariable("ZAGENT_DEV_ROOT")
    ?? throw new InvalidOperationException("ZAGENT_DEV_ROOT is not set.");
var filesPython = Environment.GetEnvironmentVariable("ZAGENT_FILES_TEST_PYTHON")
    ?? throw new InvalidOperationException("ZAGENT_FILES_TEST_PYTHON is not set.");
var tunnelPython = Environment.GetEnvironmentVariable("ZAGENT_TUNNEL_TEST_PYTHON")
    ?? throw new InvalidOperationException("ZAGENT_TUNNEL_TEST_PYTHON is not set.");
var node = Environment.GetEnvironmentVariable("ZAGENT_WEB_TEST_NODE")
    ?? throw new InvalidOperationException("ZAGENT_WEB_TEST_NODE is not set.");
var arcMapPython = Environment.GetEnvironmentVariable("ZAGENT_ARCMAP_TEST_PYTHON")
    ?? throw new InvalidOperationException("ZAGENT_ARCMAP_TEST_PYTHON is not set.");

var validationRoot = Path.Combine(
    devRoot,
    "_validation",
    "phase7-tunnel-files-web-arcmap");

if (Directory.Exists(validationRoot))
{
    Directory.Delete(validationRoot, recursive: true);
}
Directory.CreateDirectory(validationRoot);

var used = new List<int>();
var filesPort = FreePort(used); used.Add(filesPort);
var webPort = FreePort(used); used.Add(webPort);
var arcMapPort = FreePort(used); used.Add(arcMapPort);
var tunnelPort = FreePort(used); used.Add(tunnelPort);

var filesOptions = new FilesIntegrationOptions(
    PythonExecutable: filesPython,
    EngineRoot: Path.Combine(devRoot, "agents", "files", "engine"),
    DataRoot: Path.Combine(validationRoot, "files-data"),
    ConfigRoot: Path.Combine(validationRoot, "files-data", "config"),
    RuntimeRoot: Path.Combine(validationRoot, "files-data", "runtime"),
    LogRoot: Path.Combine(validationRoot, "files-data", "logs"),
    BackupRoot: Path.Combine(validationRoot, "files-data", "runtime", "backups"),
    UpdateStateRoot: Path.Combine(validationRoot, "files-data", "updates"),
    BindHost: "127.0.0.3",
    Port: filesPort,
    DefaultProfileName: "integration",
    DefaultProfileRoot: Path.Combine(validationRoot, "workspace"),
    DefaultProfileMode: "read-write");

var webOptions = new WebIntegrationOptions(
    NodeExecutable: node,
    EngineRoot: Path.Combine(devRoot, "agents", "web", "engine"),
    DataRoot: Path.Combine(validationRoot, "web-data"),
    ConfigRoot: Path.Combine(validationRoot, "web-data", "config"),
    RuntimeRoot: Path.Combine(validationRoot, "web-data", "runtime"),
    ArtifactsRoot: Path.Combine(validationRoot, "web-data", "artifacts"),
    LogRoot: Path.Combine(validationRoot, "web-data", "logs"),
    BindHost: "127.0.0.3",
    Port: webPort,
    Browser: "chrome",
    RuntimeMode: "native_attach",
    SessionIsolationMode: "tabs",
    ChromeExecutablePath: null,
    BridgeRequired: false,
    NativeAutoAttach: false,
    NativeAttachOnDemand: false);

var arcMapOptions = new ArcMapIntegrationOptions(
    PythonExecutable: arcMapPython,
    EngineRoot: Path.Combine(devRoot, "agents", "arcmap", "engine"),
    DataRoot: Path.Combine(validationRoot, "arcmap-data"),
    ConfigRoot: Path.Combine(validationRoot, "arcmap-data", "config"),
    IpcRoot: Path.Combine(validationRoot, "arcmap-data", "ipc"),
    RuntimeRoot: Path.Combine(validationRoot, "arcmap-data", "runtime"),
    LogRoot: Path.Combine(validationRoot, "arcmap-data", "logs"),
    BindHost: "127.0.0.3",
    Port: arcMapPort,
    McpPath: "/mcp",
    CommandTimeoutSeconds: 1);

var tunnelOptions = new TunnelIntegrationOptions(
    PythonExecutable: tunnelPython,
    EngineRoot: Path.Combine(devRoot, "agents", "tunnel", "engine"),
    ConfigRoot: Path.Combine(validationRoot, "tunnel-config"),
    RuntimeRoot: Path.Combine(validationRoot, "tunnel-runtime"),
    ChatLogPath: Path.Combine(validationRoot, "tunnel-logs", "chat.jsonl"),
    BindHost: "127.0.0.3",
    RouterPort: tunnelPort,
    DeviceId: "22222222-3333-4444-5555-666666666666",
    DeviceName: "Integration Device",
    DeviceAlias: "Integration Laptop",
    DeviceFingerprint: new string('c', 64),
    InstallationId: "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
    DeviceBinding: new string('d', 64),
    IdentityEnforcement: "mandatory");

using var http = new HttpClient(
    new SocketsHttpHandler { UseProxy = false })
{
    Timeout = TimeSpan.FromSeconds(20)
};

var registry = new CapabilityRegistry();
await using var supervisor = new NativeAgentSupervisor(
    acquireInstanceLease: false);

var files = new FilesAgentCoordinator(
    registry, supervisor,
    healthProbe: new FilesHealthProbe(http));
var web = new WebAgentCoordinator(
    registry, supervisor,
    healthProbe: new WebHealthProbe(http));
var arcMap = new ArcMapAgentCoordinator(
    registry, supervisor,
    healthProbe: new ArcMapHealthProbe(http));
var tunnel = new TunnelAgentCoordinator(
    registry, supervisor,
    healthProbe: new TunnelRouterHealthProbe(http));

try
{
    await files.PrepareAsync(filesOptions, "3.3.0-v3", true);
    await web.PrepareAsync(webOptions, "2.2.10-zagent.1", true);
    await arcMap.PrepareAsync(arcMapOptions, "3.0.0-zagent.1", true);

    Must((await files.StartAsync(filesOptions, TimeSpan.FromSeconds(15))).Success, "Files start failed.");
    Must((await web.StartAsync(webOptions, TimeSpan.FromSeconds(15))).Success, "Web start failed.");
    Must((await arcMap.StartAsync(arcMapOptions, TimeSpan.FromSeconds(15))).Success, "ArcMap MCP start failed.");

    await tunnel.PrepareAsync(
        tunnelOptions,
        new[]
        {
            new TunnelServiceDefinition(
                "zagent_files", "Zagent Files", "files",
                $"http://127.0.0.3:{filesPort}/mcp",
                TimeoutSeconds: 3),
            new TunnelServiceDefinition(
                "zagent_web", "Zagent Web", "web",
                $"http://127.0.0.3:{webPort}/mcp"),
            new TunnelServiceDefinition(
                "zagent_arcmap", "Zagent ArcMap", "arcmap",
                $"http://127.0.0.3:{arcMapPort}/mcp")
        },
        "4.1.0-zagent.3",
        true);

    Must(
        (await tunnel.StartAsync(
            tunnelOptions,
            startTransport: false,
            readyTimeout: TimeSpan.FromSeconds(15))).Success,
        "Tunnel start failed.");

    var routerUri = new Uri(
        $"http://127.0.0.3:{tunnelPort}/mcp");

    var tools = await ListToolsAsync(http, routerUri);

    Eq(370, tools.Length);
    Eq(370, tools.Distinct(StringComparer.Ordinal).Count());

    foreach (var name in FilesAgentManifestFactory.KnownToolNames)
        Must(tools.Contains(name, StringComparer.Ordinal), $"Missing Files tool {name}");
    foreach (var name in WebAgentManifestFactory.KnownToolNames)
        Must(tools.Contains(name, StringComparer.Ordinal), $"Missing Web tool {name}");
    foreach (var name in ArcMapAgentManifestFactory.KnownToolNames)
        Must(tools.Contains(name, StringComparer.Ordinal), $"Missing ArcMap tool {name}");

    var management = new[]
    {
        "zagent_access_bootstrap",
        "zagent_access_status",
        "zagent_access_request",
        "zagent_access_request_status",
        "zagent_access_wait",
        "zagent_access_revoke",
        "zagent_access_dev_grant_create",
        "zagent_access_dev_grant_get",
        "zagent_router_status",
        "zagent_router_refresh",
        "zagent_identity_status",
        "zagent_identity_bootstrap",
        "zagent_identity_list_devices",
        "zagent_identity_session_get",
        "zagent_identity_session_bind",
        "zagent_identity_session_unbind",
        "zagent_identity_session_switch",
        "zagent_identity_verify_target",
        "zagent_task_submit",
        "zagent_task_status",
        "zagent_task_result",
        "zagent_task_cancel",
        "zagent_task_list",
        "zagent_telemetry_status"
    };

    foreach (var name in management)
        Must(tools.Contains(name, StringComparer.Ordinal), $"Missing Tunnel tool {name}");

    using var accessBootstrap = await CallToolAsync(
        http,
        routerUri,
        "zagent_access_bootstrap");
    Must(
        accessBootstrap.RootElement.ToString().Contains(
            "requires_operator_prompt",
            StringComparison.Ordinal),
        "Plugin access bootstrap did not return the expected approval flow.");

    using var accessRequest = await CallToolAsync(
        http,
        routerUri,
        "zagent_access_request",
        new
        {
            operator_alias = "Integration Laptop"
        });

    var accessRequestText =
        accessRequest.RootElement
            .GetProperty("result")
            .GetProperty("content")[0]
            .GetProperty("text")
            .GetString()
        ?? throw new InvalidDataException(
            "Plugin access request returned no text result.");

    using var accessRequestPayload =
        JsonDocument.Parse(accessRequestText);
    var accessRequestId =
        accessRequestPayload.RootElement
            .GetProperty("request_id")
            .GetString()
        ?? throw new InvalidDataException(
            "Plugin access request returned no request_id.");

    using (var approval = new HttpRequestMessage(
        HttpMethod.Post,
        new Uri(
            $"http://127.0.0.3:{tunnelPort}/router/access/request/" +
            $"{Uri.EscapeDataString(accessRequestId)}/resolve")))
    {
        approval.Content = new StringContent(
            JsonSerializer.Serialize(new { action = "approve" }),
            Encoding.UTF8,
            "application/json");
        using var approvalResponse = await http.SendAsync(approval);
        var approvalBody =
            await approvalResponse.Content.ReadAsStringAsync();
        Must(
            approvalResponse.IsSuccessStatusCode,
            $"Plugin access local approval failed: {approvalBody}");
        using var approvalPayload =
            JsonDocument.Parse(approvalBody);
        Must(
            approvalPayload.RootElement
                .GetProperty("allowed")
                .GetBoolean(),
            "Plugin access approval did not open the session.");
    }

    using var identityBinding = await CallToolAsync(
        http,
        routerUri,
        "zagent_identity_session_bind",
        new
        {
            operator_alias = "Integration Laptop",
            target_device_id =
                "22222222-3333-4444-5555-666666666666"
        });
    Must(
        identityBinding.RootElement.ToString().Contains(
            "Integration Laptop",
            StringComparison.Ordinal),
        "Integration session identity binding failed.");

    using var filesPing = await CallToolAsync(http, routerUri, "files_ping");
    Must(filesPing.RootElement.ToString().Contains("Zagent Files", StringComparison.Ordinal), "Files route failed.");

    using var longFilesCommand = await CallToolAsync(
        http,
        routerUri,
        "files_powershell_run",
        new
        {
            script = "Start-Sleep -Seconds 4; Write-Output 'long-route-pass'",
            profile = "integration",
            cwd = ".",
            timeout_seconds = 5
        });
    Must(
        longFilesCommand.RootElement.ToString().Contains(
            "long-route-pass",
            StringComparison.Ordinal),
        "Files long-running route was cut off by the shorter upstream timeout.");

    using var webPing = await CallToolAsync(http, routerUri, "web_ping");
    Must(webPing.RootElement.ToString().Contains("Zagent Web", StringComparison.Ordinal), "Web route failed.");

    using var arcMapSafety = await CallToolAsync(
        http,
        routerUri,
        "arcmap_agent_safety_status");
    Must(
        arcMapSafety.RootElement.ToString().Contains("allow_export", StringComparison.Ordinal),
        "ArcMap route failed.");

    Must(
        registry.TryGet(FilesAgentManifestFactory.AgentId, out var f) &&
        f?.Health == AgentHealthState.Ready,
        "Files Registry health is not Ready.");

    Must(
        registry.TryGet(WebAgentManifestFactory.AgentId, out var w) &&
        w?.Health == AgentHealthState.Ready,
        "Web Registry health is not Ready.");

    Must(
        registry.TryGet(ArcMapAgentManifestFactory.AgentId, out var a) &&
        a?.Health == AgentHealthState.Degraded,
        "ArcMap Registry should be Degraded while external live bridge is offline.");

    Must(
        registry.TryGet(TunnelAgentManifestFactory.AgentId, out var t) &&
        t?.Health == AgentHealthState.Ready,
        "Tunnel Registry health is not Ready.");

    foreach (var id in new[]
    {
        FilesProcessFactory.ProcessId,
        WebProcessFactory.ProcessId,
        ArcMapProcessFactory.ProcessId,
        TunnelProcessFactory.RouterProcessId
    })
    {
        Must(
            supervisor.TryGetSnapshot(id, out var p) &&
            p is not null &&
            p.State == AgentProcessState.Running &&
            p.ProcessTreeOwned,
            $"{id} is not Running/JobObject-owned.");
    }

    Console.WriteLine(
        $"PASS Tunnel -> Files+Web+ArcMap tools={tools.Length} " +
        $"files=71 web=151 arcmap=124 management=24 " +
        $"ports={filesPort},{webPort},{arcMapPort},{tunnelPort}");
}
finally
{
    try { await tunnel.StopAsync(); } catch { }
    try { await arcMap.StopAsync(); } catch { }
    try { await web.StopAsync(); } catch { }
    try { await files.StopAsync(); } catch { }
    try { await supervisor.StopAllAsync(); } catch { }
    try { Directory.Delete(validationRoot, recursive: true); } catch { }
}

Console.WriteLine("AGENT_INTEGRATION_TEST_PASS total_tools=370");
return 0;

static async Task<JsonDocument> CallToolAsync(
    HttpClient client,
    Uri uri,
    string name,
    object? arguments = null) =>
    await RpcAsync(
        client,
        uri,
        new
        {
            jsonrpc = "2.0",
            id = Guid.NewGuid().ToString("N"),
            method = "tools/call",
            @params = new
            {
                name,
                arguments = arguments ?? new { },
                _meta = new Dictionary<string, string>
                {
                    ["openai/session"] = "integration-session"
                }
            }
        });

static async Task<string[]> ListToolsAsync(
    HttpClient client,
    Uri uri)
{
    using var result = await RpcAsync(
        client,
        uri,
        new
        {
            jsonrpc = "2.0",
            id = "all-tools",
            method = "tools/list",
            @params = new { }
        });

    return result.RootElement
        .GetProperty("result")
        .GetProperty("tools")
        .EnumerateArray()
        .Select(x => x.GetProperty("name").GetString() ?? "")
        .Where(x => !string.IsNullOrWhiteSpace(x))
        .OrderBy(x => x, StringComparer.Ordinal)
        .ToArray();
}

static async Task<JsonDocument> RpcAsync(
    HttpClient client,
    Uri uri,
    object payload)
{
    using var request = new HttpRequestMessage(HttpMethod.Post, uri);
    request.Content = new StringContent(
        JsonSerializer.Serialize(payload),
        Encoding.UTF8,
        "application/json");
    request.Headers.Accept.Add(
        new MediaTypeWithQualityHeaderValue("application/json"));
    request.Headers.Accept.Add(
        new MediaTypeWithQualityHeaderValue("text/event-stream"));
    request.Headers.TryAddWithoutValidation(
        "MCP-Protocol-Version",
        "2025-06-18");

    using var response = await client.SendAsync(request);
    var body = await response.Content.ReadAsStringAsync();

    if (!response.IsSuccessStatusCode)
        throw new HttpRequestException(
            $"HTTP {(int)response.StatusCode}: {body}");

    if (body.TrimStart().StartsWith("event:", StringComparison.Ordinal))
    {
        var data = body
            .Split(new[] { "\r\n", "\n" }, StringSplitOptions.None)
            .Where(x => x.StartsWith("data:", StringComparison.Ordinal))
            .Select(x => x[5..].Trim())
            .Where(x => !string.IsNullOrWhiteSpace(x) && x != "[DONE]")
            .ToArray();

        if (data.Length == 0)
            throw new InvalidDataException("MCP SSE response has no data.");

        return JsonDocument.Parse(data[^1]);
    }

    return JsonDocument.Parse(body);
}

static int FreePort(IReadOnlyCollection<int> used)
{
    var address = IPAddress.Parse("127.0.0.3");
    for (var port = 18900; port <= 18999; port++)
    {
        if (used.Contains(port)) continue;
        TcpListener? listener = null;
        try
        {
            listener = new TcpListener(address, port);
            listener.Start();
            return port;
        }
        catch (SocketException) { }
        finally { listener?.Stop(); }
    }

    throw new InvalidOperationException("No free Development Gateway port.");
}

static void Must(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

static void Eq<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
        throw new InvalidOperationException(
            $"Expected '{expected}', actual '{actual}'.");
}

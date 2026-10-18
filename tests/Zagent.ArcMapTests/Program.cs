using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Zagent.Core.Agents.ArcMap;
using Zagent.Core.Registry;
using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;

var passed = 0;
var failed = 0;

var devRoot = Environment.GetEnvironmentVariable("ZAGENT_DEV_ROOT")
    ?? throw new InvalidOperationException("ZAGENT_DEV_ROOT is not set.");
var python = Environment.GetEnvironmentVariable("ZAGENT_ARCMAP_TEST_PYTHON")
    ?? throw new InvalidOperationException("ZAGENT_ARCMAP_TEST_PYTHON is not set.");

var engineRoot = Path.Combine(
    devRoot,
    "agents",
    "arcmap",
    "engine");

var validationRoot = Path.Combine(
    devRoot,
    "_validation",
    "phase7-arcmap-live");

if (Directory.Exists(validationRoot))
{
    Directory.Delete(validationRoot, recursive: true);
}
Directory.CreateDirectory(validationRoot);

var port = FindFreeDevelopmentPort("127.0.0.3");

var options = new ArcMapIntegrationOptions(
    PythonExecutable: python,
    EngineRoot: engineRoot,
    DataRoot: Path.Combine(validationRoot, "data"),
    ConfigRoot: Path.Combine(validationRoot, "data", "config"),
    IpcRoot: Path.Combine(validationRoot, "data", "ipc"),
    RuntimeRoot: Path.Combine(validationRoot, "data", "runtime"),
    LogRoot: Path.Combine(validationRoot, "data", "logs"),
    BindHost: "127.0.0.3",
    Port: port,
    McpPath: "/mcp",
    LegacyManualBaseline: null,
    CommandTimeoutSeconds: 1);

using var http = new HttpClient(
    new SocketsHttpHandler
    {
        UseProxy = false
    })
{
    Timeout = TimeSpan.FromSeconds(8)
};

var registry = new CapabilityRegistry();
await using var supervisor =
    new NativeAgentSupervisor(
        acquireInstanceLease: false);

var healthProbe = new ArcMapHealthProbe(http);
var coordinator = new ArcMapAgentCoordinator(
    registry,
    supervisor,
    healthProbe: healthProbe);

try
{
    await RunAsync(
        "manifest contains runtime-verified 132 ArcMap capabilities",
        async () =>
        {
            var manifest = ArcMapAgentManifestFactory.Create(
                "3.0.0-zagent.1",
                "127.0.0.3",
                18840);

            Equal(132, manifest.Capabilities.Count);
            Equal(
                132,
                manifest.Capabilities
                    .Select(item => item.Name)
                    .Distinct(StringComparer.Ordinal)
                    .Count());

            var localRegistry = new CapabilityRegistry();
            var result = localRegistry.Register(
                manifest,
                productionApproved: true);

            True(
                result.Success,
                string.Join("; ", result.Errors));

            foreach (var tool in ArcMapAgentManifestFactory.KnownToolNames)
            {
                Equal(
                    1,
                    localRegistry.FindOwners(
                        ArcMapAgentManifestFactory.ToCapabilityName(tool))
                        .Count);
            }

            var save = manifest.Capabilities.Single(
                item => item.Name == "arcmap.save_current_map");
            Equal(CapabilityAccess.Admin, save.Access);
            Equal(CapabilityApproval.Policy, save.Approval);
            Equal(ResourcePolicy.Exclusive, save.ResourcePolicy);

            var layers = manifest.Capabilities.Single(
                item => item.Name == "arcmap.list_layers");
            Equal(CapabilityAccess.Read, layers.Access);

            await Task.CompletedTask;
        });

    await RunAsync(
        "configuration isolates IPC and locks production export defaults",
        async () =>
        {
            var writer = new ArcMapConfigurationWriter();
            await writer.WriteAsync(options);

            var agentConfigPath = Path.Combine(
                options.ConfigRoot,
                "agent_config.json");
            var pathsPath = Path.Combine(
                options.ConfigRoot,
                "paths.json");

            using var agentConfig = JsonDocument.Parse(
                await File.ReadAllTextAsync(agentConfigPath));
            using var paths = JsonDocument.Parse(
                await File.ReadAllTextAsync(pathsPath));

            Equal(
                400,
                agentConfig.RootElement
                    .GetProperty("default_export_dpi")
                    .GetInt32());

            var formats = agentConfig.RootElement
                .GetProperty("default_export_formats")
                .EnumerateArray()
                .Select(item => item.GetString() ?? "")
                .ToArray();

            Equal("PDF,PNG", string.Join(",", formats));
            Equal(
                "Hasil Peta",
                agentConfig.RootElement
                    .GetProperty("default_output_folder")
                    .GetString());

            Equal(
                Path.GetFullPath(options.EngineRoot),
                Path.GetFullPath(
                    paths.RootElement
                        .GetProperty("work_root")
                        .GetString()!));

            Equal(
                Path.GetFullPath(options.DataRoot),
                Path.GetFullPath(
                    paths.RootElement
                        .GetProperty("data_root")
                        .GetString()!));

            foreach (var folder in new[]
            {
                "inbox",
                "outbox",
                "archive",
                "logs"
            })
            {
                True(
                    Directory.Exists(
                        Path.Combine(options.IpcRoot, folder)),
                    $"IPC folder missing: {folder}");
            }
        });

    await RunAsync(
        "bridge source enforces exclusive ownership and external ArcMap policy",
        async () =>
        {
            var toolbox = await File.ReadAllTextAsync(
                Path.Combine(
                    engineRoot,
                    "arcmap_bridge",
                    "ArcMapAgent.pyt"));

            var bootstrap = await File.ReadAllTextAsync(
                Path.Combine(
                    engineRoot,
                    "arcmap_bridge",
                    "bootstrap.py"));

            var liveBridge = await File.ReadAllTextAsync(
                Path.Combine(
                    engineRoot,
                    "arcmap_bridge",
                    "live_bridge.py"));

            True(
                toolbox.Contains(
                    "zagent_arcmap_bootstrap",
                    StringComparison.Ordinal),
                "Toolbox does not use a unique Zagent bootstrap module.");

            True(
                bootstrap.Contains(
                    "_assert_no_foreign_arcmap_bridge",
                    StringComparison.Ordinal),
                "Legacy/foreign bridge detection missing.");

            True(
                bootstrap.Contains(
                    "Zagent refuses dual ownership",
                    StringComparison.Ordinal),
                "Explicit dual-ownership refusal missing.");

            True(
                liveBridge.Contains(
                    "CreateMutexW",
                    StringComparison.Ordinal),
                "Windows ownership mutex missing.");

            True(
                liveBridge.Contains(
                    "arcmap-owner.json",
                    StringComparison.Ordinal),
                "Owner diagnostics file missing.");

            await Task.CompletedTask;
        });

    await RunAsync(
        "snapshot restore and PDF PNG 400 DPI contracts are preserved",
        async () =>
        {
            foreach (var requiredTool in new[]
            {
                "arcmap_snapshot_state",
                "arcmap_restore_snapshot",
                "arcmap_export_pdf",
                "arcmap_export_png",
                "arcmap_export_bundle",
                "arcmap_stage3_export_current"
            })
            {
                True(
                    ArcMapAgentManifestFactory.KnownToolNames.Contains(
                        requiredTool,
                        StringComparer.Ordinal),
                    $"Required ArcMap contract tool missing: {requiredTool}");
            }

            True(
                ArcMapAgentManifestFactory.KnownToolNames.Contains(
                    "arcmap_export_jpeg",
                    StringComparer.Ordinal) &&
                ArcMapAgentManifestFactory.KnownToolNames.Contains(
                    "arcmap_export_tiff",
                    StringComparer.Ordinal),
                "Legacy export capability was reduced.");

            var exportSource = await File.ReadAllTextAsync(
                Path.Combine(
                    engineRoot,
                    "mcp_server",
                    "tools",
                    "export.py"));

            True(
                exportSource.Contains(
                    "resolution: int = 400",
                    StringComparison.Ordinal),
                "Primary export defaults are not 400 DPI.");

            using var stage3Profile = JsonDocument.Parse(
                await File.ReadAllTextAsync(
                    Path.Combine(
                        engineRoot,
                        "config",
                        "stage3_default_profile.json")));

            var export = stage3Profile.RootElement
                .GetProperty("export");

            True(export.GetProperty("pdf").GetBoolean(), "Stage 3 PDF default disabled.");
            True(export.GetProperty("png").GetBoolean(), "Stage 3 PNG default disabled.");
            Equal(400, export.GetProperty("resolution").GetInt32());
        });

    await RunAsync(
        "coordinator starts only MCP under Native Supervisor",
        async () =>
        {
            await coordinator.PrepareAsync(
                options,
                version: "3.0.0-zagent.1",
                productionApproved: true);

            var start = await coordinator.StartAsync(
                options,
                TimeSpan.FromSeconds(15));

            True(
                start.Success,
                start.Message ?? "ArcMap MCP failed to start.");

            True(
                supervisor.TryGetSnapshot(
                    ArcMapProcessFactory.ProcessId,
                    out var process) &&
                process is not null,
                "ArcMap MCP process snapshot missing.");

            Equal(AgentProcessState.Running, process!.State);
            True(
                process.ProcessTreeOwned,
                "ArcMap MCP process is not Job Object owned.");

            True(
                registry.TryGet(
                    ArcMapAgentManifestFactory.AgentId,
                    out var registered) &&
                registered is not null,
                "ArcMap registry entry missing.");

            Equal(
                AgentHealthState.Degraded,
                registered!.Health);

            var arcMapProcesses = System.Diagnostics.Process
                .GetProcessesByName("ArcMap");

            // Zagent Core must never claim ArcMap.exe as an owned child.
            True(
                supervisor.Snapshot().All(
                    item =>
                        !string.Equals(
                            item.AgentId,
                            "ArcMap.exe",
                            StringComparison.OrdinalIgnoreCase)),
                "Supervisor incorrectly registered ArcMap.exe.");

            foreach (var processInfo in arcMapProcesses)
            {
                processInfo.Dispose();
            }
        });

    var mcpUri = ArcMapAgentCoordinator.BuildMcpUri(options);

    await RunAsync(
        "runtime exposes exactly 132 frozen ArcMap tools",
        async () =>
        {
            var runtimeTools = await ListToolsAsync(http, mcpUri);

            var expected =
                ArcMapAgentManifestFactory.KnownToolNames
                    .OrderBy(
                        item => item,
                        StringComparer.Ordinal)
                    .ToArray();

            Equal(132, runtimeTools.Length);
            Equal(
                string.Join("\n", expected),
                string.Join("\n", runtimeTools));

            Equal(
                8,
                runtimeTools.Count(
                    name =>
                        name.StartsWith(
                            "arcmap_stage2_",
                            StringComparison.Ordinal)));

            Equal(
                20,
                runtimeTools.Count(
                    name =>
                        name.StartsWith(
                            "arcmap_stage3_",
                            StringComparison.Ordinal)));
        });

    await RunAsync(
        "MCP stays healthy while external ArcMap bridge is offline",
        async () =>
        {
            var health = await healthProbe.ProbeAsync(mcpUri);

            True(
                health.McpReady,
                health.Error ?? "ArcMap MCP health failed.");
            False(
                health.BridgeReady,
                "Fresh isolated Zagent IPC unexpectedly found an ArcMap bridge.");
            Equal(132, health.ToolCount);
            True(health.Stage2Loaded, "Stage 2 not loaded.");
            True(health.Stage3Loaded, "Stage 3 not loaded.");

            var refreshed =
                await coordinator.RefreshHealthAsync(options);

            True(refreshed.McpReady, "MCP lost readiness.");

            True(
                registry.TryGet(
                    ArcMapAgentManifestFactory.AgentId,
                    out var registered) &&
                registered?.Health == AgentHealthState.Degraded,
                "Bridge-offline state was not published as Degraded.");

            True(
                supervisor.TryGetSnapshot(
                    ArcMapProcessFactory.ProcessId,
                    out var process) &&
                process?.State == AgentProcessState.Running,
                "Degraded external bridge state restarted/stopped healthy MCP.");
        });

    await RunAsync(
        "local safety tool works without taking ArcMap ownership",
        async () =>
        {
            using var result = await RpcAsync(
                http,
                mcpUri,
                new
                {
                    jsonrpc = "2.0",
                    id = "arcmap-safety",
                    method = "tools/call",
                    @params = new
                    {
                        name = "arcmap_agent_safety_status",
                        arguments = new { }
                    }
                });

            var text = result.RootElement.ToString();

            True(
                text.Contains(
                    "allow_export",
                    StringComparison.Ordinal),
                "Safety result missing export policy.");

            True(
                text.Contains(
                    "allow_geoprocessing",
                    StringComparison.Ordinal),
                "Safety result missing geoprocessing policy.");
        });

    await RunAsync(
        "ArcMap MCP restart and stop leave clean supervised state",
        async () =>
        {
            var before = supervisor.Snapshot()
                .Single(
                    item =>
                        item.AgentId ==
                        ArcMapProcessFactory.ProcessId);

            var restart = await supervisor.RestartAsync(
                ArcMapProcessFactory.ProcessId);

            True(
                restart.Success,
                restart.Message ?? "ArcMap MCP restart failed.");

            await WaitUntilAsync(
                async () =>
                    (await healthProbe.ProbeAsync(mcpUri)).McpReady,
                TimeSpan.FromSeconds(15));

            var after = supervisor.Snapshot()
                .Single(
                    item =>
                        item.AgentId ==
                        ArcMapProcessFactory.ProcessId);

            True(
                after.ProcessId != before.ProcessId,
                "ArcMap MCP restart did not replace PID.");
            True(
                after.ProcessTreeOwned,
                "Restarted ArcMap MCP lost Job Object ownership.");

            var stop = await coordinator.StopAsync();

            True(
                stop.Success,
                stop.Message ?? "ArcMap MCP stop failed.");

            True(
                registry.TryGet(
                    ArcMapAgentManifestFactory.AgentId,
                    out var stopped) &&
                stopped?.Health == AgentHealthState.Offline,
                "ArcMap registry did not publish Offline.");

            supervisor.TryGetSnapshot(
                ArcMapProcessFactory.ProcessId,
                out var snapshot);

            Equal(
                AgentProcessState.Stopped,
                snapshot!.State);
        });
}
finally
{
    try
    {
        await supervisor.StopAllAsync();
    }
    catch
    {
    }

    try
    {
        Directory.Delete(
            validationRoot,
            recursive: true);
    }
    catch
    {
    }
}

Console.WriteLine(
    failed == 0
        ? $"ARCMAP_TEST_PASS passed={passed} failed={failed}"
        : $"ARCMAP_TEST_FAIL passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

static async Task<string[]> ListToolsAsync(
    HttpClient client,
    Uri uri)
{
    using var response = await RpcAsync(
        client,
        uri,
        new
        {
            jsonrpc = "2.0",
            id = "arcmap-tools-list",
            method = "tools/list",
            @params = new { }
        });

    return response.RootElement
        .GetProperty("result")
        .GetProperty("tools")
        .EnumerateArray()
        .Select(
            item =>
                item.GetProperty("name").GetString() ?? "")
        .Where(
            name =>
                !string.IsNullOrWhiteSpace(name))
        .OrderBy(
            name => name,
            StringComparer.Ordinal)
        .ToArray();
}

static async Task<JsonDocument> RpcAsync(
    HttpClient client,
    Uri uri,
    object payload)
{
    var json = JsonSerializer.Serialize(payload);

    using var request = new HttpRequestMessage(
        HttpMethod.Post,
        uri);

    request.Content = new StringContent(
        json,
        Encoding.UTF8,
        "application/json");

    request.Headers.Accept.Add(
        new MediaTypeWithQualityHeaderValue(
            "application/json"));
    request.Headers.Accept.Add(
        new MediaTypeWithQualityHeaderValue(
            "text/event-stream"));
    request.Headers.TryAddWithoutValidation(
        "MCP-Protocol-Version",
        "2025-06-18");

    using var response = await client.SendAsync(request);
    var body = await response.Content.ReadAsStringAsync();

    if (!response.IsSuccessStatusCode)
    {
        throw new HttpRequestException(
            $"HTTP {(int)response.StatusCode}: {body}");
    }

    if (body.TrimStart().StartsWith(
            "event:",
            StringComparison.Ordinal))
    {
        var payloads = body
            .Split(
                new[] { "\r\n", "\n" },
                StringSplitOptions.None)
            .Where(
                line =>
                    line.StartsWith(
                        "data:",
                        StringComparison.Ordinal))
            .Select(line => line[5..].Trim())
            .Where(
                line =>
                    !string.IsNullOrWhiteSpace(line) &&
                    line != "[DONE]")
            .ToArray();

        if (payloads.Length == 0)
        {
            throw new InvalidDataException(
                "ArcMap MCP SSE response contained no JSON payload.");
        }

        return JsonDocument.Parse(payloads[^1]);
    }

    return JsonDocument.Parse(body);
}

static async Task WaitUntilAsync(
    Func<Task<bool>> predicate,
    TimeSpan timeout)
{
    var deadline = DateTimeOffset.UtcNow + timeout;

    while (DateTimeOffset.UtcNow < deadline)
    {
        if (await predicate())
        {
            return;
        }

        await Task.Delay(100);
    }

    throw new TimeoutException(
        $"Condition was not satisfied within {timeout}.");
}

async Task RunAsync(
    string name,
    Func<Task> test)
{
    try
    {
        await test();
        passed++;
        Console.WriteLine($"PASS {name}");
    }
    catch (Exception ex)
    {
        failed++;
        Console.WriteLine($"FAIL {name}: {ex}");
    }
}

static int FindFreeDevelopmentPort(
    string host)
{
    var address = IPAddress.Parse(host);

    for (var port = 18900;
        port <= 18999;
        port++)
    {
        TcpListener? listener = null;

        try
        {
            listener = new TcpListener(
                address,
                port);
            listener.Start();
            return port;
        }
        catch (SocketException)
        {
        }
        finally
        {
            listener?.Stop();
        }
    }

    throw new InvalidOperationException(
        "No free Zagent Development Gateway port is available.");
}

static void True(
    bool condition,
    string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void False(
    bool condition,
    string message) =>
    True(!condition, message);

static void Equal<T>(
    T expected,
    T actual)
{
    if (!EqualityComparer<T>.Default.Equals(
            expected,
            actual))
    {
        throw new InvalidOperationException(
            $"Expected '{expected}', actual '{actual}'.");
    }
}
using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Zagent.Core.Agents.Web;
using Zagent.Core.Registry;
using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;

var passed = 0;
var failed = 0;

var devRoot = Environment.GetEnvironmentVariable("ZAGENT_DEV_ROOT")
    ?? throw new InvalidOperationException("ZAGENT_DEV_ROOT is not set.");
var node = Environment.GetEnvironmentVariable("ZAGENT_WEB_TEST_NODE")
    ?? throw new InvalidOperationException("ZAGENT_WEB_TEST_NODE is not set.");

var engineRoot = Path.Combine(
    devRoot,
    "agents",
    "web",
    "engine");

var validationRoot = Path.Combine(
    devRoot,
    "_validation",
    "phase6-web-live");

if (Directory.Exists(validationRoot))
{
    Directory.Delete(validationRoot, recursive: true);
}

Directory.CreateDirectory(validationRoot);

var port = FindFreeDevelopmentPort("127.0.0.3");

var options = CreateOptions(
    bridgeRequired: false,
    nativeAutoAttach: false,
    nativeAttachOnDemand: false);

using var http = new HttpClient(
    new SocketsHttpHandler
    {
        UseProxy = false
    })
{
    Timeout = TimeSpan.FromSeconds(20)
};

var registry = new CapabilityRegistry();

await using var supervisor =
    new NativeAgentSupervisor(
        acquireInstanceLease: false);

var healthProbe = new WebHealthProbe(http);
var coordinator = new WebAgentCoordinator(
    registry,
    supervisor,
    healthProbe: healthProbe);

try
{
    await RunAsync(
        "manifest contains runtime-verified 151 capabilities",
        async () =>
        {
            var manifest = WebAgentManifestFactory.Create(
                "2.2.10-zagent.1",
                "127.0.0.3",
                18830);

            Equal(151, manifest.Capabilities.Count);
            Equal(
                151,
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

            foreach (var tool in WebAgentManifestFactory.KnownToolNames)
            {
                Equal(
                    1,
                    localRegistry.FindOwners(
                        WebAgentManifestFactory.ToCapabilityName(tool))
                        .Count);
            }

            await Task.CompletedTask;
        });

    await RunAsync(
        "configuration preserves camelCase and isolates mutable state",
        async () =>
        {
            var writer = new WebConfigurationWriter();
            await writer.WriteAsync(options);

            var settingsPath = Path.Combine(
                options.ConfigRoot,
                "settings.json");
            var bridgePath = Path.Combine(
                options.ConfigRoot,
                "bridge.json");

            using var settings = JsonDocument.Parse(
                await File.ReadAllTextAsync(settingsPath));

            var root = settings.RootElement;

            True(
                root.TryGetProperty("runtimeMode", out _),
                "runtimeMode missing.");
            True(
                root.TryGetProperty("screenshotsDir", out _),
                "screenshotsDir missing.");
            False(
                root.TryGetProperty("runtime_mode", out _),
                "snake_case runtime_mode must not be emitted.");
            False(
                root.TryGetProperty("screenshots_dir", out _),
                "snake_case screenshots_dir must not be emitted.");

            Equal(
                "127.0.0.3",
                root.GetProperty("host").GetString());
            Equal(
                port,
                root.GetProperty("port").GetInt32());
            Equal(
                "native_attach",
                root.GetProperty("runtimeMode").GetString());
            Equal(
                "tabs",
                root.GetProperty("sessionIsolationMode").GetString());
            Equal(
                "DEVELOPMENT",
                root.GetProperty("bridgeEnvironment").GetString());
            Equal(
                $"http://127.0.0.3:{port}/bridge/",
                root.GetProperty("bridgeEndpoint").GetString());

            using var bridge = JsonDocument.Parse(
                await File.ReadAllTextAsync(bridgePath));

            False(
                bridge.RootElement.GetProperty("required").GetBoolean(),
                "Development bridge should be disabled for direct behavior test.");
            Equal(
                "DEVELOPMENT",
                bridge.RootElement.GetProperty("environment").GetString());
            Equal(
                $"http://127.0.0.3:{port}/bridge/",
                bridge.RootElement.GetProperty("endpoint").GetString());

            foreach (var forbidden in new[]
            {
                "pairingHash",
                "extensionOrigin",
                "reconnectHash",
                "profileBinding",
                "token",
                "reconnectSecret"
            })
            {
                False(
                    bridge.RootElement.TryGetProperty(forbidden, out _),
                    $"Sensitive bridge state '{forbidden}' must not be copied.");
            }

            True(
                Path.GetFullPath(options.ConfigRoot)
                    .StartsWith(
                        Path.GetFullPath(validationRoot),
                        StringComparison.OrdinalIgnoreCase),
                "Web config escaped validation data root.");
        });


    await RunAsync(
        "configuration preserves existing Chrome bridge pairing state",
        async () =>
        {
            var bridgePath = Path.Combine(
                options.ConfigRoot,
                "bridge.json");

            var pairedState = JsonSerializer.Serialize(
                new
                {
                    required = false,
                    extensionOrigin =
                        "chrome-extension://kejbfjimcnebnfcadfpnbljnkpcfakpg",
                    reconnectHash =
                        "test-reconnect-hash",
                    profileBinding = new
                    {
                        directory = "Profile 14",
                        name = "HARRY",
                        boundEmail = "test@example.invalid",
                        instanceHash = "test-instance"
                    }
                });

            await File.WriteAllTextAsync(
                bridgePath,
                pairedState);

            var writer = new WebConfigurationWriter();
            await writer.WriteAsync(options);

            using var bridge = JsonDocument.Parse(
                await File.ReadAllTextAsync(bridgePath));

            var root = bridge.RootElement;

            Equal(
                "chrome-extension://kejbfjimcnebnfcadfpnbljnkpcfakpg",
                root.GetProperty("extensionOrigin").GetString());
            Equal(
                "test-reconnect-hash",
                root.GetProperty("reconnectHash").GetString());
            Equal(
                "Profile 14",
                root.GetProperty("profileBinding")
                    .GetProperty("directory")
                    .GetString());
            False(
                root.GetProperty("required").GetBoolean(),
                "Writer must update required without erasing pairing state.");
        });

    await RunAsync(
        "Chrome Bridge runtime configuration follows installed machine Web port",
        async () =>
        {
            var syncRoot = Path.Combine(
                validationRoot,
                "bridge-sync-root");

            if (Directory.Exists(syncRoot))
            {
                Directory.Delete(syncRoot, recursive: true);
            }

            var extensionRoots = new[]
            {
                Path.Combine(
                    syncRoot,
                    "agents",
                    "web",
                    "engine",
                    "extension"),
                Path.Combine(
                    syncRoot,
                    "agents",
                    "web",
                    "engine",
                    "artifacts",
                    "chrome-bridge")
            };

            foreach (var extensionRoot in extensionRoots)
            {
                Directory.CreateDirectory(extensionRoot);
                await File.WriteAllTextAsync(
                    Path.Combine(extensionRoot, "manifest.json"),
                    "{\"manifest_version\":3}");
                await File.WriteAllTextAsync(
                    Path.Combine(extensionRoot, "background.js"),
                    "// test worker");
            }

            var synchronizer =
                new ChromeBridgeConfigurationSynchronizer();

            var first = await synchronizer.SyncAsync(
                syncRoot,
                "127.0.0.3",
                18831,
                "PRODUCTION");

            Equal(
                "http://127.0.0.3:18831/bridge/",
                first.DefaultBase);
            Equal(2, first.WrittenPaths.Count);

            foreach (var extensionRoot in extensionRoots)
            {
                using var config = JsonDocument.Parse(
                    await File.ReadAllTextAsync(
                        Path.Combine(
                            extensionRoot,
                            "bridge-config.json")));

                True(
                    config.RootElement
                        .GetProperty("configured")
                        .GetBoolean(),
                    "Installed Bridge config must be configured.");
                Equal(
                    "PRODUCTION",
                    config.RootElement
                        .GetProperty("environment")
                        .GetString());
                Equal(
                    "http://127.0.0.3:18831/bridge/",
                    config.RootElement
                        .GetProperty("defaultBase")
                        .GetString());
                Equal(
                    "zagent.machine.json",
                    config.RootElement
                        .GetProperty("generatedFrom")
                        .GetString());
            }

            await synchronizer.SyncAsync(
                syncRoot,
                "127.0.0.3",
                18832,
                "PRODUCTION");

            using var migrated = JsonDocument.Parse(
                await File.ReadAllTextAsync(
                    Path.Combine(
                        extensionRoots[0],
                        "bridge-config.json")));

            var legacy = migrated.RootElement
                .GetProperty("legacyBases")
                .EnumerateArray()
                .Select(item => item.GetString() ?? "")
                .ToArray();

            True(
                legacy.Contains(
                    "http://127.0.0.3:18831/bridge/",
                    StringComparer.Ordinal),
                "Previous installation endpoint was not retained as a migration source.");
            True(
                legacy.Contains(
                    "http://127.0.0.3:18830/bridge/",
                    StringComparer.Ordinal),
                "Historical production default was not retained for stale extension migration.");
            False(
                legacy.Contains(
                    "http://127.0.0.3:18832/bridge/",
                    StringComparer.Ordinal),
                "Current installation endpoint must not be classified as legacy.");
        });

    await RunAsync(
        "Chrome Bridge extension is Zagent-branded and endpoint-configurable",
        async () =>
        {
            var manifestPath = Path.Combine(
                engineRoot,
                "extension",
                "manifest.json");

            using var manifest = JsonDocument.Parse(
                await File.ReadAllTextAsync(manifestPath));

            Equal(
                "Zagent Chrome Bridge",
                manifest.RootElement
                    .GetProperty("name")
                    .GetString());

            Equal(
                "1.4.0",
                manifest.RootElement
                    .GetProperty("version")
                    .GetString());

            var hosts = manifest.RootElement
                .GetProperty("host_permissions")
                .EnumerateArray()
                .Select(item => item.GetString() ?? "")
                .ToArray();

            True(
                hosts.Contains(
                    "http://127.0.0.3/*",
                    StringComparer.Ordinal),
                "Extension does not allow Zagent loopback host.");

            var background = await File.ReadAllTextAsync(
                Path.Combine(
                    engineRoot,
                    "extension",
                    "background.js"));

            var bridgeConfigPath = Path.Combine(
                engineRoot,
                "extension",
                "bridge-config.json");

            using var bridgeConfig = JsonDocument.Parse(
                await File.ReadAllTextAsync(bridgeConfigPath));

            Equal(
                "DEVELOPMENT",
                bridgeConfig.RootElement
                    .GetProperty("environment")
                    .GetString());
            Equal(
                "http://127.0.0.3:19030/bridge/",
                bridgeConfig.RootElement
                    .GetProperty("defaultBase")
                    .GetString());

            var legacyBases = bridgeConfig.RootElement
                .GetProperty("legacyBases")
                .EnumerateArray()
                .Select(item => item.GetString() ?? "")
                .ToArray();

            True(
                legacyBases.Contains(
                    "http://127.0.0.3:18830/bridge/",
                    StringComparer.Ordinal),
                "Development bridge config must migrate stale production endpoint.");
            False(
                legacyBases.Contains(
                    "http://127.0.0.3:19030/bridge/",
                    StringComparer.Ordinal),
                "Development bridge default endpoint must never be classified as legacy.");

            True(
                background.Contains(
                    "bridge-config.json",
                    StringComparison.Ordinal),
                "Environment-aware bridge config loader missing.");

            True(
                background.Contains(
                    "zagentBridgeBase",
                    StringComparison.Ordinal),
                "Configurable bridge endpoint override missing.");

            False(
                background.Contains(
                    "const DEFAULT_BASE",
                    StringComparison.Ordinal),
                "Hard-coded Chrome Bridge default endpoint remains in worker.");

            False(
                background.Contains(
                    "Zohr",
                    StringComparison.OrdinalIgnoreCase),
                "Legacy branding remains in extension worker.");
        });

    await RunAsync(
        "coordinator starts Web with Registry Ready and Job Object ownership",
        async () =>
        {
            await coordinator.PrepareAsync(
                options,
                version: "2.2.10-zagent.1",
                productionApproved: true);

            var start = await coordinator.StartAsync(
                options,
                TimeSpan.FromSeconds(15));

            True(
                start.Success,
                start.Message ?? "Web failed to start.");

            True(
                registry.TryGet(
                    WebAgentManifestFactory.AgentId,
                    out var registered) &&
                registered is not null,
                "Web registry entry missing.");

            Equal(
                AgentHealthState.Ready,
                registered!.Health);

            True(
                supervisor.TryGetSnapshot(
                    WebProcessFactory.ProcessId,
                    out var process) &&
                process is not null,
                "Web process snapshot missing.");

            Equal(
                AgentProcessState.Running,
                process!.State);

            True(
                process.ProcessTreeOwned,
                "Web Node process is not Job Object owned.");
        });

    var mcpUri = WebAgentCoordinator.BuildMcpUri(options);

    await RunAsync(
        "runtime exposes exactly 151 frozen Web tools",
        async () =>
        {
            var runtimeTools = await ListToolsAsync(
                http,
                mcpUri);

            var expected = WebAgentManifestFactory.KnownToolNames
                .OrderBy(
                    item => item,
                    StringComparer.Ordinal)
                .ToArray();

            Equal(151, runtimeTools.Length);
            Equal(
                string.Join("\n", expected),
                string.Join("\n", runtimeTools));

            await File.WriteAllTextAsync(
                Path.Combine(
                    devRoot,
                    "agents",
                    "web",
                    "runtime-tools.snapshot.json"),
                JsonSerializer.Serialize(
                    new
                    {
                        version = "2.2.10-zagent.1",
                        count = runtimeTools.Length,
                        tools = runtimeTools
                    },
                    new JsonSerializerOptions
                    {
                        WriteIndented = true
                    }));
        });

    await RunAsync(
        "visual latest returns MCP image content with session provenance",
        async () =>
        {
            var sourcePath = Path.Combine(
                options.DataRoot,
                "visual-mcp-test.png");
            Directory.CreateDirectory(
                options.DataRoot);

            // Valid 1x1 transparent PNG.
            await File.WriteAllBytesAsync(
                sourcePath,
                Convert.FromBase64String(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="));

            using var ingest = await RpcAsync(
                http,
                mcpUri,
                new
                {
                    jsonrpc = "2.0",
                    id = "visual-ingest",
                    method = "tools/call",
                    @params = new
                    {
                        name = "web_visual_ingest",
                        arguments = new
                        {
                            path = sourcePath,
                            source = "web",
                            kind = "mcp-image-test",
                            sessionId =
                                "web-visual-test-session"
                        }
                    }
                });

            var ingestResult =
                ingest.RootElement
                    .GetProperty("result");
            False(
                ingestResult.TryGetProperty(
                    "isError",
                    out var ingestError) &&
                ingestError.ValueKind ==
                    JsonValueKind.True,
                ingestResult.ToString());

            var ingestContent =
                ingestResult
                    .GetProperty("content")
                    .EnumerateArray()
                    .ToArray();

            True(
                ingestContent.Any(
                    item =>
                        item.TryGetProperty(
                            "type",
                            out var type) &&
                        type.GetString() ==
                            "image" &&
                        item.TryGetProperty(
                            "data",
                            out var data) &&
                        !string.IsNullOrWhiteSpace(
                            data.GetString())),
                "visual ingest did not return MCP image content.");

            using var latest = await RpcAsync(
                http,
                mcpUri,
                new
                {
                    jsonrpc = "2.0",
                    id = "visual-latest",
                    method = "tools/call",
                    @params = new
                    {
                        name = "web_visual_latest",
                        arguments = new
                        {
                            source = "web"
                        }
                    }
                });

            var latestResult =
                latest.RootElement
                    .GetProperty("result");
            var latestContent =
                latestResult
                    .GetProperty("content")
                    .EnumerateArray()
                    .ToArray();

            True(
                latestContent.Any(
                    item =>
                        item.TryGetProperty(
                            "type",
                            out var type) &&
                        type.GetString() ==
                            "image"),
                "visual latest did not return MCP image content.");

            var text = latestContent
                .Where(
                    item =>
                        item.TryGetProperty(
                            "text",
                            out _))
                .Select(
                    item =>
                        item.GetProperty(
                            "text").GetString() ?? "")
                .FirstOrDefault() ?? "";

            True(
                text.Contains(
                    "web-visual-test-session",
                    StringComparison.Ordinal),
                "visual latest lost session provenance.");
        });

    await RunAsync(
        "visual feedback loop captures before and after through managed Chrome",
        async () =>
        {
            await CallToolAsync(
                http,
                mcpUri,
                "web_browser_start",
                new
                {
                    headless = true
                });

            try
            {
                using var snapshot = await RpcAsync(
                    http,
                    mcpUri,
                    new
                    {
                        jsonrpc = "2.0",
                        id = "visual-snapshot",
                        method = "tools/call",
                        @params = new
                        {
                            name = "web_visual_snapshot",
                            arguments = new
                            {
                                name = "loop-before",
                                label = "loop-before",
                                fullPage = false,
                                sessionId =
                                    "feedback-loop-session"
                            }
                        }
                    });

                var snapshotContent =
                    snapshot.RootElement
                        .GetProperty("result")
                        .GetProperty("content")
                        .EnumerateArray()
                        .ToArray();

                True(
                    snapshotContent.Any(
                        item =>
                            item.TryGetProperty(
                                "type",
                                out var type) &&
                            type.GetString() ==
                                "image"),
                    "visual snapshot did not return an image.");

                using var feedback = await RpcAsync(
                    http,
                    mcpUri,
                    new
                    {
                        jsonrpc = "2.0",
                        id = "visual-feedback",
                        method = "tools/call",
                        @params = new
                        {
                            name =
                                "web_visual_act_and_observe",
                            arguments = new
                            {
                                action = "wait",
                                milliseconds = 25,
                                label = "feedback-loop",
                                sessionId =
                                    "feedback-loop-session"
                            }
                        }
                    });

                var feedbackContent =
                    feedback.RootElement
                        .GetProperty("result")
                        .GetProperty("content")
                        .EnumerateArray()
                        .ToArray();

                True(
                    feedbackContent.Any(
                        item =>
                            item.TryGetProperty(
                                "type",
                                out var type) &&
                            type.GetString() ==
                                "image"),
                    "feedback loop did not return post-action image.");

                var feedbackText =
                    feedbackContent
                        .Where(
                            item =>
                                item.TryGetProperty(
                                    "text",
                                    out _))
                        .Select(
                            item =>
                                item.GetProperty(
                                    "text").GetString() ??
                                "")
                        .FirstOrDefault() ??
                    "";

                True(
                    feedbackText.Contains(
                        "observe-reason-act-observe",
                        StringComparison.Ordinal),
                    "feedback loop marker missing.");
                True(
                    feedbackText.Contains(
                        "feedback-loop-session",
                        StringComparison.Ordinal),
                    "feedback loop lost session provenance.");
            }
            finally
            {
                await CallToolAsync(
                    http,
                    mcpUri,
                    "web_browser_stop",
                    new { });
            }
        });

    await RunAsync(
        "health ping and runtime metadata are normalized",
        async () =>
        {
            var health = await healthProbe.ProbeAsync(
                WebAgentCoordinator.BuildHealthUri(options));

            True(
                health.Ready,
                health.Error ?? "Web health failed.");
            Equal(
                "Zagent Web",
                health.Service);
            Equal(
                "2.2.10-zagent.1",
                health.Version);
            False(
                health.NativeAttached,
                "Acceptance test must not attach user Chrome.");

            using var ping = await CallToolAsync(
                http,
                mcpUri,
                "web_ping",
                new { });

            True(ping.Success, ping.Text);
            True(
                ping.Text.Contains(
                    "Zagent Web",
                    StringComparison.Ordinal),
                "web_ping missing Zagent identity.");
            True(
                ping.Text.Contains(
                    "2.2.10-zagent.1",
                    StringComparison.Ordinal),
                "web_ping missing Zagent integration version.");

            using var runtime = await CallToolAsync(
                http,
                mcpUri,
                "web_runtime_info",
                new { });

            True(runtime.Success, runtime.Text);
            True(
                runtime.Text.Contains(
                    "2.2.10-zagent.1",
                    StringComparison.Ordinal),
                "web_runtime_info version mismatch.");
        });

    await RunAsync(
        "session state resolves under Zagent runtime data root",
        async () =>
        {
            using var status = await CallToolAsync(
                http,
                mcpUri,
                "web_session_status",
                new
                {
                    sessionId = "phase6-safe-session"
                });

            True(status.Success, status.Text);

            var expectedSessionPath = Path.Combine(
                options.RuntimeRoot,
                "sessions",
                "phase6-safe-session.storage.json");

            Equal(
                Path.GetFullPath(expectedSessionPath),
                Path.GetFullPath(
                    FindStringProperty(
                        status.Text,
                        "storagePath")
                    ?? throw new InvalidOperationException(
                        "storagePath missing from session status.")));
        });

    await RunAsync(
        "native Chrome detection and profile discovery are read-only",
        async () =>
        {
            using var detect = await CallToolAsync(
                http,
                mcpUri,
                "web_native_chrome_detect",
                new { });

            True(detect.Success, detect.Text);

            using var profiles = await CallToolAsync(
                http,
                mcpUri,
                "web_chrome_profiles",
                new { });

            True(profiles.Success, profiles.Text);

            // These tools may inspect local Chrome metadata but must not
            // attach, launch, close, or authorize Chrome.
            var health = await healthProbe.ProbeAsync(
                WebAgentCoordinator.BuildHealthUri(options));

            False(
                health.NativeAttached,
                "Read-only Chrome discovery unexpectedly attached Chrome.");
        });

    await RunAsync(
        "production bridge mode fails closed before pairing",
        async () =>
        {
            var stop = await coordinator.StopAsync();
            True(
                stop.Success,
                stop.Message ?? "Web stop failed.");

            var protectedOptions = CreateOptions(
                bridgeRequired: true,
                nativeAutoAttach: false,
                nativeAttachOnDemand: false);

            var writer = new WebConfigurationWriter();
            await writer.WriteAsync(protectedOptions);

            var start = await supervisor.StartAsync(
                WebProcessFactory.ProcessId);

            True(
                start.Success,
                start.Message ?? "Protected Web restart failed.");

            await WaitUntilAsync(
                async () =>
                    (await healthProbe.ProbeAsync(
                        WebAgentCoordinator.BuildHealthUri(
                            protectedOptions))).Ready,
                TimeSpan.FromSeconds(15));

            var protectedHealth =
                await healthProbe.ProbeAsync(
                    WebAgentCoordinator.BuildHealthUri(
                        protectedOptions));

            True(protectedHealth.Ready, "Protected Web unhealthy.");
            True(
                protectedHealth.BridgeRequired,
                "Bridge protection was not enabled.");
            False(
                protectedHealth.NativeAttached,
                "Protected startup must not attach Chrome without trusted bridge.");

            var protectedMcp =
                WebAgentCoordinator.BuildMcpUri(
                    protectedOptions);

            using var bridgeStatus = await CallToolAsync(
                http,
                protectedMcp,
                "web_bridge_pair_status",
                new { });

            True(
                bridgeStatus.Success,
                bridgeStatus.Text);
            Equal(
                $"http://127.0.0.3:{port}/bridge/",
                FindStringProperty(
                    bridgeStatus.Text,
                    "expectedBridgeEndpoint"));
            Equal(
                "DEVELOPMENT",
                FindStringProperty(
                    bridgeStatus.Text,
                    "bridgeEnvironment"));

            using var preflightPing = await CallToolAsync(
                http,
                protectedMcp,
                "web_ping",
                new { });

            True(
                preflightPing.Success,
                "Preflight web_ping must remain available before pairing.");

            using var blockedPageAction = await CallToolAsync(
                http,
                protectedMcp,
                "web_get_url",
                new { },
                expectError: true);

            True(
                blockedPageAction.IsError,
                "Page action was not blocked before pairing.");
            True(
                !string.IsNullOrWhiteSpace(
                    blockedPageAction.Text),
                "Bridge fail-closed response was empty.");
        });

    await RunAsync(
        "Web restart stays supervised and stop publishes Offline",
        async () =>
        {
            var restart = await supervisor.RestartAsync(
                WebProcessFactory.ProcessId);

            True(
                restart.Success,
                restart.Message ?? "Web restart failed.");

            await WaitUntilAsync(
                async () =>
                    (await healthProbe.ProbeAsync(
                        WebAgentCoordinator.BuildHealthUri(
                            CreateOptions(
                                bridgeRequired: true,
                                nativeAutoAttach: false,
                                nativeAttachOnDemand: false)))).Ready,
                TimeSpan.FromSeconds(15));

            True(
                supervisor.TryGetSnapshot(
                    WebProcessFactory.ProcessId,
                    out var running) &&
                running is not null &&
                running.State == AgentProcessState.Running &&
                running.ProcessTreeOwned,
                "Web did not return to Running/owned state.");

            var stop = await coordinator.StopAsync();
            True(
                stop.Success,
                stop.Message ?? "Web stop failed.");

            True(
                registry.TryGet(
                    WebAgentManifestFactory.AgentId,
                    out var stopped) &&
                stopped?.Health == AgentHealthState.Offline,
                "Registry did not publish Web Offline.");

            supervisor.TryGetSnapshot(
                WebProcessFactory.ProcessId,
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
        ? $"WEB_TEST_PASS passed={passed} failed={failed}"
        : $"WEB_TEST_FAIL passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

WebIntegrationOptions CreateOptions(
    bool bridgeRequired,
    bool nativeAutoAttach,
    bool nativeAttachOnDemand) =>
    new(
        NodeExecutable: node,
        EngineRoot: engineRoot,
        DataRoot: Path.Combine(validationRoot, "data"),
        ConfigRoot: Path.Combine(validationRoot, "data", "config"),
        RuntimeRoot: Path.Combine(validationRoot, "data", "runtime"),
        ArtifactsRoot: Path.Combine(validationRoot, "data", "artifacts"),
        LogRoot: Path.Combine(validationRoot, "data", "logs"),
        BindHost: "127.0.0.3",
        Port: port,
        Browser: "chrome",
        RuntimeMode: "native_attach",
        SessionIsolationMode: "tabs",
        ChromeExecutablePath: null,
        BridgeRequired: bridgeRequired,
        NativeAutoAttach: nativeAutoAttach,
        NativeAttachOnDemand: nativeAttachOnDemand,
        BridgeEnvironment: "DEVELOPMENT");

async Task<string[]> ListToolsAsync(
    HttpClient client,
    Uri uri)
{
    using var response = await RpcAsync(
        client,
        uri,
        new
        {
            jsonrpc = "2.0",
            id = "tools-list",
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

async Task<ToolCallResult> CallToolAsync(
    HttpClient client,
    Uri uri,
    string name,
    object arguments,
    bool expectError = false)
{
    using var response = await RpcAsync(
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
                arguments
            }
        });

    if (response.RootElement.TryGetProperty(
            "error",
            out var rpcError))
    {
        if (!expectError)
        {
            throw new InvalidOperationException(
                $"Tool '{name}' RPC error: {rpcError}");
        }

        return new ToolCallResult(
            false,
            true,
            rpcError.ToString());
    }

    var result = response.RootElement
        .GetProperty("result");

    var isError =
        result.TryGetProperty(
            "isError",
            out var isErrorElement) &&
        isErrorElement.ValueKind == JsonValueKind.True;

    var text = ExtractToolText(result);

    if (isError && !expectError)
    {
        throw new InvalidOperationException(
            $"Tool '{name}' failed: {text}");
    }

    if (!isError && expectError)
    {
        throw new InvalidOperationException(
            $"Tool '{name}' unexpectedly succeeded: {text}");
    }

    return new ToolCallResult(
        !isError,
        isError,
        text);
}

static string ExtractToolText(
    JsonElement result)
{
    if (result.TryGetProperty(
            "structuredContent",
            out var structured) &&
        structured.ValueKind is not
            JsonValueKind.Null and not
            JsonValueKind.Undefined)
    {
        return structured.ToString();
    }

    if (result.TryGetProperty(
            "content",
            out var content) &&
        content.ValueKind == JsonValueKind.Array)
    {
        var texts = content
            .EnumerateArray()
            .Where(
                item =>
                    item.TryGetProperty(
                        "text",
                        out _))
            .Select(
                item =>
                    item.GetProperty("text").GetString() ?? "")
            .Where(
                text =>
                    !string.IsNullOrWhiteSpace(text))
            .ToArray();

        if (texts.Length > 0)
        {
            return string.Join("\n", texts);
        }
    }

    return result.ToString();
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

    var mediaType =
        response.Content.Headers.ContentType?.MediaType ?? "";

    if (mediaType.Contains(
            "text/event-stream",
            StringComparison.OrdinalIgnoreCase) ||
        body.TrimStart().StartsWith(
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
                "MCP SSE response had no JSON payload.");
        }

        return JsonDocument.Parse(payloads[^1]);
    }

    return JsonDocument.Parse(body);
}

static string? FindStringProperty(
    string jsonText,
    string propertyName)
{
    try
    {
        using var document = JsonDocument.Parse(jsonText);
        return FindStringPropertyInElement(
            document.RootElement,
            propertyName);
    }
    catch (JsonException)
    {
        return null;
    }
}

static string? FindStringPropertyInElement(
    JsonElement element,
    string propertyName)
{
    if (element.ValueKind == JsonValueKind.Object)
    {
        foreach (var property in element.EnumerateObject())
        {
            if (string.Equals(
                    property.Name,
                    propertyName,
                    StringComparison.Ordinal))
            {
                return property.Value.ValueKind == JsonValueKind.String
                    ? property.Value.GetString()
                    : property.Value.ToString();
            }

            var nested = FindStringPropertyInElement(
                property.Value,
                propertyName);

            if (nested is not null)
            {
                return nested;
            }
        }
    }
    else if (element.ValueKind == JsonValueKind.Array)
    {
        foreach (var item in element.EnumerateArray())
        {
            var nested = FindStringPropertyInElement(
                item,
                propertyName);

            if (nested is not null)
            {
                return nested;
            }
        }
    }
    else if (element.ValueKind == JsonValueKind.String)
    {
        var raw = element.GetString();

        if (!string.IsNullOrWhiteSpace(raw))
        {
            try
            {
                using var nestedDocument =
                    JsonDocument.Parse(raw);

                return FindStringPropertyInElement(
                    nestedDocument.RootElement,
                    propertyName);
            }
            catch (JsonException)
            {
            }
        }
    }

    return null;
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

static int FindFreeDevelopmentPort(string host)
{
    var address = IPAddress.Parse(host);

    for (var candidate = 18900;
        candidate <= 18999;
        candidate++)
    {
        TcpListener? listener = null;

        try
        {
            listener = new TcpListener(
                address,
                candidate);
            listener.Start();
            return candidate;
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
        "No free Development Gateway port available.");
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

sealed record ToolCallResult(
    bool Success,
    bool IsError,
    string Text) : IDisposable
{
    public void Dispose()
    {
    }
}
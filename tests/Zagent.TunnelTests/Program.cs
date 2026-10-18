using System.Net;
using System.Net.Http.Json;
using System.Net.Sockets;
using System.Text.Json;
using Zagent.Core.Agents.Tunnel;
using Zagent.Core.Registry;
using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;

var passed = 0;
var failed = 0;

var devRoot = Environment.GetEnvironmentVariable("ZAGENT_DEV_ROOT")
    ?? throw new InvalidOperationException("ZAGENT_DEV_ROOT is not set.");
var python = Environment.GetEnvironmentVariable("ZAGENT_TEST_PYTHON")
    ?? throw new InvalidOperationException("ZAGENT_TEST_PYTHON is not set.");
var transportClient =
    Environment.GetEnvironmentVariable("ZAGENT_TEST_TUNNEL_CLIENT");

const string testDeviceId =
    "11111111-2222-3333-4444-555555555555";
var testDeviceBinding = new string('a', 64);

var engineRoot = Path.Combine(
    devRoot,
    "agents",
    "tunnel",
    "engine");
var mockScript = Path.Combine(
    devRoot,
    "tests",
    "Zagent.TunnelTests",
    "mock_mcp.py");

var validationRoot = Path.Combine(
    devRoot,
    "_validation",
    "phase4-tunnel",
    Guid.NewGuid().ToString("N"));

Directory.CreateDirectory(validationRoot);

using var http = new HttpClient(
    new SocketsHttpHandler
    {
        UseProxy = false
    })
{
    Timeout = TimeSpan.FromSeconds(5)
};

try
{
    await RunAsync("tunnel manifest registers in production registry", async () =>
    {
        var manifest = TunnelAgentManifestFactory.Create(
            "4.1.0-zagent.3",
            "127.0.0.3",
            18910);

        Equal("system.tunnel", manifest.Agent.Id);
        Equal(8, manifest.Capabilities.Count);

        var registry = new CapabilityRegistry();
        var result = registry.Register(
            manifest,
            productionApproved: true);

        True(result.Success, string.Join("; ", result.Errors));
        Equal(
            1,
            registry.FindOwners("system.tunnel.status").Count);

        await Task.CompletedTask;
    });

    await RunAsync("tunnel config contains no credential fields", async () =>
    {
        var configRoot = Path.Combine(
            validationRoot,
            "config-no-secret");
        var runtimeRoot = Path.Combine(
            validationRoot,
            "runtime-no-secret");

        var options = new TunnelIntegrationOptions(
            PythonExecutable: python,
            EngineRoot: engineRoot,
            ConfigRoot: configRoot,
            RuntimeRoot: runtimeRoot,
            ChatLogPath: Path.Combine(
                runtimeRoot,
                "chat_log.jsonl"),
            BindHost: "127.0.0.3",
            RouterPort: 18911);

        var writer = new TunnelConfigurationWriter();
        await writer.WriteAsync(
            options,
            Array.Empty<TunnelServiceDefinition>(),
            pluginConfigured: true);

        var tunnelJson = await File.ReadAllTextAsync(
            Path.Combine(configRoot, "tunnel.json"));

        using var tunnelDocument =
            JsonDocument.Parse(tunnelJson);

        True(
            tunnelDocument.RootElement
                .GetProperty("plugin")
                .GetProperty("configured")
                .GetBoolean(),
            "Tunnel config did not expose plugin configured state.");

        False(
            tunnelJson.Contains(
                "api_key",
                StringComparison.OrdinalIgnoreCase),
            "Tunnel config unexpectedly contains API key material.");
        False(
            tunnelJson.Contains(
                "tunnel_id",
                StringComparison.OrdinalIgnoreCase),
            "Tunnel config unexpectedly contains tunnel ID material.");
        False(
            File.Exists(Path.Combine(engineRoot, ".env")),
            "Zagent Tunnel engine should not require an .env file.");
    });

    await RunAsync("transport process receives secrets only through environment", async () =>
    {
        if (string.IsNullOrWhiteSpace(transportClient) ||
            !File.Exists(transportClient))
        {
            throw new InvalidOperationException(
                "ZAGENT_TEST_TUNNEL_CLIENT is unavailable.");
        }

        var definition = TunnelProcessFactory.CreateTransport(
            new TunnelTransportOptions(
                ClientExecutable: transportClient,
                WorkingDirectory:
                    Path.GetDirectoryName(transportClient)
                    ?? validationRoot,
                TunnelId: "tunnel_test_only",
                ApiKey: "test-secret-not-persisted",
                HealthListenAddress: "127.0.0.3:18912",
                RouterMcpUrl: "http://127.0.0.3:18910/mcp"));

        True(
            definition.EnvironmentVariables is not null,
            "Transport environment is missing.");

        Equal(
            "tunnel_test_only",
            definition.EnvironmentVariables![
                "CONTROL_PLANE_TUNNEL_ID"]);
        Equal(
            "test-secret-not-persisted",
            definition.EnvironmentVariables[
                "CONTROL_PLANE_API_KEY"]);

        False(
            definition.Arguments.Any(
                value => value.Contains(
                    "test-secret-not-persisted",
                    StringComparison.Ordinal)),
            "API key leaked into command-line arguments.");

        await Task.CompletedTask;
    });


    await RunAsync("coordinator prepares registry and supervisor", async () =>
    {
        var routerPort = FindFreeDevelopmentPort("127.0.0.3");
        var scenarioRoot = Path.Combine(
            validationRoot,
            "coordinator-prepare");

        var options = new TunnelIntegrationOptions(
            PythonExecutable: python,
            EngineRoot: engineRoot,
            ConfigRoot: Path.Combine(scenarioRoot, "config"),
            RuntimeRoot: Path.Combine(scenarioRoot, "runtime"),
            ChatLogPath: Path.Combine(scenarioRoot, "logs", "chat.jsonl"),
            BindHost: "127.0.0.3",
            RouterPort: routerPort);

        var registry = new CapabilityRegistry();
        await using var supervisor = new NativeAgentSupervisor(
            acquireInstanceLease: false);

        var coordinator = new TunnelAgentCoordinator(
            registry,
            supervisor);

        await coordinator.PrepareAsync(
            options,
            Array.Empty<TunnelServiceDefinition>(),
            version: "4.1.0-zagent.3",
            productionApproved: true);

        True(
            registry.TryGet(
                TunnelAgentManifestFactory.AgentId,
                out var registered) &&
            registered is not null,
            "Tunnel logical agent was not registered.");

        True(
            supervisor.TryGetSnapshot(
                TunnelProcessFactory.RouterProcessId,
                out var router) &&
            router is not null,
            "Tunnel router process was not registered.");

        Equal(
            AgentProcessState.Stopped,
            router!.State);
        Equal(
            AgentHealthState.Unknown,
            registered!.Health);
    });

    await RunAsync("router discovers and invokes mock mcp through native supervisor", async () =>
    {
        var routerPort = FindFreeDevelopmentPort("127.0.0.3");
        var mockPort = FindFreeEphemeralPort(IPAddress.Loopback);

        var scenarioRoot = Path.Combine(
            validationRoot,
            "live-routing");
        var configRoot = Path.Combine(scenarioRoot, "config");
        var runtimeRoot = Path.Combine(scenarioRoot, "runtime");
        var chatLog = Path.Combine(scenarioRoot, "logs", "chat.jsonl");

        var options = new TunnelIntegrationOptions(
            PythonExecutable: python,
            EngineRoot: engineRoot,
            ConfigRoot: configRoot,
            RuntimeRoot: runtimeRoot,
            ChatLogPath: chatLog,
            BindHost: "127.0.0.3",
            RouterPort: routerPort,
            DeviceId: testDeviceId,
            DeviceName: "ZISB Test Device",
            DeviceAlias: "Test Laptop",
            DeviceFingerprint: new string('b', 64),
            InstallationId: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            DeviceBinding: testDeviceBinding,
            IdentityEnforcement: "mandatory",
            PluginAccessEnforcement: "disabled");

        await using var supervisor = new NativeAgentSupervisor(
            acquireInstanceLease: false);

        supervisor.Register(
            new AgentProcessDefinition(
                AgentId: "test.mock-mcp",
                ExecutablePath: python,
                Arguments:
                [
                    mockScript,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    mockPort.ToString()
                ],
                WorkingDirectory:
                    Path.GetDirectoryName(mockScript),
                GracefulShutdownSeconds: 0));

        var registry = new CapabilityRegistry();
        var healthProbe = new TunnelRouterHealthProbe(http);
        var coordinator = new TunnelAgentCoordinator(
            registry,
            supervisor,
            healthProbe: healthProbe);

        await coordinator.PrepareAsync(
            options,
            [
                new TunnelServiceDefinition(
                    Id: "test_mock",
                    Name: "Mock MCP",
                    Namespace: "mock",
                    Url: $"http://127.0.0.1:{mockPort}/mcp",
                    TimeoutSeconds: 3)
            ],
            version: "4.1.0-zagent.1",
            productionApproved: true);

        var mockStart = await supervisor.StartAsync(
            "test.mock-mcp");
        True(
            mockStart.Success,
            mockStart.Message ?? "Mock MCP failed to start.");

        await WaitForHttpAsync(
            new Uri($"http://127.0.0.1:{mockPort}/healthz"),
            TimeSpan.FromSeconds(8));

        var routerStart = await coordinator.StartAsync(
            options,
            startTransport: false,
            readyTimeout: TimeSpan.FromSeconds(12));
        True(
            routerStart.Success,
            routerStart.Message ?? "Router failed to start.");

        True(
            registry.TryGet(
                TunnelAgentManifestFactory.AgentId,
                out var liveRegistered) &&
            liveRegistered?.Health == AgentHealthState.Ready,
            "Coordinator did not publish Ready health to Capability Registry.");

        TunnelRouterHealthSnapshot? health = null;

        await WaitUntilAsync(
            async () =>
            {
                health = await healthProbe.ProbeAsync(
                    new Uri(
                        $"http://127.0.0.3:{routerPort}/healthz"));
                return health.Ready && health.ToolCount >= 9;
            },
            TimeSpan.FromSeconds(12));

        True(health is not null && health.Ready, "Router health is not ready.");
        True(
            health!.ToolCount >= 9,
            $"Expected at least 9 tools, actual {health.ToolCount}.");

        var mcpUri = new Uri(
            $"http://127.0.0.3:{routerPort}/mcp");

        using var initialize = await RpcAsync(
            mcpUri,
            new
            {
                jsonrpc = "2.0",
                id = "init-1",
                method = "initialize",
                @params = new
                {
                    protocolVersion = "2025-06-18",
                    capabilities = new { },
                    clientInfo = new
                    {
                        name = "Zagent Tunnel Test",
                        version = "1.0"
                    }
                }
            });

        Equal(
            "Zagent Tunnel",
            initialize.RootElement
                .GetProperty("result")
                .GetProperty("serverInfo")
                .GetProperty("name")
                .GetString());

        using var tools = await RpcAsync(
            mcpUri,
            new
            {
                jsonrpc = "2.0",
                id = "tools-1",
                method = "tools/list",
                @params = new { }
            });

        var toolNames = tools.RootElement
            .GetProperty("result")
            .GetProperty("tools")
            .EnumerateArray()
            .Select(
                item => item.GetProperty("name").GetString() ?? "")
            .ToHashSet(StringComparer.Ordinal);

        True(toolNames.Contains("mock_ping"), "mock_ping was not discovered.");
        True(
            toolNames.Contains("zagent_router_status"),
            "zagent_router_status was not exposed.");
        True(
            toolNames.Contains("zagent_task_submit"),
            "zagent_task_submit was not exposed.");
        True(
            toolNames.Contains("zagent_identity_session_bind"),
            "zagent_identity_session_bind was not exposed.");
        True(
            toolNames.Contains("zagent_identity_verify_target"),
            "zagent_identity_verify_target was not exposed.");
        True(
            toolNames.Contains("zagent_identity_list_devices"),
            "zagent_identity_list_devices was not exposed.");

        using var identityStatus =
            await CallToolJsonAsync(
                mcpUri,
                "zagent_identity_status",
                new { session_id = "phase4-sync" });
        Equal(
            "trusted",
            identityStatus.RootElement
                .GetProperty("device")
                .GetProperty("trust_state")
                .GetString());
        Equal(
            "mandatory",
            identityStatus.RootElement
                .GetProperty("enforcement_mode")
                .GetString());

        using var challengeResponse =
            await http.PostAsync(
                new Uri(
                    $"http://127.0.0.3:{routerPort}/router/identity/challenge"),
                content: null);
        challengeResponse.EnsureSuccessStatusCode();
        using var challenge =
            JsonDocument.Parse(
                await challengeResponse.Content.ReadAsStringAsync());
        var challengeId =
            challenge.RootElement
                .GetProperty("challenge_id")
                .GetString()
            ?? throw new InvalidOperationException(
                "Identity challenge id missing.");

        using var proofResponse =
            await http.PostAsync(
                new Uri(
                    $"http://127.0.0.3:{routerPort}/router/identity/proof/{challengeId}"),
                content: null);
        proofResponse.EnsureSuccessStatusCode();
        using var proof =
            JsonDocument.Parse(
                await proofResponse.Content.ReadAsStringAsync());

        using var verifyResponse =
            await http.PostAsJsonAsync(
                new Uri(
                    $"http://127.0.0.3:{routerPort}/router/identity/verify"),
                new
                {
                    challenge_id = challengeId,
                    proof =
                        proof.RootElement
                            .GetProperty("proof")
                            .GetString()
                });
        verifyResponse.EnsureSuccessStatusCode();
        using var verifiedProof =
            JsonDocument.Parse(
                await verifyResponse.Content.ReadAsStringAsync());
        True(
            verifiedProof.RootElement
                .GetProperty("trusted")
                .GetBoolean(),
            "Valid identity challenge proof was rejected.");

        using var unboundCall = await RpcAsync(
            mcpUri,
            new
            {
                jsonrpc = "2.0",
                id = "unbound-call",
                method = "tools/call",
                @params = new
                {
                    name = "mock_ping",
                    arguments = new
                    {
                        value = "must-not-execute"
                    },
                    _meta = new
                    {
                        session_id = "phase4-unbound"
                    }
                }
            });
        True(
            unboundCall.RootElement
                .GetProperty("error")
                .GetProperty("message")
                .GetString()!
                .Contains(
                    "SESSION_IDENTITY_REQUIRED",
                    StringComparison.Ordinal),
            "Unbound session was not rejected before execution.");

        await BindSessionAsync(
            mcpUri,
            "phase4-sync",
            "Test Laptop",
            testDeviceId);
        await BindSessionAsync(
            mcpUri,
            "phase4-session-a",
            "Test Laptop",
            testDeviceId);
        await BindSessionAsync(
            mcpUri,
            "phase4-session-long",
            "Test Laptop",
            testDeviceId);
        await BindSessionAsync(
            mcpUri,
            "phase4-session-b",
            "Test Laptop",
            testDeviceId);

        using var wrongTarget = await RpcAsync(
            mcpUri,
            new
            {
                jsonrpc = "2.0",
                id = "wrong-target",
                method = "tools/call",
                @params = new
                {
                    name = "mock_ping",
                    arguments = new
                    {
                        value = "must-not-execute"
                    },
                    _meta = new
                    {
                        session_id = "phase4-sync",
                        target_device_id =
                            "99999999-8888-7777-6666-555555555555"
                    }
                }
            });
        True(
            wrongTarget.RootElement
                .GetProperty("error")
                .GetProperty("message")
                .GetString()!
                .Contains(
                    "IDENTITY_MISMATCH",
                    StringComparison.Ordinal),
            "Wrong target_device_id was not rejected.");

        using var call = await RpcAsync(
            mcpUri,
            new
            {
                jsonrpc = "2.0",
                id = "call-1",
                method = "tools/call",
                @params = new
                {
                    name = "mock_ping",
                    arguments = new
                    {
                        value = "hello-zagent"
                    },
                    _meta = new
                    {
                        session_id = "phase4-sync"
                    }
                }
            });

        var callText = call.RootElement.ToString();
        True(
            callText.Contains(
                "hello-zagent",
                StringComparison.Ordinal),
            "Tool call did not traverse the router.");

        using var asyncSubmit = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_submit",
            new
            {
                tool_name = "mock_ping",
                arguments = new
                {
                    value = "async-zagent"
                },
                session_id = "phase4-session-a",
                idempotency_key = "phase4-idem-001",
                priority = 1
            });

        var asyncTaskId = asyncSubmit.RootElement
            .GetProperty("task_id")
            .GetString()
            ?? throw new InvalidOperationException(
                "Async task id was not returned.");

        using var asyncSubmitDuplicate = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_submit",
            new
            {
                tool_name = "mock_ping",
                arguments = new
                {
                    value = "async-zagent"
                },
                session_id = "phase4-session-a",
                idempotency_key = "phase4-idem-001",
                priority = 1
            });

        Equal(
            asyncTaskId,
            asyncSubmitDuplicate.RootElement
                .GetProperty("task_id")
                .GetString());

        await WaitUntilAsync(
            async () =>
            {
                using var status = await CallToolJsonAsync(
                    mcpUri,
                    "zagent_task_status",
                    new
                    {
                        task_id = asyncTaskId
                    });

                var state = status.RootElement
                    .GetProperty("task")
                    .GetProperty("state")
                    .GetString();

                return string.Equals(
                    state,
                    "succeeded",
                    StringComparison.Ordinal);
            },
            TimeSpan.FromSeconds(8));

        using var asyncResult = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_result",
            new
            {
                task_id = asyncTaskId
            });

        True(
            asyncResult.RootElement.ToString().Contains(
                "async-zagent",
                StringComparison.Ordinal),
            "Async task result was not persisted.");

        using var longSubmit = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_submit",
            new
            {
                tool_name = "mock_sleep",
                arguments = new
                {
                    delay_ms = 3500,
                    timeout_seconds = 5
                },
                session_id = "phase4-session-long",
                idempotency_key = "phase4-long-timeout-001",
                priority = 1
            });

        var longTaskId = longSubmit.RootElement
            .GetProperty("task_id")
            .GetString()
            ?? throw new InvalidOperationException(
                "Long task id was not returned.");

        await WaitUntilAsync(
            async () =>
            {
                using var status = await CallToolJsonAsync(
                    mcpUri,
                    "zagent_task_status",
                    new
                    {
                        task_id = longTaskId
                    });

                var state = status.RootElement
                    .GetProperty("task")
                    .GetProperty("state")
                    .GetString();

                if (string.Equals(state, "failed", StringComparison.Ordinal))
                {
                    throw new InvalidOperationException(
                        "Long task failed before its tool timeout contract elapsed.");
                }

                return string.Equals(
                    state,
                    "succeeded",
                    StringComparison.Ordinal);
            },
            TimeSpan.FromSeconds(8));

        using var longResult = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_result",
            new
            {
                task_id = longTaskId
            });

        True(
            longResult.RootElement.ToString().Contains(
                "3500",
                StringComparison.Ordinal),
            "Per-tool long-running timeout override did not preserve the result.");

        using var sleepSubmit = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_submit",
            new
            {
                tool_name = "mock_sleep",
                arguments = new
                {
                    delay_ms = 4000
                },
                session_id = "phase4-session-b",
                idempotency_key = "phase4-cancel-001",
                priority = 1
            });

        var sleepTaskId = sleepSubmit.RootElement
            .GetProperty("task_id")
            .GetString()
            ?? throw new InvalidOperationException(
                "Sleep task id was not returned.");

        await WaitUntilAsync(
            async () =>
            {
                using var status = await CallToolJsonAsync(
                    mcpUri,
                    "zagent_task_status",
                    new
                    {
                        task_id = sleepTaskId
                    });

                var state = status.RootElement
                    .GetProperty("task")
                    .GetProperty("state")
                    .GetString();

                return state is "running" or "queued" or
                    "waiting_capacity" or "waiting_lock";
            },
            TimeSpan.FromSeconds(5));

        using var cancel = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_cancel",
            new
            {
                task_id = sleepTaskId
            });

        True(
            cancel.RootElement
                .GetProperty("ok")
                .GetBoolean(),
            "Task cancellation was rejected.");

        await WaitUntilAsync(
            async () =>
            {
                using var status = await CallToolJsonAsync(
                    mcpUri,
                    "zagent_task_status",
                    new
                    {
                        task_id = sleepTaskId
                    });

                var state = status.RootElement
                    .GetProperty("task")
                    .GetProperty("state")
                    .GetString();

                return string.Equals(
                    state,
                    "cancelled",
                    StringComparison.Ordinal);
            },
            TimeSpan.FromSeconds(8));

        using var telemetry = await CallToolJsonAsync(
            mcpUri,
            "zagent_telemetry_status",
            new { });

        True(
            telemetry.RootElement.ValueKind == JsonValueKind.Object,
            "Telemetry did not return an object.");

        using var sessionList = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_list",
            new
            {
                session_id = "phase4-session-a",
                limit = 20
            });

        var sessionTasks = sessionList.RootElement
            .GetProperty("tasks")
            .EnumerateArray()
            .ToArray();

        True(
            sessionTasks.Length >= 1,
            "Session-scoped task list returned no tasks.");

        True(
            sessionTasks.All(
                item =>
                    string.Equals(
                        item.GetProperty("session_id").GetString(),
                        "phase4-session-a",
                        StringComparison.Ordinal)),
            "Session-scoped task list leaked another session.");

        var restart = await supervisor.RestartAsync(
            TunnelProcessFactory.RouterProcessId);
        True(
            restart.Success,
            restart.Message ?? "Router restart failed.");

        await WaitUntilAsync(
            async () =>
            {
                var restartedHealth = await healthProbe.ProbeAsync(
                    new Uri(
                        $"http://127.0.0.3:{routerPort}/healthz"));
                return restartedHealth.Ready &&
                    restartedHealth.ToolCount >= 10;
            },
            TimeSpan.FromSeconds(12));

        using var persistedResult = await CallToolJsonAsync(
            mcpUri,
            "zagent_task_result",
            new
            {
                task_id = asyncTaskId
            });

        True(
            persistedResult.RootElement.ToString().Contains(
                "async-zagent",
                StringComparison.Ordinal),
            "Completed task result did not survive router restart.");

        var routerSnapshot = supervisor.Snapshot()
            .Single(
                item =>
                    item.AgentId ==
                    TunnelProcessFactory.RouterProcessId);

        True(
            routerSnapshot.ProcessTreeOwned,
            "Router process is not owned by Windows Job Object.");

        var tunnelStop = await coordinator.StopAsync();
        True(
            tunnelStop.Success,
            tunnelStop.Message ?? "Tunnel coordinator stop failed.");

        True(
            registry.TryGet(
                TunnelAgentManifestFactory.AgentId,
                out var stoppedRegistered) &&
            stoppedRegistered?.Health == AgentHealthState.Offline,
            "Coordinator did not publish Offline health after stop.");

        var shutdown = await supervisor.StopAllAsync();
        True(shutdown.Success, "Tunnel integration StopAll failed.");
    });
}
finally
{
    try
    {
        Directory.Delete(validationRoot, recursive: true);
    }
    catch
    {
    }
}

Console.WriteLine(
    failed == 0
        ? $"TUNNEL_TEST_PASS passed={passed} failed={failed}"
        : $"TUNNEL_TEST_FAIL passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

async Task<JsonDocument> RpcAsync(
    Uri uri,
    object payload)
{
    using var response = await http.PostAsJsonAsync(
        uri,
        payload);

    response.EnsureSuccessStatusCode();

    await using var stream =
        await response.Content.ReadAsStreamAsync();

    return await JsonDocument.ParseAsync(stream);
}

async Task<JsonDocument> CallToolJsonAsync(
    Uri uri,
    string toolName,
    object arguments)
{
    using var rpc = await RpcAsync(
        uri,
        new
        {
            jsonrpc = "2.0",
            id = Guid.NewGuid().ToString("N"),
            method = "tools/call",
            @params = new
            {
                name = toolName,
                arguments
            }
        });

    if (rpc.RootElement.TryGetProperty("error", out var rpcError))
    {
        throw new InvalidDataException(
            $"Tool '{toolName}' RPC error: {rpcError}");
    }

    var text = rpc.RootElement
        .GetProperty("result")
        .GetProperty("content")[0]
        .GetProperty("text")
        .GetString();

    if (string.IsNullOrWhiteSpace(text))
    {
        throw new InvalidDataException(
            $"Tool '{toolName}' returned no text payload.");
    }

    return JsonDocument.Parse(text);
}

async Task BindSessionAsync(
    Uri uri,
    string sessionId,
    string operatorAlias,
    string targetDeviceId)
{
    using var bound =
        await CallToolJsonAsync(
            uri,
            "zagent_identity_session_bind",
            new
            {
                session_id = sessionId,
                operator_alias = operatorAlias,
                target_device_id = targetDeviceId
            });

    True(
        bound.RootElement
            .GetProperty("bound")
            .GetBoolean(),
        $"Identity session '{sessionId}' did not bind.");
}

async Task WaitForHttpAsync(
    Uri uri,
    TimeSpan timeout)
{
    await WaitUntilAsync(
        async () =>
        {
            try
            {
                using var response = await http.GetAsync(uri);
                return response.IsSuccessStatusCode;
            }
            catch (HttpRequestException)
            {
                return false;
            }
            catch (TaskCanceledException)
            {
                return false;
            }
        },
        timeout);
}

static async Task WaitUntilAsync(
    Func<Task<bool>> predicate,
    TimeSpan timeout)
{
    var deadline = DateTime.UtcNow + timeout;

    while (DateTime.UtcNow < deadline)
    {
        if (await predicate())
        {
            return;
        }

        await Task.Delay(50);
    }

    throw new TimeoutException(
        $"Condition was not satisfied within {timeout}.");
}

static int FindFreeDevelopmentPort(string host)
{
    var address = IPAddress.Parse(host);

    for (var port = 18900; port <= 18999; port++)
    {
        TcpListener? listener = null;
        try
        {
            listener = new TcpListener(address, port);
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

static int FindFreeEphemeralPort(IPAddress address)
{
    var listener = new TcpListener(address, 0);
    listener.Start();
    try
    {
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }
    finally
    {
        listener.Stop();
    }
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
using System.Net;
using System.Net.Sockets;
using System.Net.Http.Headers;
using System.Text;
using System.Diagnostics;
using System.Text.Json;
using Zagent.Core.Agents.ArcMap;
using Zagent.Core.Agents.Files;
using Zagent.Core.Agents.Tunnel;
using Zagent.Core.Agents.Web;
using Zagent.Core.Manager;
using Zagent.Core.Registry;
using Zagent.Core.Supervision;

using Zagent.Shared.Contracts;
using Zagent.Shared.Manager;

var passed = 0;
var failed = 0;

await RunAsync(
    "manager protocol is versioned",
    () =>
    {
        Equal("1.0", ManagerProtocol.Version);
        Equal("Zagent.Manager.v1", ManagerProtocol.DefaultPipeName);
        return Task.CompletedTask;
    });

await RunAsync(
    "visual read model accepts in-root artifact and blocks path escape",
    async () =>
    {
        var tempRoot = Path.Combine(
            Path.GetTempPath(),
            "zagent-visual-manager-" +
            Guid.NewGuid().ToString("N"));
        var visualRoot = Path.Combine(tempRoot, "visual");
        var artifacts = Path.Combine(visualRoot, "artifacts");
        Directory.CreateDirectory(artifacts);
        try
        {
            var artifactPath = Path.Combine(
                artifacts,
                "viewer-test.png");
            await File.WriteAllBytesAsync(
                artifactPath,
                [1, 2, 3, 4]);

            var validManifest = JsonSerializer.Serialize(
                new
                {
                    schemaVersion = 1,
                    id = "vis-test",
                    source = "web",
                    kind = "viewport-screenshot",
                    label = "viewer-test",
                    capturedAt = DateTimeOffset.UtcNow
                        .ToString("O"),
                    artifactPath,
                    mimeType = "image/png",
                    bytes = 4L,
                    sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(new byte[] { 1, 2, 3, 4 })),
                    provenance = new
                    {
                        deviceId = "device-test",
                        deviceName = "Viewer Test Device",
                        workspaceId = "workspace-test"
                    }
                });

            await File.WriteAllTextAsync(
                Path.Combine(
                    visualRoot,
                    "latest.json"),
                validManifest);

            var reader =
                new ManagerVisualReadModel(
                    visualRoot);
            var valid =
                await reader.GetLatestAsync();

            True(
                valid.Available,
                valid.Error ??
                    "Valid visual artifact was rejected.");
            Equal(
                "device-test",
                valid.DeviceId);
            Equal(
                "workspace-test",
                valid.WorkspaceId);

            var outsidePath =
                Path.Combine(
                    tempRoot,
                    "outside.png");
            await File.WriteAllBytesAsync(
                outsidePath,
                [9, 8, 7]);

            var escapedManifest =
                JsonSerializer.Serialize(
                    new
                    {
                        schemaVersion = 1,
                        id = "vis-escape",
                        source = "web",
                        kind = "viewport-screenshot",
                        capturedAt =
                            DateTimeOffset.UtcNow
                                .ToString("O"),
                        artifactPath =
                            outsidePath,
                        mimeType =
                            "image/png",
                        bytes = 3L,
                        sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(new byte[] { 9, 8, 7 })),
                        provenance = new
                        {
                            deviceId =
                                "device-test",
                            deviceName =
                                "Viewer Test Device",
                            workspaceId =
                                "workspace-test"
                        }
                    });

            await File.WriteAllTextAsync(
                Path.Combine(
                    visualRoot,
                    "latest.json"),
                escapedManifest);

            var blocked =
                await reader.GetLatestAsync();

            False(
                blocked.Available,
                "Visual path escape was not blocked.");
            True(
                blocked.Error?.Contains(
                    "outside",
                    StringComparison
                        .OrdinalIgnoreCase) ==
                    true,
                "Visual path escape did not return a security error.");
        }
        finally
        {
            try
            {
                Directory.Delete(
                    tempRoot,
                    recursive: true);
            }
            catch
            {
            }
        }
    });

var registry = new CapabilityRegistry();

Register(
    registry,
    TunnelAgentManifestFactory.Create(
        "4.1.0-zagent.1",
        "127.0.0.3",
        18810));

Register(
    registry,
    FilesAgentManifestFactory.Create(
        "3.3.0-v3",
        "127.0.0.3",
        18820));

Register(
    registry,
    WebAgentManifestFactory.Create(
        "2.2.10-zagent.1",
        "127.0.0.3",
        18830));

Register(
    registry,
    ArcMapAgentManifestFactory.Create(
        "3.0.0-zagent.1",
        "127.0.0.3",
        18840));

registry.TrySetHealth(
    TunnelAgentManifestFactory.AgentId,
    AgentHealthState.Ready);
registry.TrySetHealth(
    FilesAgentManifestFactory.AgentId,
    AgentHealthState.Ready);
registry.TrySetHealth(
    WebAgentManifestFactory.AgentId,
    AgentHealthState.Ready);
registry.TrySetHealth(
    ArcMapAgentManifestFactory.AgentId,
    AgentHealthState.Degraded,
    "External ArcMap bridge offline.");

await RunAsync(
    "registry contains exactly 390 manager-visible capabilities",
    async () =>
    {
        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var controllers =
            CreateControllers([]);

        var service = new ManagerControlService(
            registry,
            supervisor,
            controllers);

        var rows =
            await CallAsync<
                IReadOnlyList<ManagerCapabilityRow>>(
                service,
                "registry.capabilities");

        Equal(390, rows.Count);
        Equal(
            390,
            rows.Select(item => item.Capability)
                .Distinct(StringComparer.Ordinal)
                .Count());

        Equal(
            8,
            rows.Count(
                item =>
                    item.AgentId ==
                    TunnelAgentManifestFactory.AgentId));

        Equal(
            71,
            rows.Count(
                item =>
                    item.AgentId ==
                    FilesAgentManifestFactory.AgentId));

        Equal(
            151,
            rows.Count(
                item =>
                    item.AgentId ==
                    WebAgentManifestFactory.AgentId));

        Equal(
            160,
            rows.Count(
                item =>
                    item.AgentId ==
                    ArcMapAgentManifestFactory.AgentId));
    });

await RunAsync(
    "dashboard preserves ArcMap degraded semantics",
    async () =>
    {
        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var calls = new List<string>();
        var controllers =
            CreateControllers(calls);

        var service = new ManagerControlService(
            registry,
            supervisor,
            controllers);

        var dashboard =
            await CallAsync<
                ManagerDashboardSnapshot>(
                service,
                "manager.dashboard");

        Equal(4, dashboard.RegisteredAgents);
        Equal(390, dashboard.CapabilityCount);

        var arc = dashboard.Agents.Single(
            item =>
                item.AgentId ==
                ArcMapAgentManifestFactory.AgentId);

        Equal(
            AgentHealthState.Degraded,
            arc.Health);

        True(
            arc.Detail?.Contains(
                "external CURRENT-MXD bridge offline",
                StringComparison.OrdinalIgnoreCase) ==
            true,
            "ArcMap degraded explanation missing.");
    });

await RunAsync(
    "start all follows dependency order",
    async () =>
    {
        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var calls = new List<string>();
        var service = new ManagerControlService(
            registry,
            supervisor,
            CreateControllers(calls));

        var result =
            await CallAsync<ManagerOperationResult>(
                service,
                "lifecycle.all",
                new ManagerLifecycleRequest(
                    "all",
                    "start"));

        True(result.Success, result.Message);

        Equal(
            "start:files.service|start:web.service|start:arcmap.service|start:system.tunnel",
            string.Join("|", calls));
    });

await RunAsync(
    "stop all follows reverse dependency order",
    async () =>
    {
        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var calls = new List<string>();
        var service = new ManagerControlService(
            registry,
            supervisor,
            CreateControllers(calls));

        var result =
            await CallAsync<ManagerOperationResult>(
                service,
                "lifecycle.all",
                new ManagerLifecycleRequest(
                    "all",
                    "stop"));

        True(result.Success, result.Message);

        Equal(
            "stop:system.tunnel|stop:arcmap.service|stop:web.service|stop:files.service",
            string.Join("|", calls));
    });

await RunAsync(
    "restart all performs complete stop then start",
    async () =>
    {
        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var calls = new List<string>();
        var service = new ManagerControlService(
            registry,
            supervisor,
            CreateControllers(calls));

        var result =
            await CallAsync<ManagerOperationResult>(
                service,
                "lifecycle.all",
                new ManagerLifecycleRequest(
                    "all",
                    "restart"));

        True(result.Success, result.Message);

        Equal(
            "stop:system.tunnel|stop:arcmap.service|stop:web.service|stop:files.service|" +
            "start:files.service|start:web.service|start:arcmap.service|start:system.tunnel",
            string.Join("|", calls));
    });

await RunAsync(
    "unknown manager method fails closed",
    async () =>
    {
        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var service = new ManagerControlService(
            registry,
            supervisor,
            CreateControllers([]));

        var response =
            await service.HandleAsync(
                new ManagerRequestEnvelope(
                    ManagerProtocol.Version,
                    "unknown",
                    "does.not.exist"));

        False(response.Success, "Unknown method unexpectedly succeeded.");
        True(
            response.Error?.Contains(
                "Unknown Manager method",
                StringComparison.Ordinal) ==
            true,
            "Unknown-method error missing.");
    });

await RunAsync(
    "named pipe client roundtrip returns 390 capabilities",
    async () =>
    {
        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var service = new ManagerControlService(
            registry,
            supervisor,
            CreateControllers([]));

        var pipeName =
            "Zagent.Manager.Test." +
            Guid.NewGuid().ToString("N");

        await using var server =
            new ManagerNamedPipeServer(
                service,
                pipeName);

        server.Start();

        var client = new ManagerPipeTestClient(
            pipeName);

        var rows =
            await client.SendAsync<
                IReadOnlyList<ManagerCapabilityRow>>(
                "registry.capabilities",
                timeout: TimeSpan.FromSeconds(4));

        Equal(390, rows.Count);

        await server.StopAsync();
    });

await RunAsync(
    "system shutdown fires named pipe shutdown event",
    async () =>
    {
        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var service = new ManagerControlService(
            registry,
            supervisor,
            CreateControllers([]));

        var pipeName =
            "Zagent.Manager.Shutdown." +
            Guid.NewGuid().ToString("N");

        await using var server =
            new ManagerNamedPipeServer(
                service,
                pipeName);

        var shutdown =
            new TaskCompletionSource<bool>(
                TaskCreationOptions.RunContinuationsAsynchronously);

        server.ShutdownRequested += (_, _) =>
            shutdown.TrySetResult(true);

        server.Start();

        var client = new ManagerPipeTestClient(
            pipeName);

        await client.RequestShutdownAsync();

        var completed =
            await Task.WhenAny(
                shutdown.Task,
                Task.Delay(
                    TimeSpan.FromSeconds(3)));

        True(
            completed == shutdown.Task &&
            shutdown.Task.Result,
            "Shutdown event was not raised.");

        await server.StopAsync();
    });

await RunAsync(
    "monitoring filters completed tasks and STOP routes to Tunnel cancel",
    async () =>
    {
        var handler =
            new StubHttpHandler(
                request =>
                {
                    var path =
                        request.RequestUri?.AbsolutePath ??
                        "";

                    if (request.Method == HttpMethod.Get &&
                        path == "/router/tasks")
                    {
                        return JsonResponse(
                            """
                            {
                              "tasks": [
                                {
                                  "task_id": "tsk_running",
                                  "session_id": "chat_01",
                                  "request_id": "req_01",
                                  "service_id": "files",
                                  "tool_name": "files_powershell_run",
                                  "state": "running",
                                  "progress": 0.5,
                                  "access_mode": "write",
                                  "priority": 1,
                                  "resource_key": "files:test",
                                  "created_at": 10,
                                  "started_at": 11,
                                  "arguments": {"script": "test"}
                                },
                                {
                                  "task_id": "tsk_done",
                                  "session_id": "chat_01",
                                  "request_id": "req_02",
                                  "service_id": "files",
                                  "tool_name": "files_read",
                                  "state": "succeeded",
                                  "progress": 1,
                                  "access_mode": "read",
                                  "priority": 2,
                                  "resource_key": "files:test",
                                  "created_at": 8,
                                  "started_at": 8.5,
                                  "finished_at": 9,
                                  "arguments": {"path": "x"}
                                }
                              ],
                              "queue_depth": 1,
                              "queue_depths": {"interactive": 1, "background": 0}
                            }
                            """);
                    }

                    if (request.Method == HttpMethod.Get &&
                        path == "/router/chats")
                    {
                        return JsonResponse(
                            """
                            {
                              "chats": [
                                {
                                  "session_id": "chat_01",
                                  "alias": "Chat 01",
                                  "title": "Manager Monitoring",
                                  "title_source": "host_metadata",
                                  "first_seen": 1,
                                  "last_seen": 12,
                                  "last_tool": "files_powershell_run"
                                }
                              ],
                              "count": 1
                            }
                            """);
                    }

                    if (request.Method == HttpMethod.Post &&
                        path ==
                            "/router/tasks/tsk_running/cancel")
                    {
                        return JsonResponse(
                            """
                            {
                              "ok": true,
                              "task_id": "tsk_running",
                              "state": "cancelling",
                              "cooperative": true
                            }
                            """);
                    }

                    return new HttpResponseMessage(
                        HttpStatusCode.NotFound);
                });

        using var http =
            new HttpClient(handler);

        var tunnel =
            new TunnelManagerReadModel(
                new Uri(
                    "http://127.0.0.3:18990/"),
                http);

        await using var supervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);

        var service =
            new ManagerControlService(
                registry,
                supervisor,
                CreateControllers([]),
                tunnel: tunnel);

        var active =
            await CallAsync<
                ManagerMonitoringSnapshot>(
                service,
                "monitoring.snapshot",
                new ManagerRefreshRequest(
                    IncludeCompletedTasks: false));

        Equal(1, active.Tasks.Count);
        Equal("tsk_running", active.Tasks[0].TaskId);
        True(
            active.Tasks[0].CanStop,
            "Running task should be stoppable.");
        Equal(
            "COOPERATIVE/BEST-EFFORT",
            active.Tasks[0].StopMode);

        var recent =
            await CallAsync<
                ManagerMonitoringSnapshot>(
                service,
                "monitoring.snapshot",
                new ManagerRefreshRequest(
                    IncludeCompletedTasks: true));

        Equal(2, recent.Tasks.Count);

        var cancel =
            await CallAsync<
                ManagerOperationResult>(
                service,
                "task.cancel",
                new ManagerTaskCancelRequest(
                    "tsk_running"));

        True(cancel.Success, cancel.Message);
    });

await RunAsync(
    "web Pair and Approve requests are visible but not locally resolvable",
    async () =>
    {
        var statusPayload =
            """
            {
              "required": true,
              "connected": true,
              "authorized": false,
              "pairingPending": {
                "id": "PAIR-01",
                "expiresAt": 9999999999999,
                "profile": {
                  "directory": "Profile 2",
                  "name": "HARRY",
                  "userName": "harry@example.test"
                }
              },
              "authorizationPending": {
                "id": "AUTH-01",
                "scope": "window",
                "seconds": 300,
                "allowNavigation": true,
                "allowNewTabs": true,
                "expiresAt": 9999999999999
              },
              "profileBound": true
            }
            """;

        var rpc =
            JsonSerializer.Serialize(
                new
                {
                    jsonrpc = "2.0",
                    id = "web-status",
                    result = new
                    {
                        content = new[]
                        {
                            new
                            {
                                type = "text",
                                text = statusPayload
                            }
                        },
                        isError = false
                    }
                });

        var handler =
            new StubHttpHandler(
                request =>
                    new HttpResponseMessage(
                        HttpStatusCode.OK)
                    {
                        Content = new StringContent(
                            rpc,
                            Encoding.UTF8,
                            "application/json")
                    });

        using var http =
            new HttpClient(handler);

        var web =
            new WebManagerReadModel(
                new Uri(
                    "http://127.0.0.3:18991/mcp"),
                http);

        var result =
            await web.GetPendingRequestsAsync();

        Equal(2, result.Requests.Count);
        True(result.Connected, "Web bridge should be connected.");
        False(result.Authorized, "Authorization should still be pending.");
        True(
            result.Requests.All(
                item =>
                    !item.CanResolveLocally &&
                    item.Source ==
                    "Web Chrome Bridge"),
            "Web requests must remain Chrome-resolved.");
        True(
            result.Requests.Any(
                item =>
                    item.Kind == "web_pairing"),
            "Pair request missing.");
        True(
            result.Requests.Any(
                item =>
                    item.Kind ==
                    "web_authorization"),
            "Authorization request missing.");
    });

await RunAsync(
    "technical logs are newest first and bounded",
    () =>
    {
        var logs =
            new ManagerTechnicalLogStore(
                capacity: 100);

        for (var i = 0; i < 150; i++)
        {
            logs.Write(
                "INFO",
                "test",
                "event",
                i.ToString());
        }

        var rows = logs.Snapshot(100);

        Equal(100, rows.Count);
        Equal("149", rows[0].Message);
        Equal("50", rows[^1].Message);

        return Task.CompletedTask;
    });

Console.WriteLine(
    failed == 0
        ? $"MANAGER_TEST_PASS passed={passed} failed={failed}"
        : $"MANAGER_TEST_FAIL passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

static ManagerAgentControllerRegistry CreateControllers(
    List<string> calls)
{
    var registry =
        new ManagerAgentControllerRegistry();

    Add(
        registry,
        TunnelAgentManifestFactory.AgentId,
        TunnelProcessFactory.RouterProcessId);
    Add(
        registry,
        FilesAgentManifestFactory.AgentId,
        FilesProcessFactory.ProcessId);
    Add(
        registry,
        WebAgentManifestFactory.AgentId,
        WebProcessFactory.ProcessId);
    Add(
        registry,
        ArcMapAgentManifestFactory.AgentId,
        ArcMapProcessFactory.ProcessId);

    return registry;

    void Add(
        ManagerAgentControllerRegistry target,
        string agentId,
        string processId)
    {
        target.Register(
            new ManagerAgentController(
                agentId,
                processId,
                ct =>
                {
                    calls.Add("start:" + agentId);
                    return Task.FromResult(
                        new LifecycleOperationResult(
                            true,
                            agentId,
                            "start",
                            "ok"));
                },
                ct =>
                {
                    calls.Add("stop:" + agentId);
                    return Task.FromResult(
                        new LifecycleOperationResult(
                            true,
                            agentId,
                            "stop",
                            "ok"));
                },
                ct =>
                {
                    calls.Add("restart:" + agentId);
                    return Task.FromResult(
                        new LifecycleOperationResult(
                            true,
                            agentId,
                            "restart",
                            "ok"));
                },
                ct =>
                {
                    calls.Add("refresh:" + agentId);
                    return Task.FromResult(
                        new ManagerOperationResult(
                            true,
                            "refresh",
                            agentId,
                            "ok"));
                }));
    }
}

static void Register(
    CapabilityRegistry registry,
    AgentManifest manifest)
{
    var result =
        registry.Register(
            manifest,
            productionApproved: true);

    if (!result.Success)
    {
        throw new InvalidOperationException(
            string.Join("; ", result.Errors));
    }
}

static async Task<T> CallAsync<T>(
    ManagerControlService service,
    string method,
    object? parameters = null)
{
    var request =
        new ManagerRequestEnvelope(
            ManagerProtocol.Version,
            Guid.NewGuid().ToString("N"),
            method,
            parameters is null
                ? null
                : ManagerJson.ToElement(parameters));

    var response =
        await service.HandleAsync(request);

    if (!response.Success)
    {
        throw new InvalidOperationException(
            response.Error ??
            $"Manager method {method} failed.");
    }

    if (response.Result is null)
    {
        throw new InvalidOperationException(
            $"Manager method {method} returned no result.");
    }

    return response.Result.Value.Deserialize<T>(
               ManagerJson.Options) ??
           throw new InvalidOperationException(
               $"Manager method {method} returned null.");
}

async Task RunAsync(
    string name,
    Func<Task> test)
{
    try
    {
        await test();
        passed++;
        Console.WriteLine("PASS " + name);
    }
    catch (Exception ex)
    {
        failed++;
        Console.WriteLine(
            $"FAIL {name}: {ex}");
    }
}

static void True(
    bool value,
    string message)
{
    if (!value)
    {
        throw new InvalidOperationException(message);
    }
}

static void False(
    bool value,
    string message) =>
    True(!value, message);

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

static HttpResponseMessage JsonResponse(string json) =>
    new(HttpStatusCode.OK)
    {
        Content = new StringContent(
            json,
            Encoding.UTF8,
            "application/json")
    };

sealed class StubHttpHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, HttpResponseMessage> _handler;

    public StubHttpHandler(
        Func<HttpRequestMessage, HttpResponseMessage> handler)
    {
        _handler = handler;
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken) =>
        Task.FromResult(_handler(request));
}
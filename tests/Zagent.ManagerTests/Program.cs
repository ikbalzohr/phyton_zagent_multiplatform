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
                    provenance = new
                    {
                        deviceId = "device-test",
                        deviceName = "Viewer Test Device",
                        sessionId = "session-test"
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
                "session-test",
                valid.SessionId);

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
                        provenance = new
                        {
                            deviceId =
                                "device-test",
                            deviceName =
                                "Viewer Test Device",
                            sessionId =
                                "session-test"
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
    "registry contains exactly 354 manager-visible capabilities",
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

        Equal(354, rows.Count);
        Equal(
            354,
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
            124,
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
        Equal(354, dashboard.CapabilityCount);

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
    "named pipe client roundtrip returns 354 capabilities",
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

        var client = new ManagerPipeClient(
            pipeName);

        var rows =
            await client.SendAsync<
                IReadOnlyList<ManagerCapabilityRow>>(
                "registry.capabilities",
                timeout: TimeSpan.FromSeconds(4));

        Equal(354, rows.Count);

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

        var client = new ManagerPipeClient(
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
    "chat presentation humanizes machine activity",
    () =>
    {
        var row = new ManagerChatLogRow(
            "chat_a",
            "Chat 01",
            "",
            "Tunnel",
            "files",
            "files_powershell_run",
            "",
            1,
            "Chat 01");

        Equal(
            "Menjalankan perintah PowerShell",
            ChatPresentation.Humanize(row));

        var chat = new ManagerChatRow(
            "chat_a",
            "Chat 01",
            "",
            "unavailable_from_host",
            1,
            2,
            "files_powershell_run",
            "Chat 01");

        var title =
            ChatPresentation.BuildDisplayTitle(
                chat,
                [
                    row with
                    {
                        Message =
                            "Zagent.Manager MainWindow development"
                    }
                ]);

        Equal(
            "Chat - Produksi Zagent",
            title);

        Equal(
            "Chat",
            ChatPresentation.BuildEntryDisplayTitle(row));

        return Task.CompletedTask;
    });


await RunAsync(
    "chat log reader accepts ISO timestamps",
    async () =>
    {
        var root =
            Path.Combine(
                Path.GetTempPath(),
                "zagent-manager-chatlog-" +
                Guid.NewGuid().ToString("N"));

        Directory.CreateDirectory(root);

        try
        {
            var path =
                Path.Combine(
                    root,
                    "chat_log.jsonl");

            var line =
                JsonSerializer.Serialize(
                    new
                    {
                        time =
                            "2026-09-28T11:01:59+08:00",
                        role = "assistant",
                        source = "ChatGPT",
                        message =
                            "Visible progress message",
                        chat_id = "chat_iso",
                        chat_alias = "Chat 02",
                        chat_title =
                            "Produksi Zagent"
                    });

            await File.WriteAllTextAsync(
                path,
                line + Environment.NewLine);

            var reader =
                new ManagerChatLogReader(path);

            var rows =
                await reader.ReadAsync(
                    10,
                    [
                        new ManagerChatRow(
                            "chat_iso",
                            "Chat 02",
                            "Produksi Zagent",
                            "host",
                            null,
                            null,
                            "",
                            "")
                    ]);

            Equal(1, rows.Count);
            True(
                rows[0].Timestamp.GetValueOrDefault() > 0,
                "ISO timestamp was not converted.");
            Equal(
                "Visible progress message",
                rows[0].Message);
        }
        finally
        {
            Directory.Delete(
                root,
                recursive: true);
        }
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
    "plugin access configuration persists installer-selected audience",
    async () =>
    {
        var root =
            Path.Combine(
                Path.GetTempPath(),
                "zagent-plugin-access-config-" +
                Guid.NewGuid().ToString("N"));

        Directory.CreateDirectory(root);

        var oldAudience =
            Environment.GetEnvironmentVariable(
                "ZAGENT_PLUGIN_AUDIENCE");
        var oldDisplay =
            Environment.GetEnvironmentVariable(
                "ZAGENT_PLUGIN_DISPLAY_NAME");

        try
        {
            Environment.SetEnvironmentVariable(
                "ZAGENT_PLUGIN_AUDIENCE",
                "tryplugin");
            Environment.SetEnvironmentVariable(
                "ZAGENT_PLUGIN_DISPLAY_NAME",
                "TryPlugin");

            var store =
                new Zagent.Core.Configuration
                    .PluginAccessConfigurationStore();

            var created =
                await store.EnsureAsync(
                    root,
                    Zagent.Shared.Contracts
                        .AgentEnvironment.Production);

            Equal(
                "tryplugin",
                created.Audience);
            Equal(
                "TryPlugin",
                created.DisplayName);
            Equal(
                "zagent",
                created.FallbackPlugin);

            Environment.SetEnvironmentVariable(
                "ZAGENT_PLUGIN_AUDIENCE",
                "zagent-production");
            Environment.SetEnvironmentVariable(
                "ZAGENT_PLUGIN_DISPLAY_NAME",
                "Zagent");

            var reloaded =
                await store.EnsureAsync(
                    root,
                    Zagent.Shared.Contracts
                        .AgentEnvironment.Production);

            Equal(
                "tryplugin",
                reloaded.Audience);
            Equal(
                "TryPlugin",
                reloaded.DisplayName);
        }
        finally
        {
            Environment.SetEnvironmentVariable(
                "ZAGENT_PLUGIN_AUDIENCE",
                oldAudience);
            Environment.SetEnvironmentVariable(
                "ZAGENT_PLUGIN_DISPLAY_NAME",
                oldDisplay);

            Directory.Delete(
                root,
                recursive: true);
        }
    });

await RunAsync(
    "plugin access pending requests are locally resolvable through Router Manager",
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
                        path == "/router/access/requests")
                    {
                        return JsonResponse(
                            """
                            {
                              "ok": true,
                              "audience": "zagent-production",
                              "display_name": "Zagent",
                              "count": 1,
                              "requests": [
                                {
                                  "request_id": "PAC-TEST01",
                                  "plugin_audience": "zagent-production",
                                  "plugin_display_name": "Zagent",
                                  "operator_alias": "Ikbal",
                                  "session_id": "chat_test",
                                  "device_alias": "Ikbal",
                                  "state": "PENDING",
                                  "created_at": 1790840000.0
                                }
                              ]
                            }
                            """);
                    }

                    if (request.Method == HttpMethod.Post &&
                        path ==
                            "/router/access/request/PAC-TEST01/resolve")
                    {
                        return JsonResponse(
                            """
                            {
                              "ok": true,
                              "request_id": "PAC-TEST01",
                              "session_id": "chat_test",
                              "state": "APPROVED",
                              "allowed": true,
                              "operator_alias": "Ikbal"
                            }
                            """);
                    }

                    return new HttpResponseMessage(
                        HttpStatusCode.NotFound);
                });

        using var http =
            new HttpClient(handler);

        var configRoot =
            Path.Combine(
                Path.GetTempPath(),
                "zagent-router-manager-access-" +
                Guid.NewGuid().ToString("N"));

        Directory.CreateDirectory(configRoot);

        try
        {
            var router =
                new RouterManagerService(
                    new Uri(
                        "http://127.0.0.3:18992/"),
                    configRoot,
                    http);

            var pending =
                await router
                    .GetPluginAccessPendingAsync();

            Equal(1, pending.Count);
            Equal(
                "Plugin Access",
                pending[0].Source);
            Equal(
                "plugin_access",
                pending[0].Kind);
            Equal(
                "Ikbal",
                pending[0].RequestedBy);
            True(
                pending[0].CanResolveLocally,
                "Plugin Access request must be resolvable locally.");

            var resolved =
                await router.ResolvePluginAccessAsync(
                    new ManagerApprovalActionRequest(
                        "PAC-TEST01",
                        "approve",
                        null,
                        "Plugin Access"));

            True(
                resolved.Success,
                resolved.Message);
        }
        finally
        {
            Directory.Delete(
                configRoot,
                recursive: true);
        }
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

var devRoot =
    Environment.GetEnvironmentVariable(
        "ZAGENT_DEV_ROOT");

if (!string.IsNullOrWhiteSpace(devRoot))
{
    // UI1 replaces the WPF window-close smoke; browser lifetime must not own Core.

    await RunAsync(
        "real Manager Core host controls all four agents through Development Gateway",
        async () =>
        {
            var filesPython =
                Environment.GetEnvironmentVariable(
                    "ZAGENT_FILES_TEST_PYTHON") ??
                throw new InvalidOperationException(
                    "ZAGENT_FILES_TEST_PYTHON is required.");
            var tunnelPython =
                Environment.GetEnvironmentVariable(
                    "ZAGENT_TUNNEL_TEST_PYTHON") ??
                throw new InvalidOperationException(
                    "ZAGENT_TUNNEL_TEST_PYTHON is required.");
            var webNode =
                Environment.GetEnvironmentVariable(
                    "ZAGENT_WEB_TEST_NODE") ??
                throw new InvalidOperationException(
                    "ZAGENT_WEB_TEST_NODE is required.");
            var arcMapPython =
                Environment.GetEnvironmentVariable(
                    "ZAGENT_ARCMAP_TEST_PYTHON") ??
                throw new InvalidOperationException(
                    "ZAGENT_ARCMAP_TEST_PYTHON is required.");

            var ports = FindFreePorts(4);
            var validationRoot = Path.Combine(
                Path.GetFullPath(devRoot),
                "_validation",
                "phase8-manager-e2e-" +
                Guid.NewGuid().ToString("N"));

            var workspace =
                Path.Combine(
                    validationRoot,
                    "workspace");

            Directory.CreateDirectory(workspace);

            var pipeName =
                "Zagent.Manager.E2E." +
                Guid.NewGuid().ToString("N");

            await using var host =
                await ManagerCoreHost.CreateAsync(
                    new ManagerCoreHostOptions(
                        ZagentRoot:
                            Path.GetFullPath(devRoot),
                        DataRoot:
                            Path.Combine(
                                validationRoot,
                                "data"),
                        FilesDefaultProfile:
                            workspace,
                        PipeName:
                            pipeName,
                        FilesPython:
                            filesPython,
                        TunnelPython:
                            tunnelPython,
                        WebNode:
                            webNode,
                        ArcMapPython:
                            arcMapPython,
                        BindHost:
                            "127.0.0.3",
                        TunnelPort:
                            ports[0],
                        FilesPort:
                            ports[1],
                        WebPort:
                            ports[2],
                        ArcMapPort:
                            ports[3],
                        Environment:
                            AgentEnvironment.Development),
                    acquireSupervisorLease: false);

            host.Start();

            try
            {
                var client =
                    new ManagerPipeClient(
                        pipeName);

                var capabilities =
                    await client.SendAsync<
                        IReadOnlyList<
                            ManagerCapabilityRow>>(
                        "registry.capabilities",
                        timeout:
                            TimeSpan.FromSeconds(8));

                Equal(354, capabilities.Count);

                var start =
                    await client.SendAsync<
                        ManagerOperationResult>(
                        "lifecycle.all",
                        new ManagerLifecycleRequest(
                            "all",
                            "start"),
                        timeout:
                            TimeSpan.FromSeconds(50));

                True(
                    start.Success,
                    start.Message);

                var dashboard =
                    await client.SendAsync<
                        ManagerDashboardSnapshot>(
                        "manager.dashboard",
                        timeout:
                            TimeSpan.FromSeconds(15));

                Equal(4, dashboard.RegisteredAgents);
                Equal(354, dashboard.CapabilityCount);
                Equal(4, dashboard.RunningProcesses);
                True(
                    dashboard.Agents.All(
                        item => item.Environment ==
                            AgentEnvironment.Development),
                    "DEV Manager host exposed a non-development agent environment.");
                True(
                    dashboard.Agents.All(
                        item => !item.ProductionApproved),
                    "DEV Manager host exposed production-approved agents.");

                var arc =
                    dashboard.Agents.Single(
                        item =>
                            item.AgentId ==
                            ArcMapAgentManifestFactory.AgentId);

                Equal(
                    AgentHealthState.Degraded,
                    arc.Health);

                var tunnel =
                    dashboard.Agents.Single(
                        item =>
                            item.AgentId ==
                            TunnelAgentManifestFactory.AgentId);
                Equal(
                    AgentHealthState.Ready,
                    tunnel.Health);

                var profiles =
                    await client.SendAsync<
                        ManagerProfilesSnapshot>(
                        "profiles.snapshot",
                        timeout:
                            TimeSpan.FromSeconds(10));

                if (profiles.Profiles.Count < 1)
                {
                    var logs =
                        await client.SendAsync<
                            ManagerLogsSnapshot>(
                            "logs.snapshot",
                            timeout:
                                TimeSpan.FromSeconds(5));

                    var rawFiles =
                        await RawMcpToolAsync(
                            new Uri(
                                $"http://127.0.0.3:{ports[1]}/mcp"),
                            "files_profile_list");

                    throw new InvalidOperationException(
                        "Files profile read-model returned no profiles. RAW=" +
                        rawFiles +
                        " LOGS=" +
                        string.Join(
                            " | ",
                            logs.Technical
                                .Take(10)
                                .Select(
                                    item =>
                                        $"{item.Source}/{item.Event}: {item.Message}")));
                }

                var approvedRoot =
                    Path.Combine(
                        validationRoot,
                        "approved-profile");
                Directory.CreateDirectory(
                    approvedRoot);

                await RawMcpToolAsync(
                    new Uri(
                        $"http://127.0.0.3:{ports[1]}/mcp"),
                    "files_profile_request_add",
                    new
                    {
                        name = "manager_approved",
                        root = approvedRoot,
                        mode = "read-only",
                        description =
                            "Phase 8 local approval E2E"
                    });

                var pending =
                    await client.SendAsync<
                        ManagerProfilesSnapshot>(
                        "profiles.snapshot",
                        timeout:
                            TimeSpan.FromSeconds(10));

                var filesApproval =
                    pending.PendingApprovals
                        .Single(
                            item =>
                                item.Source == "Files" &&
                                item.Kind == "add" &&
                                item.CanResolveLocally);

                var approvalResult =
                    await client.SendAsync<
                        ManagerOperationResult>(
                        "approval.resolve",
                        new ManagerApprovalActionRequest(
                            filesApproval.RequestId,
                            "approve"),
                        timeout:
                            TimeSpan.FromSeconds(10));

                True(
                    approvalResult.Success,
                    approvalResult.Message);

                var afterApproval =
                    await client.SendAsync<
                        ManagerProfilesSnapshot>(
                        "profiles.snapshot",
                        timeout:
                            TimeSpan.FromSeconds(10));

                True(
                    afterApproval.Profiles.Any(
                        item =>
                            item.Name ==
                            "manager_approved"),
                    "Local Files approval did not materialize the approved profile.");

                False(
                    afterApproval.PendingApprovals.Any(
                        item =>
                            item.RequestId ==
                            filesApproval.RequestId),
                    "Resolved Files approval remained pending.");

                var stop =
                    await client.SendAsync<
                        ManagerOperationResult>(
                        "lifecycle.all",
                        new ManagerLifecycleRequest(
                            "all",
                            "stop"),
                        timeout:
                            TimeSpan.FromSeconds(35));

                True(
                    stop.Success,
                    stop.Message);

                var stopped =
                    await client.SendAsync<
                        ManagerDashboardSnapshot>(
                        "manager.dashboard",
                        timeout:
                            TimeSpan.FromSeconds(12));

                Equal(
                    0,
                    stopped.RunningProcesses);
            }
            finally
            {
                try
                {
                    await host.StopAsync();
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
        });
}

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

static int[] FindFreePorts(int count)
{
    var result = new List<int>();
    var address = IPAddress.Parse("127.0.0.3");

    for (var port = 18900;
        port <= 18999 &&
        result.Count < count;
        port++)
    {
        TcpListener? listener = null;

        try
        {
            listener = new TcpListener(
                address,
                port);
            listener.Start();
            result.Add(port);
        }
        catch (SocketException)
        {
        }
        finally
        {
            listener?.Stop();
        }
    }

    if (result.Count != count)
    {
        throw new InvalidOperationException(
            "Not enough free Development Gateway ports.");
    }

    return result.ToArray();
}

static async Task<string> RawMcpToolAsync(
    Uri uri,
    string toolName,
    object? arguments = null)
{
    using var http = new HttpClient(
        new SocketsHttpHandler
        {
            UseProxy = false
        })
    {
        Timeout = TimeSpan.FromSeconds(5)
    };

    var body = JsonSerializer.Serialize(
        new
        {
            jsonrpc = "2.0",
            id = "raw-manager-test",
            method = "tools/call",
            @params = new
            {
                name = toolName,
                arguments =
                    arguments ??
                    new Dictionary<string, object?>()
            }
        });

    using var request =
        new HttpRequestMessage(
            HttpMethod.Post,
            uri);

    request.Content =
        new StringContent(
            body,
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

    using var response =
        await http.SendAsync(request);

    return await response.Content.ReadAsStringAsync();
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
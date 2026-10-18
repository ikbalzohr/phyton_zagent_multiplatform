using System.Text.Json;
using Zagent.Core.Agents.ArcMap;
using Zagent.Core.Agents.Files;
using Zagent.Core.Agents.Tunnel;
using Zagent.Core.Agents.Web;
using Zagent.Core.Configuration;
using Zagent.Core.Network;
using Zagent.Core.Identity;
using Zagent.Core.Registry;
using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;
using Zagent.Shared.Manager;
using Zagent.Shared.Installation;

namespace Zagent.Core.Manager;

public sealed record ManagerCoreHostOptions(
    string ZagentRoot,
    string DataRoot,
    string FilesDefaultProfile,
    string PipeName = ManagerProtocol.DefaultPipeName,
    string? FilesPython = null,
    string? TunnelPython = null,
    string? WebNode = null,
    string? ArcMapPython = null,
    string BindHost = "127.0.0.3",
    int TunnelPort = 18810,
    int TunnelHealthPort = 18811,
    int FilesPort = 18820,
    int WebPort = 18830,
    int ArcMapPort = 18840,
    string? SupervisorLeaseName = null,
    AgentEnvironment Environment = AgentEnvironment.Production);

public sealed class ManagerCoreHost : IAsyncDisposable
{
    private readonly NativeAgentSupervisor _supervisor;
    private int _disposed;
    private readonly object _stopSync = new();
    private Task? _stopTask;

    private ManagerCoreHost(
        NativeAgentSupervisor supervisor,
        ManagerControlService controlService,
        ManagerCoreHostOptions options)
    {
        _supervisor = supervisor;
        ControlService = controlService;
        Options = options;
    }

    public ManagerControlService ControlService { get; }

    public ManagerCoreHostOptions Options { get; }

    public bool IsStopping => _stopTask is not null;
    private bool _shutdownWired;
    private void OnShutdownRequested(object? sender, EventArgs args) => ShutdownRequested?.Invoke(this, args);
    public event EventHandler? ShutdownRequested
    {
        add { ShutdownRequested += value; if (!_shutdownWired) { _shutdownWired = true; ControlService.Shutdown.ShutdownRequested += OnShutdownRequested; } }
        remove { ShutdownRequested -= value; }
    }

    public static async Task<ManagerCoreHost> CreateAsync(
        ManagerCoreHostOptions options,
        bool acquireSupervisorLease = true,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var root = Path.GetFullPath(options.ZagentRoot);
        var data = Path.GetFullPath(options.DataRoot);

        if (!Directory.Exists(root))
        {
            throw new DirectoryNotFoundException(
                $"Zagent root was not found: {root}");
        }

        Directory.CreateDirectory(data);

        var machineIdentityStore =
            new MachineIdentityStore(
                Path.Combine(
                    data,
                    "config",
                    MachineIdentityStore.FileName));

        // Chat history is not an execution authority; it is not loaded by the product host.
        var machineIdentity =
            await machineIdentityStore.EnsureAsync(
                cancellationToken);

        // Child processes inherit these owner-provisioned private-channel credentials.
        Environment.SetEnvironmentVariable("ZAGENT_DEVICE_ID", machineIdentity.DeviceId);
        Environment.SetEnvironmentVariable("ZAGENT_INSTALLATION_ID", machineIdentity.InstallationId);
        var internalToken = Environment.GetEnvironmentVariable("ZAGENT_INTERNAL_TOKEN");
        if (!string.IsNullOrWhiteSpace(internalToken))
        {
            Environment.SetEnvironmentVariable("ZAGENT_INTERNAL_TOKEN", internalToken);
        }
        var internalContextKey = Environment.GetEnvironmentVariable("ZAGENT_INTERNAL_CONTEXT_KEY");
        if (!string.IsNullOrWhiteSpace(internalContextKey))
        {
            Environment.SetEnvironmentVariable("ZAGENT_INTERNAL_CONTEXT_KEY", internalContextKey);
        }

        if (!options.BindHost.Equals("127.0.0.3", StringComparison.Ordinal) &&
            !options.BindHost.Equals("127.0.0.1", StringComparison.Ordinal) &&
            !options.BindHost.Equals("::1", StringComparison.Ordinal) &&
            !options.BindHost.Equals("localhost", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Product management bind host must be loopback.");

        var filesPython = ResolveExecutable(
            options.FilesPython,
            "ZAGENT_FILES_PYTHON",
            Path.Combine(
                root,
                "agents",
                "files",
                "runtime",
                "python",
                "python.exe"),
            "python.exe");

        var tunnelPython = ResolveExecutable(
            options.TunnelPython,
            "ZAGENT_TUNNEL_PYTHON",
            Path.Combine(
                root,
                "agents",
                "tunnel",
                "runtime",
                "python",
                "python.exe"),
            "python.exe");

        var webNode = ResolveExecutable(
            options.WebNode,
            "ZAGENT_WEB_NODE",
            Path.Combine(
                root,
                "agents",
                "web",
                "runtime",
                "node",
                "node.exe"),
            "node.exe");

        var arcMapPython = ResolveExecutable(
            options.ArcMapPython,
            "ZAGENT_ARCMAP_PYTHON",
            Path.Combine(
                root,
                "agents",
                "arcmap",
                "runtime",
                "python",
                "python.exe"),
            "python.exe");

        var registry = new CapabilityRegistry();
        var supervisor = new NativeAgentSupervisor(
            acquireInstanceLease: acquireSupervisorLease,
            instanceLeaseName: options.SupervisorLeaseName ??
                ZagentInstallationProfile.SupervisorLeaseName(
                    ZagentInstallationProfile.InferRole(root)));

        try
        {
            var filesData = Path.Combine(data, "files");
            var tunnelData = Path.Combine(data, "tunnel");
            var webData = Path.Combine(data, "web");
            var arcMapData = Path.Combine(data, "arcmap");

            var filesOptions = new FilesIntegrationOptions(
                PythonExecutable: filesPython,
                EngineRoot: Path.Combine(
                    root,
                    "agents",
                    "files",
                    "engine"),
                DataRoot: filesData,
                ConfigRoot: Path.Combine(
                    filesData,
                    "config"),
                RuntimeRoot: Path.Combine(
                    filesData,
                    "runtime"),
                LogRoot: Path.Combine(
                    filesData,
                    "logs"),
                BackupRoot: Path.Combine(
                    filesData,
                    "backups"),
                UpdateStateRoot: Path.Combine(
                    filesData,
                    "updates"),
                BindHost: options.BindHost,
                Port: options.FilesPort,
                DefaultProfileName: "appBridge",
                DefaultProfileRoot:
                    Path.GetFullPath(
                        options.FilesDefaultProfile),
                DefaultProfileMode: "read-write",
                DeviceId: machineIdentity.DeviceId,
                DeviceName: machineIdentity.DeviceName);

            var webOptions = new WebIntegrationOptions(
                NodeExecutable: webNode,
                EngineRoot: Path.Combine(
                    root,
                    "agents",
                    "web",
                    "engine"),
                DataRoot: webData,
                ConfigRoot: Path.Combine(
                    webData,
                    "config"),
                RuntimeRoot: Path.Combine(
                    webData,
                    "runtime"),
                ArtifactsRoot: Path.Combine(
                    webData,
                    "artifacts"),
                LogRoot: Path.Combine(
                    webData,
                    "logs"),
                BindHost: options.BindHost,
                Port: options.WebPort,
                Browser: "chrome",
                RuntimeMode: "native_attach",
                SessionIsolationMode: "tabs",
                ChromeExecutablePath: null,
                BridgeRequired: true,
                NativeAutoAttach: true,
                NativeAttachOnDemand: true,
                DeviceId: machineIdentity.DeviceId,
                DeviceName: machineIdentity.DeviceName,
                BridgeEnvironment:
                    options.Environment == AgentEnvironment.Development
                        ? "DEVELOPMENT"
                        : "PRODUCTION");

            var arcMapOptions = new ArcMapIntegrationOptions(
                PythonExecutable: arcMapPython,
                EngineRoot: Path.Combine(
                    root,
                    "agents",
                    "arcmap",
                    "engine"),
                DataRoot: arcMapData,
                ConfigRoot: Path.Combine(
                    arcMapData,
                    "config"),
                IpcRoot: Path.Combine(
                    arcMapData,
                    "ipc"),
                RuntimeRoot: Path.Combine(
                    arcMapData,
                    "runtime"),
                LogRoot: Path.Combine(
                    arcMapData,
                    "logs"),
                BindHost: options.BindHost,
                Port: options.ArcMapPort,
                McpPath: "/mcp",
                LegacyManualBaseline: null,
                CommandTimeoutSeconds: 15,
                TunnelPort: options.TunnelPort,
                DeviceId: machineIdentity.DeviceId,
                DeviceName: machineIdentity.DeviceName);

            var localRouterIdentityBinding =
                await machineIdentityStore.CreateTunnelBindingAsync(
                    "zagent-router-local",
                    cancellationToken);

            var pluginAccessConfigStore =
                new PluginAccessConfigurationStore();

            var pluginAccessConfig =
                await pluginAccessConfigStore.EnsureAsync(
                    Path.Combine(
                        data,
                        "config"),
                    options.Environment,
                    cancellationToken);

            var pluginAccessRoot =
                Environment.GetEnvironmentVariable(
                    "ZAGENT_PLUGIN_ACCESS_ROOT");

            if (string.IsNullOrWhiteSpace(
                    pluginAccessRoot))
            {
                pluginAccessRoot = Path.Combine(
                    Environment.GetFolderPath(
                        Environment.SpecialFolder.LocalApplicationData),
                    "Zagent",
                    ZagentInstallationProfile.InferRole(root),
                    "PluginAccess");
            }

            var tunnelOptions = new TunnelIntegrationOptions(
                PythonExecutable: tunnelPython,
                EngineRoot: Path.Combine(
                    root,
                    "agents",
                    "tunnel",
                    "engine"),
                ConfigRoot: Path.Combine(
                    tunnelData,
                    "config"),
                RuntimeRoot: Path.Combine(
                    tunnelData,
                    "runtime"),
                ChatLogPath: Path.Combine(
                    tunnelData,
                    "runtime",
                    "chat_log.jsonl"),
                BindHost: options.BindHost,
                RouterPort: options.TunnelPort,
                DeviceId: machineIdentity.DeviceId,
                DeviceName: machineIdentity.DeviceName,
                DeviceAlias: machineIdentity.DeviceAlias,
                DeviceFingerprint:
                    machineIdentity.BindingFingerprint,
                InstallationId:
                    machineIdentity.InstallationId,
                DeviceBinding:
                    localRouterIdentityBinding,
                IdentityEnforcement:
                    Environment.GetEnvironmentVariable(
                        "ZAGENT_IDENTITY_ENFORCEMENT")
                    ?? "mandatory",
                PluginAudience:
                    pluginAccessConfig.Audience,
                PluginDisplayName:
                    pluginAccessConfig.DisplayName,
                PluginAccessMode:
                    pluginAccessConfig.Mode,
                PluginAccessRoot:
                    Path.GetFullPath(
                        pluginAccessRoot),
                PluginAccessEnforcement:
                    pluginAccessConfig.Enforcement,
                PluginFallback:
                    pluginAccessConfig.FallbackPlugin,
                PluginParentAudience:
                    pluginAccessConfig.ParentAudience,
                ArcMapMcpUrl: $"http://{options.BindHost}:{options.ArcMapPort}/mcp");

            var credentialScope =
                options.Environment.ToString().ToLowerInvariant();
            var persistentCredentialRoot = Path.Combine(
                System.Environment.GetFolderPath(
                    System.Environment.SpecialFolder.LocalApplicationData),
                "Zagent",
                ZagentInstallationProfile.InferRole(root),
                "Credentials",
                credentialScope);
            var persistentCredentialPath = Path.Combine(
                persistentCredentialRoot,
                "transport.credentials.json");
            var legacyCredentialPath = Path.Combine(
                tunnelData,
                "config",
                "transport.credentials.json");

            Directory.CreateDirectory(persistentCredentialRoot);

            if (!File.Exists(persistentCredentialPath) &&
                File.Exists(legacyCredentialPath))
            {
                File.Copy(
                    legacyCredentialPath,
                    persistentCredentialPath,
                    overwrite: false);
            }

            var tunnelCredentialStore =
                new TunnelCredentialStore(
                    persistentCredentialPath);

            TunnelTransportOptions? tunnelTransport = null;

            try
            {
                var credentials =
                    await tunnelCredentialStore.LoadAsync(
                        cancellationToken);

                var transportRoot = Path.Combine(
                    root,
                    "agents",
                    "tunnel",
                    "transport");
                var transportExecutable = Path.Combine(
                    transportRoot,
                    "tunnel-client.exe");

                if (credentials is not null &&
                    File.Exists(transportExecutable))
                {
                    tunnelTransport =
                        new TunnelTransportOptions(
                            ClientExecutable:
                                transportExecutable,
                            WorkingDirectory:
                                transportRoot,
                            TunnelId:
                                credentials.TunnelId,
                            ApiKey:
                                credentials.ApiKey,
                            HealthListenAddress:
                                $"{options.BindHost}:{options.TunnelHealthPort}",
                            RouterMcpUrl:
                                $"http://{options.BindHost}:{options.TunnelPort}/mcp",
                            DeviceId:
                                machineIdentity.DeviceId,
                            DeviceName:
                                machineIdentity.DeviceName,
                            DeviceBinding:
                                await machineIdentityStore.CreateTunnelBindingAsync(
                                    credentials.TunnelId,
                                    cancellationToken));
                }
            }
            catch
            {
                tunnelTransport = null;
            }

            var developmentAgentStore =
                new DevelopmentAgentStore(
                    Path.Combine(tunnelData, "config", "additional_services.json"),
                    ZagentNetworkPolicy.For(ZagentInstallationProfile.InferRole(root))
                        .DevelopmentGatewayStart,
                    ZagentNetworkPolicy.For(ZagentInstallationProfile.InferRole(root))
                        .DevelopmentGatewayEnd);

            var files = new FilesAgentCoordinator(
                registry,
                supervisor);
            var web = new WebAgentCoordinator(
                registry,
                supervisor);
            var arcMap = new ArcMapAgentCoordinator(
                registry,
                supervisor);
            var tunnel = new TunnelAgentCoordinator(
                registry,
                supervisor);

            var filesVersion = ReadComponentVersion(
                Path.Combine(
                    root,
                    "agents",
                    "files",
                    "files.component.json"),
                "1.0.0");
            var webVersion = ReadComponentVersion(
                Path.Combine(
                    root,
                    "agents",
                    "web",
                    "web.component.json"),
                "1.0.0");
            var arcMapVersion = ReadComponentVersion(
                Path.Combine(
                    root,
                    "agents",
                    "arcmap",
                    "arcmap.component.json"),
                "1.0.0");
            var tunnelVersion = ReadComponentVersion(
                Path.Combine(
                    root,
                    "agents",
                    "tunnel",
                    "tunnel.component.json"),
                "1.0.0");

            var productionApproved =
                options.Environment == AgentEnvironment.Production;

            await files.PrepareAsync(
                filesOptions,
                filesVersion,
                productionApproved: productionApproved,
                cancellationToken: cancellationToken,
                environment: options.Environment);

            await web.PrepareAsync(
                webOptions,
                webVersion,
                productionApproved: productionApproved,
                cancellationToken: cancellationToken,
                environment: options.Environment);

            await arcMap.PrepareAsync(
                arcMapOptions,
                arcMapVersion,
                productionApproved: productionApproved,
                cancellationToken: cancellationToken,
                environment: options.Environment);

            var services = new[]
            {
                new TunnelServiceDefinition(
                    "zagent_files",
                    "Zagent Files",
                    "files",
                    $"http://{options.BindHost}:{options.FilesPort}/mcp"),
                new TunnelServiceDefinition(
                    "zagent_web",
                    "Zagent Web",
                    "web",
                    $"http://{options.BindHost}:{options.WebPort}/mcp"),
                new TunnelServiceDefinition(
                    "zagent_arcmap",
                    "Zagent ArcMap",
                    "arcmap",
                    $"http://{options.BindHost}:{options.ArcMapPort}/mcp")
            };

            await tunnel.PrepareAsync(
                tunnelOptions,
                services,
                tunnelVersion,
                productionApproved: productionApproved,
                transport: tunnelTransport,
                cancellationToken: cancellationToken,
                environment: options.Environment);

            var controllers =
                new ManagerAgentControllerRegistry();

            controllers.Register(
                new ManagerAgentController(
                    FilesAgentManifestFactory.AgentId,
                    FilesProcessFactory.ProcessId,
                    ct => files.StartAsync(
                        filesOptions,
                        cancellationToken: ct),
                    ct => files.StopAsync(ct),
                    async ct =>
                    {
                        var stop = await files.StopAsync(ct);
                        if (!stop.Success)
                        {
                            return stop with
                            {
                                Operation = "restart"
                            };
                        }

                        var start = await files.StartAsync(
                            filesOptions,
                            cancellationToken: ct);

                        return start with
                        {
                            Operation = "restart"
                        };
                    },
                    async ct =>
                    {
                        var health =
                            await files.RefreshHealthAsync(
                                filesOptions,
                                ct);

                        return new ManagerOperationResult(
                            health.Ready,
                            "refresh",
                            FilesAgentManifestFactory.AgentId,
                            health.Ready
                                ? "Files ready."
                                : health.Error ??
                                    "Files offline.");
                    }));

            controllers.Register(
                new ManagerAgentController(
                    WebAgentManifestFactory.AgentId,
                    WebProcessFactory.ProcessId,
                    ct => web.StartAsync(
                        webOptions,
                        cancellationToken: ct),
                    ct => web.StopAsync(ct),
                    async ct =>
                    {
                        var stop = await web.StopAsync(ct);
                        if (!stop.Success)
                        {
                            return stop with
                            {
                                Operation = "restart"
                            };
                        }

                        var start = await web.StartAsync(
                            webOptions,
                            cancellationToken: ct);

                        return start with
                        {
                            Operation = "restart"
                        };
                    },
                    async ct =>
                    {
                        var health =
                            await web.RefreshHealthAsync(
                                webOptions,
                                ct);

                        return new ManagerOperationResult(
                            health.Ready,
                            "refresh",
                            WebAgentManifestFactory.AgentId,
                            health.Ready
                                ? "Web ready."
                                : health.Error ??
                                    "Web offline.");
                    }));

            controllers.Register(
                new ManagerAgentController(
                    ArcMapAgentManifestFactory.AgentId,
                    ArcMapProcessFactory.ProcessId,
                    ct => arcMap.StartAsync(
                        arcMapOptions,
                        cancellationToken: ct),
                    ct => arcMap.StopAsync(ct),
                    async ct =>
                    {
                        var stop = await arcMap.StopAsync(ct);
                        if (!stop.Success)
                        {
                            return stop with
                            {
                                Operation = "restart"
                            };
                        }

                        var start = await arcMap.StartAsync(
                            arcMapOptions,
                            cancellationToken: ct);

                        return start with
                        {
                            Operation = "restart"
                        };
                    },
                    async ct =>
                    {
                        var health =
                            await arcMap.RefreshHealthAsync(
                                arcMapOptions,
                                ct);

                        return new ManagerOperationResult(
                            health.McpReady,
                            "refresh",
                            ArcMapAgentManifestFactory.AgentId,
                            health.BridgeReady
                                ? "ArcMap MCP + bridge ready."
                                : health.McpReady
                                    ? "ArcMap MCP ready; bridge offline."
                                    : health.Error ??
                                        "ArcMap offline.");
                    }));

            controllers.Register(
                new ManagerAgentController(
                    TunnelAgentManifestFactory.AgentId,
                    TunnelProcessFactory.RouterProcessId,
                    ct => tunnel.StartAsync(
                        tunnelOptions,
                        startTransport: tunnelTransport is not null,
                        cancellationToken: ct),
                    ct => tunnel.StopAsync(ct),
                    async ct =>
                    {
                        var stop = await tunnel.StopAsync(ct);
                        if (!stop.Success)
                        {
                            return stop with
                            {
                                Operation = "restart"
                            };
                        }

                        var start = await tunnel.StartAsync(
                            tunnelOptions,
                            startTransport: tunnelTransport is not null,
                            cancellationToken: ct);

                        return start with
                        {
                            Operation = "restart"
                        };
                    },
                    async ct =>
                    {
                        var health =
                            await tunnel.RefreshHealthAsync(
                                tunnelOptions,
                                ct);

                        return new ManagerOperationResult(
                            health.Ready,
                            "refresh",
                            TunnelAgentManifestFactory.AgentId,
                            health.Ready
                                ? $"Tunnel ready ({health.ToolCount} tools)."
                                : health.Error ??
                                    "Tunnel offline.");
                    }));

            var logs = new ManagerTechnicalLogStore();
            logs.Write(
                "INFO",
                "Core",
                "manager.prepare",
                "Manager control plane prepared.");

            var tunnelReader =
                new TunnelManagerReadModel(
                    new Uri(
                        $"http://{options.BindHost}:{options.TunnelPort}/"));

            var routerManager =
                new RouterManagerService(
                    new Uri(
                        $"http://{options.BindHost}:{options.TunnelPort}/"),
                    tunnelOptions.ConfigRoot);

            var filesApprovalEnvironment =
                new Dictionary<string, string>(
                    StringComparer.Ordinal)
                {
                    ["ZAGENT_FILES_ENGINE_ROOT"] =
                        Path.GetFullPath(
                            filesOptions.EngineRoot),
                    ["ZAGENT_FILES_DATA_ROOT"] =
                        Path.GetFullPath(
                            filesOptions.DataRoot),
                    ["ZAGENT_FILES_CONFIG_DIR"] =
                        Path.GetFullPath(
                            filesOptions.ConfigRoot),
                    ["ZAGENT_FILES_RUNTIME_DIR"] =
                        Path.GetFullPath(
                            filesOptions.RuntimeRoot),
                    ["ZAGENT_FILES_LOG_DIR"] =
                        Path.GetFullPath(
                            filesOptions.LogRoot),
                    ["ZAGENT_FILES_BACKUP_ROOT"] =
                        Path.GetFullPath(
                            filesOptions.BackupRoot),
                    ["ZAGENT_FILES_UPDATE_STATE_ROOT"] =
                        Path.GetFullPath(
                            filesOptions.UpdateStateRoot)
                };

            var filesReader =
                new FilesManagerReadModel(
                    new Uri(
                        $"http://{options.BindHost}:{options.FilesPort}/mcp"),
                    new FilesLocalApprovalOptions(
                        filesOptions.PythonExecutable,
                        filesOptions.EngineRoot,
                        filesApprovalEnvironment));

            var webReader =
                new WebManagerReadModel(
                    new Uri(
                        $"http://{options.BindHost}:{options.WebPort}/mcp"));

            var visualReader =
                new ManagerVisualReadModel(
                    Path.Combine(data, "visual"));

            var integrationService =
                new ManagerIntegrationService(
                    root,
                    data,
                    options.Environment,
                    registry,
                    controllers,
                    webReader,
                    logs);

            var control =
                new ManagerControlService(
                    registry,
                    supervisor,
                    controllers,
                    tunnelReader,
                    routerManager,
                    filesReader,
                    webReader,
                    logs,
                    tunnelCredentialStore,
                    developmentAgentStore,
                    machineIdentityStore,
                    integrationService,
                    visualReader);

            var pipe =
                new ManagerNamedPipeServer(
                    control,
                    options.PipeName);

            InternalManagementChannel.ValidateProvisioning();
            var host = new ManagerCoreHost(supervisor, pipe, control, options);
            host.ShutdownRequested += host.OnPipeShutdown;
            return host;
        }
        catch
        {
            await supervisor.DisposeAsync();
            throw;
        }
    }



    public Task StopAsync()
    {
        lock (_stopSync) return _stopTask ??= StopCoreAsync();
    }
    private async Task StopCoreAsync()
    {
        await ControlService.StopForShutdownAsync();
        await _pipeServer.DisposeAsync();
        ShutdownRequested -= OnPipeShutdown;
        await _supervisor.StopAllAsync();
    }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(
                ref _disposed,
                1) != 0)
        {
            return;
        }

        try { await StopAsync(); }
        catch { /* Host termination must still dispose children. */ }
        finally {
            await _pipeServer.DisposeAsync();
            await _supervisor.DisposeAsync();
        }
    }

    private static string ReadComponentVersion(
        string path,
        string fallback)
    {
        try
        {
            using var document =
                JsonDocument.Parse(
                    File.ReadAllText(path));

            return document.RootElement
                .GetProperty("version")
                .GetString() ??
                fallback;
        }
        catch
        {
            return fallback;
        }
    }

    private static string ResolveExecutable(
        string? explicitPath,
        string environmentName,
        string bundledPath,
        string executableName)
    {
        foreach (var candidate in new[]
        {
            explicitPath,
            Environment.GetEnvironmentVariable(
                environmentName),
            bundledPath,
            FindOnPath(executableName)
        })
        {
            if (string.IsNullOrWhiteSpace(candidate))
            {
                continue;
            }

            var full = Path.GetFullPath(candidate);

            if (File.Exists(full))
            {
                return full;
            }
        }

        throw new FileNotFoundException(
            $"Required runtime '{executableName}' was not found. " +
            $"Set {environmentName} or bundle it under the Zagent component runtime.");
    }

    private static string? FindOnPath(
        string executableName)
    {
        var path = Environment.GetEnvironmentVariable(
            "PATH");

        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }

        foreach (var part in path.Split(
                     Path.PathSeparator,
                     StringSplitOptions.RemoveEmptyEntries |
                     StringSplitOptions.TrimEntries))
        {
            try
            {
                var candidate = Path.Combine(
                    part,
                    executableName);

                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
            catch
            {
            }
        }

        return null;
    }
}
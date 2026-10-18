using Zagent.Core.Abstractions;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Agents.Tunnel;

public sealed class TunnelAgentCoordinator
{
    private readonly ICapabilityRegistry _registry;
    private readonly IAgentSupervisor _supervisor;
    private readonly TunnelConfigurationWriter _configurationWriter;
    private readonly TunnelRouterHealthProbe _healthProbe;

    public TunnelAgentCoordinator(
        ICapabilityRegistry registry,
        IAgentSupervisor supervisor,
        TunnelConfigurationWriter? configurationWriter = null,
        TunnelRouterHealthProbe? healthProbe = null)
    {
        _registry = registry
            ?? throw new ArgumentNullException(nameof(registry));
        _supervisor = supervisor
            ?? throw new ArgumentNullException(nameof(supervisor));
        _configurationWriter =
            configurationWriter ?? new TunnelConfigurationWriter();
        _healthProbe =
            healthProbe ?? new TunnelRouterHealthProbe();
    }

    public async Task PrepareAsync(
        TunnelIntegrationOptions options,
        IReadOnlyList<TunnelServiceDefinition> services,
        string version,
        bool productionApproved,
        TunnelTransportOptions? transport = null,
        CancellationToken cancellationToken = default,
        AgentEnvironment environment = AgentEnvironment.Production)
    {
        ArgumentNullException.ThrowIfNull(options);
        ArgumentNullException.ThrowIfNull(services);

        await _configurationWriter.WriteAsync(
            options,
            services,
            pluginConfigured: transport is not null,
            cancellationToken: cancellationToken);

        var manifest = TunnelAgentManifestFactory.Create(
            version,
            options.BindHost,
            options.RouterPort,
            environment);

        if (!_registry.TryGet(
                TunnelAgentManifestFactory.AgentId,
                out var existing))
        {
            var registration = _registry.Register(
                manifest,
                productionApproved);

            if (!registration.Success)
            {
                throw new InvalidOperationException(
                    "Tunnel capability registration failed: " +
                    string.Join("; ", registration.Errors));
            }
        }
        else if (existing is not null &&
            !string.Equals(
                existing.Manifest.Agent.Version,
                version,
                StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                $"Tunnel '{existing.Manifest.Agent.Version}' is already " +
                $"registered; cannot prepare '{version}'.");
        }

        var routerOptions = transport is null
            ? options
            : options with
            {
                ControlPlaneTunnelId = transport.TunnelId,
                ControlPlaneApiKey = transport.ApiKey
            };

        if (!_supervisor.TryGetSnapshot(
                TunnelProcessFactory.RouterProcessId,
                out _))
        {
            _supervisor.Register(
                TunnelProcessFactory.CreateRouter(routerOptions));
        }

        if (transport is not null &&
            !_supervisor.TryGetSnapshot(
                TunnelProcessFactory.TransportProcessId,
                out _))
        {
            _supervisor.Register(
                TunnelProcessFactory.CreateTransport(transport));
        }
    }

    public async Task<LifecycleOperationResult> StartAsync(
        TunnelIntegrationOptions options,
        bool startTransport,
        TimeSpan? readyTimeout = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var routerStart = await _supervisor.StartAsync(
            TunnelProcessFactory.RouterProcessId,
            cancellationToken);

        if (!routerStart.Success)
        {
            _registry.TrySetHealth(
                TunnelAgentManifestFactory.AgentId,
                AgentHealthState.Failed,
                routerStart.Message);

            return new LifecycleOperationResult(
                false,
                TunnelAgentManifestFactory.AgentId,
                "start",
                $"Router start failed: {routerStart.Message}");
        }

        var health = await WaitUntilReadyAsync(
            options,
            readyTimeout ?? TimeSpan.FromSeconds(12),
            cancellationToken);

        if (!health.Ready)
        {
            _registry.TrySetHealth(
                TunnelAgentManifestFactory.AgentId,
                AgentHealthState.Failed,
                health.Error);

            return new LifecycleOperationResult(
                false,
                TunnelAgentManifestFactory.AgentId,
                "start",
                "Router did not become ready: " +
                (health.Error ?? "timeout"));
        }

        _registry.TrySetHealth(
            TunnelAgentManifestFactory.AgentId,
            AgentHealthState.Ready);

        if (!startTransport)
        {
            return new LifecycleOperationResult(
                true,
                TunnelAgentManifestFactory.AgentId,
                "start",
                $"Router ready with {health.ToolCount} tool(s).");
        }

        if (!_supervisor.TryGetSnapshot(
                TunnelProcessFactory.TransportProcessId,
                out _))
        {
            return new LifecycleOperationResult(
                false,
                TunnelAgentManifestFactory.AgentId,
                "start",
                "Tunnel transport process is not prepared.");
        }

        var transportStart = await _supervisor.StartAsync(
            TunnelProcessFactory.TransportProcessId,
            cancellationToken);

        if (!transportStart.Success)
        {
            _registry.TrySetHealth(
                TunnelAgentManifestFactory.AgentId,
                AgentHealthState.Degraded,
                transportStart.Message);

            return new LifecycleOperationResult(
                false,
                TunnelAgentManifestFactory.AgentId,
                "start",
                $"Router ready but transport failed: {transportStart.Message}");
        }

        return new LifecycleOperationResult(
            true,
            TunnelAgentManifestFactory.AgentId,
            "start",
            $"Router ready with {health.ToolCount} tool(s); transport started.");
    }

    public async Task<TunnelRouterHealthSnapshot> RefreshHealthAsync(
        TunnelIntegrationOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var health = await _healthProbe.ProbeAsync(
            BuildHealthUri(options),
            cancellationToken);

        var state = health.Ready
            ? AgentHealthState.Ready
            : AgentHealthState.Offline;

        _registry.TrySetHealth(
            TunnelAgentManifestFactory.AgentId,
            state,
            health.Error);

        await _supervisor.ReportHealthAsync(
            TunnelProcessFactory.RouterProcessId,
            state,
            cancellationToken);

        return health;
    }

    public async Task<LifecycleOperationResult> StopAsync(
        CancellationToken cancellationToken = default)
    {
        var errors = new List<string>();

        if (_supervisor.TryGetSnapshot(
                TunnelProcessFactory.TransportProcessId,
                out _))
        {
            var transport = await _supervisor.StopAsync(
                TunnelProcessFactory.TransportProcessId,
                cancellationToken);

            if (!transport.Success)
            {
                errors.Add(
                    "transport: " +
                    (transport.Message ?? "unknown error"));
            }
        }

        if (_supervisor.TryGetSnapshot(
                TunnelProcessFactory.RouterProcessId,
                out _))
        {
            var router = await _supervisor.StopAsync(
                TunnelProcessFactory.RouterProcessId,
                cancellationToken);

            if (!router.Success)
            {
                errors.Add(
                    "router: " +
                    (router.Message ?? "unknown error"));
            }
        }

        _registry.TrySetHealth(
            TunnelAgentManifestFactory.AgentId,
            AgentHealthState.Offline);

        return new LifecycleOperationResult(
            errors.Count == 0,
            TunnelAgentManifestFactory.AgentId,
            "stop",
            errors.Count == 0
                ? "Tunnel stopped."
                : string.Join("; ", errors));
    }

    private async Task<TunnelRouterHealthSnapshot> WaitUntilReadyAsync(
        TunnelIntegrationOptions options,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var deadline = DateTimeOffset.UtcNow + timeout;
        TunnelRouterHealthSnapshot? latest = null;

        while (DateTimeOffset.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();

            latest = await _healthProbe.ProbeAsync(
                BuildHealthUri(options),
                cancellationToken);

            if (latest.Ready)
            {
                return latest;
            }

            await Task.Delay(
                TimeSpan.FromMilliseconds(100),
                cancellationToken);
        }

        return latest ?? new TunnelRouterHealthSnapshot(
            Ready: false,
            Version: null,
            ToolCount: 0,
            PluginConfigured: false,
            PluginConnected: false,
            Error: "Health probe timed out.");
    }

    private static Uri BuildHealthUri(
        TunnelIntegrationOptions options) =>
        new(
            $"http://{options.BindHost}:{options.RouterPort}/healthz");
}

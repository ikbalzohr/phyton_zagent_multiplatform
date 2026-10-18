using Zagent.Core.Abstractions;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Agents.ArcMap;

public sealed class ArcMapAgentCoordinator
{
    private readonly ICapabilityRegistry _registry;
    private readonly IAgentSupervisor _supervisor;
    private readonly ArcMapConfigurationWriter _configurationWriter;
    private readonly ArcMapHealthProbe _healthProbe;

    public ArcMapAgentCoordinator(
        ICapabilityRegistry registry,
        IAgentSupervisor supervisor,
        ArcMapConfigurationWriter? configurationWriter = null,
        ArcMapHealthProbe? healthProbe = null)
    {
        _registry = registry
            ?? throw new ArgumentNullException(nameof(registry));
        _supervisor = supervisor
            ?? throw new ArgumentNullException(nameof(supervisor));
        _configurationWriter =
            configurationWriter ?? new ArcMapConfigurationWriter();
        _healthProbe =
            healthProbe ?? new ArcMapHealthProbe();
    }

    public async Task PrepareAsync(
        ArcMapIntegrationOptions options,
        string version,
        bool productionApproved,
        CancellationToken cancellationToken = default,
        AgentEnvironment environment = AgentEnvironment.Production)
    {
        ArgumentNullException.ThrowIfNull(options);

        await _configurationWriter.WriteAsync(
            options,
            cancellationToken);

        var manifest = ArcMapAgentManifestFactory.Create(
            version,
            options.BindHost,
            options.Port,
            options.McpPath,
            environment);

        if (!_registry.TryGet(
                ArcMapAgentManifestFactory.AgentId,
                out var existing))
        {
            var registration = _registry.Register(
                manifest,
                productionApproved);

            if (!registration.Success)
            {
                throw new InvalidOperationException(
                    "ArcMap capability registration failed: " +
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
                $"ArcMap '{existing.Manifest.Agent.Version}' is already " +
                $"registered; cannot prepare '{version}'.");
        }

        if (!_supervisor.TryGetSnapshot(
                ArcMapProcessFactory.ProcessId,
                out _))
        {
            _supervisor.Register(
                ArcMapProcessFactory.Create(options));
        }
    }

    public async Task<LifecycleOperationResult> StartAsync(
        ArcMapIntegrationOptions options,
        TimeSpan? readyTimeout = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var start = await _supervisor.StartAsync(
            ArcMapProcessFactory.ProcessId,
            cancellationToken);

        if (!start.Success)
        {
            _registry.TrySetHealth(
                ArcMapAgentManifestFactory.AgentId,
                AgentHealthState.Failed,
                start.Message);

            return new LifecycleOperationResult(
                false,
                ArcMapAgentManifestFactory.AgentId,
                "start",
                start.Message);
        }

        var health = await WaitUntilMcpReadyAsync(
            options,
            readyTimeout ?? TimeSpan.FromSeconds(15),
            cancellationToken);

        if (!health.McpReady)
        {
            _registry.TrySetHealth(
                ArcMapAgentManifestFactory.AgentId,
                AgentHealthState.Failed,
                health.Error);

            return new LifecycleOperationResult(
                false,
                ArcMapAgentManifestFactory.AgentId,
                "start",
                "ArcMap MCP did not become ready: " +
                (health.Error ?? "timeout"));
        }

        var state = health.BridgeReady
            ? AgentHealthState.Ready
            : AgentHealthState.Degraded;

        _registry.TrySetHealth(
            ArcMapAgentManifestFactory.AgentId,
            state,
            health.Error);

        return new LifecycleOperationResult(
            true,
            ArcMapAgentManifestFactory.AgentId,
            "start",
            health.BridgeReady
                ? $"ArcMap MCP and live bridge ready with {health.ToolCount} tool(s)."
                : $"ArcMap MCP ready with {health.ToolCount} tool(s); external ArcMap bridge is offline.");
    }

    public async Task<ArcMapHealthSnapshot> RefreshHealthAsync(
        ArcMapIntegrationOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var health = await _healthProbe.ProbeAsync(
            BuildMcpUri(options),
            cancellationToken);

        var state = !health.McpReady
            ? AgentHealthState.Offline
            : health.BridgeReady
                ? AgentHealthState.Ready
                : AgentHealthState.Degraded;

        _registry.TrySetHealth(
            ArcMapAgentManifestFactory.AgentId,
            state,
            health.Error);

        await _supervisor.ReportHealthAsync(
            ArcMapProcessFactory.ProcessId,
            state,
            cancellationToken);

        return health;
    }

    public async Task<LifecycleOperationResult> StopAsync(
        CancellationToken cancellationToken = default)
    {
        if (!_supervisor.TryGetSnapshot(
                ArcMapProcessFactory.ProcessId,
                out _))
        {
            _registry.TrySetHealth(
                ArcMapAgentManifestFactory.AgentId,
                AgentHealthState.Offline);

            return new LifecycleOperationResult(
                true,
                ArcMapAgentManifestFactory.AgentId,
                "stop",
                "ArcMap MCP was not registered with supervisor.");
        }

        var stop = await _supervisor.StopAsync(
            ArcMapProcessFactory.ProcessId,
            cancellationToken);

        _registry.TrySetHealth(
            ArcMapAgentManifestFactory.AgentId,
            stop.Success
                ? AgentHealthState.Offline
                : AgentHealthState.Failed,
            stop.Success
                ? null
                : stop.Message);

        return new LifecycleOperationResult(
            stop.Success,
            ArcMapAgentManifestFactory.AgentId,
            "stop",
            stop.Message);
    }

    public static Uri BuildMcpUri(
        ArcMapIntegrationOptions options)
    {
        var path = options.McpPath.StartsWith(
            "/",
            StringComparison.Ordinal)
            ? options.McpPath
            : "/" + options.McpPath;

        return new Uri(
            $"http://{options.BindHost}:{options.Port}{path}");
    }

    private async Task<ArcMapHealthSnapshot> WaitUntilMcpReadyAsync(
        ArcMapIntegrationOptions options,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var deadline = DateTimeOffset.UtcNow + timeout;
        ArcMapHealthSnapshot? latest = null;

        while (DateTimeOffset.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();

            latest = await _healthProbe.ProbeAsync(
                BuildMcpUri(options),
                cancellationToken);

            if (latest.McpReady)
            {
                return latest;
            }

            await Task.Delay(
                TimeSpan.FromMilliseconds(100),
                cancellationToken);
        }

        return latest ?? new ArcMapHealthSnapshot(
            false,
            false,
            0,
            false,
            false,
            null,
            null,
            null,
            null,
            "Health probe timed out.");
    }
}

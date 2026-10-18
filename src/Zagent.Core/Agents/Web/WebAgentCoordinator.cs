using Zagent.Core.Abstractions;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Agents.Web;

public sealed class WebAgentCoordinator
{
    private readonly ICapabilityRegistry _registry;
    private readonly IAgentSupervisor _supervisor;
    private readonly WebConfigurationWriter _configurationWriter;
    private readonly WebHealthProbe _healthProbe;

    public WebAgentCoordinator(
        ICapabilityRegistry registry,
        IAgentSupervisor supervisor,
        WebConfigurationWriter? configurationWriter = null,
        WebHealthProbe? healthProbe = null)
    {
        _registry = registry
            ?? throw new ArgumentNullException(nameof(registry));
        _supervisor = supervisor
            ?? throw new ArgumentNullException(nameof(supervisor));
        _configurationWriter =
            configurationWriter ?? new WebConfigurationWriter();
        _healthProbe =
            healthProbe ?? new WebHealthProbe();
    }

    public async Task PrepareAsync(
        WebIntegrationOptions options,
        string version,
        bool productionApproved,
        CancellationToken cancellationToken = default,
        AgentEnvironment environment = AgentEnvironment.Production)
    {
        ArgumentNullException.ThrowIfNull(options);

        await _configurationWriter.WriteAsync(
            options,
            cancellationToken);

        var manifest = WebAgentManifestFactory.Create(
            version,
            options.BindHost,
            options.Port,
            environment);

        if (!_registry.TryGet(
                WebAgentManifestFactory.AgentId,
                out var existing))
        {
            var registration = _registry.Register(
                manifest,
                productionApproved);

            if (!registration.Success)
            {
                throw new InvalidOperationException(
                    "Web capability registration failed: " +
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
                $"Web '{existing.Manifest.Agent.Version}' is already " +
                $"registered; cannot prepare '{version}'.");
        }

        if (!_supervisor.TryGetSnapshot(
                WebProcessFactory.ProcessId,
                out _))
        {
            _supervisor.Register(
                WebProcessFactory.Create(options));
        }
    }

    public async Task<LifecycleOperationResult> StartAsync(
        WebIntegrationOptions options,
        TimeSpan? readyTimeout = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var start = await _supervisor.StartAsync(
            WebProcessFactory.ProcessId,
            cancellationToken);

        if (!start.Success)
        {
            _registry.TrySetHealth(
                WebAgentManifestFactory.AgentId,
                AgentHealthState.Failed,
                start.Message);

            return new LifecycleOperationResult(
                false,
                WebAgentManifestFactory.AgentId,
                "start",
                start.Message);
        }

        var health = await WaitUntilReadyAsync(
            options,
            readyTimeout ?? TimeSpan.FromSeconds(15),
            cancellationToken);

        if (!health.Ready)
        {
            _registry.TrySetHealth(
                WebAgentManifestFactory.AgentId,
                AgentHealthState.Failed,
                health.Error);

            return new LifecycleOperationResult(
                false,
                WebAgentManifestFactory.AgentId,
                "start",
                "Web service did not become ready: " +
                (health.Error ?? "timeout"));
        }

        _registry.TrySetHealth(
            WebAgentManifestFactory.AgentId,
            AgentHealthState.Ready);

        return new LifecycleOperationResult(
            true,
            WebAgentManifestFactory.AgentId,
            "start",
            $"Web ready at {BuildMcpUri(options)}.");
    }

    public async Task<WebHealthSnapshot> RefreshHealthAsync(
        WebIntegrationOptions options,
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
            WebAgentManifestFactory.AgentId,
            state,
            health.Error);

        await _supervisor.ReportHealthAsync(
            WebProcessFactory.ProcessId,
            state,
            cancellationToken);

        return health;
    }

    public async Task<LifecycleOperationResult> StopAsync(
        CancellationToken cancellationToken = default)
    {
        if (!_supervisor.TryGetSnapshot(
                WebProcessFactory.ProcessId,
                out _))
        {
            _registry.TrySetHealth(
                WebAgentManifestFactory.AgentId,
                AgentHealthState.Offline);

            return new LifecycleOperationResult(
                true,
                WebAgentManifestFactory.AgentId,
                "stop",
                "Web service was not registered with supervisor.");
        }

        var stop = await _supervisor.StopAsync(
            WebProcessFactory.ProcessId,
            cancellationToken);

        _registry.TrySetHealth(
            WebAgentManifestFactory.AgentId,
            stop.Success
                ? AgentHealthState.Offline
                : AgentHealthState.Failed,
            stop.Success
                ? null
                : stop.Message);

        return new LifecycleOperationResult(
            stop.Success,
            WebAgentManifestFactory.AgentId,
            "stop",
            stop.Message);
    }

    public static Uri BuildHealthUri(
        WebIntegrationOptions options) =>
        new($"http://{options.BindHost}:{options.Port}/health");

    public static Uri BuildMcpUri(
        WebIntegrationOptions options) =>
        new($"http://{options.BindHost}:{options.Port}/mcp");

    private async Task<WebHealthSnapshot> WaitUntilReadyAsync(
        WebIntegrationOptions options,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var deadline = DateTimeOffset.UtcNow + timeout;
        WebHealthSnapshot? latest = null;

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

        return latest ?? new WebHealthSnapshot(
            false,
            null,
            null,
            false,
            false,
            false,
            false,
            "Health probe timed out.");
    }
}

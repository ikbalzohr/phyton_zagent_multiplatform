using Zagent.Core.Abstractions;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Agents.Files;

public sealed class FilesAgentCoordinator
{
    private readonly ICapabilityRegistry _registry;
    private readonly IAgentSupervisor _supervisor;
    private readonly FilesConfigurationWriter _configurationWriter;
    private readonly FilesHealthProbe _healthProbe;

    public FilesAgentCoordinator(
        ICapabilityRegistry registry,
        IAgentSupervisor supervisor,
        FilesConfigurationWriter? configurationWriter = null,
        FilesHealthProbe? healthProbe = null)
    {
        _registry = registry
            ?? throw new ArgumentNullException(nameof(registry));
        _supervisor = supervisor
            ?? throw new ArgumentNullException(nameof(supervisor));
        _configurationWriter =
            configurationWriter ?? new FilesConfigurationWriter();
        _healthProbe =
            healthProbe ?? new FilesHealthProbe();
    }

    public async Task PrepareAsync(
        FilesIntegrationOptions options,
        string version,
        bool productionApproved,
        CancellationToken cancellationToken = default,
        AgentEnvironment environment = AgentEnvironment.Production)
    {
        ArgumentNullException.ThrowIfNull(options);

        await _configurationWriter.WriteAsync(
            options,
            cancellationToken);

        var manifest = FilesAgentManifestFactory.Create(
            version,
            options.BindHost,
            options.Port,
            environment);

        if (!_registry.TryGet(
                FilesAgentManifestFactory.AgentId,
                out var existing))
        {
            var registration = _registry.Register(
                manifest,
                productionApproved);

            if (!registration.Success)
            {
                throw new InvalidOperationException(
                    "Files capability registration failed: " +
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
                $"Files '{existing.Manifest.Agent.Version}' is already " +
                $"registered; cannot prepare '{version}'.");
        }

        if (!_supervisor.TryGetSnapshot(
                FilesProcessFactory.ProcessId,
                out _))
        {
            _supervisor.Register(
                FilesProcessFactory.Create(options));
        }
    }

    public async Task<LifecycleOperationResult> StartAsync(
        FilesIntegrationOptions options,
        TimeSpan? readyTimeout = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var start = await _supervisor.StartAsync(
            FilesProcessFactory.ProcessId,
            cancellationToken);

        if (!start.Success)
        {
            _registry.TrySetHealth(
                FilesAgentManifestFactory.AgentId,
                AgentHealthState.Failed,
                start.Message);

            return new LifecycleOperationResult(
                false,
                FilesAgentManifestFactory.AgentId,
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
                FilesAgentManifestFactory.AgentId,
                AgentHealthState.Failed,
                health.Error);

            return new LifecycleOperationResult(
                false,
                FilesAgentManifestFactory.AgentId,
                "start",
                "Files MCP did not become ready: " +
                (health.Error ?? "timeout"));
        }

        _registry.TrySetHealth(
            FilesAgentManifestFactory.AgentId,
            AgentHealthState.Ready);

        return new LifecycleOperationResult(
            true,
            FilesAgentManifestFactory.AgentId,
            "start",
            $"Files MCP ready at {BuildMcpUri(options)}.");
    }

    public async Task<FilesHealthSnapshot> RefreshHealthAsync(
        FilesIntegrationOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var health = await _healthProbe.ProbeAsync(
            BuildMcpUri(options),
            cancellationToken);

        var state = health.Ready
            ? AgentHealthState.Ready
            : AgentHealthState.Offline;

        _registry.TrySetHealth(
            FilesAgentManifestFactory.AgentId,
            state,
            health.Error);

        await _supervisor.ReportHealthAsync(
            FilesProcessFactory.ProcessId,
            state,
            cancellationToken);

        return health;
    }

    public async Task<LifecycleOperationResult> StopAsync(
        CancellationToken cancellationToken = default)
    {
        if (!_supervisor.TryGetSnapshot(
                FilesProcessFactory.ProcessId,
                out _))
        {
            _registry.TrySetHealth(
                FilesAgentManifestFactory.AgentId,
                AgentHealthState.Offline);

            return new LifecycleOperationResult(
                true,
                FilesAgentManifestFactory.AgentId,
                "stop",
                "Files service was not registered with supervisor.");
        }

        var stop = await _supervisor.StopAsync(
            FilesProcessFactory.ProcessId,
            cancellationToken);

        _registry.TrySetHealth(
            FilesAgentManifestFactory.AgentId,
            stop.Success
                ? AgentHealthState.Offline
                : AgentHealthState.Failed,
            stop.Success
                ? null
                : stop.Message);

        return new LifecycleOperationResult(
            stop.Success,
            FilesAgentManifestFactory.AgentId,
            "stop",
            stop.Message);
    }

    public static Uri BuildMcpUri(
        FilesIntegrationOptions options) =>
        new($"http://{options.BindHost}:{options.Port}/mcp");

    private async Task<FilesHealthSnapshot> WaitUntilReadyAsync(
        FilesIntegrationOptions options,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var deadline = DateTimeOffset.UtcNow + timeout;
        FilesHealthSnapshot? latest = null;

        while (DateTimeOffset.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();

            latest = await _healthProbe.ProbeAsync(
                BuildMcpUri(options),
                cancellationToken);

            if (latest.Ready)
            {
                return latest;
            }

            await Task.Delay(
                TimeSpan.FromMilliseconds(100),
                cancellationToken);
        }

        return latest ?? new FilesHealthSnapshot(
            false,
            null,
            null,
            null,
            "Health probe timed out.");
    }
}

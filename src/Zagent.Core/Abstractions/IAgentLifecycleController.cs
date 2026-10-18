using Zagent.Shared.Contracts;

namespace Zagent.Core.Abstractions;

public interface IAgentLifecycleController
{
    Task<LifecycleOperationResult> StartAsync(
        string agentId,
        CancellationToken cancellationToken = default);

    Task<LifecycleOperationResult> StopAsync(
        string agentId,
        CancellationToken cancellationToken = default);

    Task<LifecycleOperationResult> RestartAsync(
        string agentId,
        CancellationToken cancellationToken = default);
}

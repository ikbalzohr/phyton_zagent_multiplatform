using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Abstractions;

public interface IAgentSupervisor : IAgentLifecycleController, IAsyncDisposable
{
    void Register(AgentProcessDefinition definition);

    bool TryGetSnapshot(
        string agentId,
        out AgentProcessSnapshot? snapshot);

    IReadOnlyList<AgentProcessSnapshot> Snapshot();

    Task<LifecycleOperationResult> ReportHealthAsync(
        string agentId,
        AgentHealthState health,
        CancellationToken cancellationToken = default);

    Task<SupervisorShutdownResult> StopAllAsync(
        CancellationToken cancellationToken = default);
}

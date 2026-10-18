using Zagent.Shared.Contracts;

namespace Zagent.Core.Abstractions;

public interface IAgentHealthProbe
{
    Task<AgentHealthState> ProbeAsync(
        RegisteredAgent agent,
        CancellationToken cancellationToken = default);
}

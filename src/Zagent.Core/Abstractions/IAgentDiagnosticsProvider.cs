using Zagent.Shared.Contracts;

namespace Zagent.Core.Abstractions;

public interface IAgentDiagnosticsProvider
{
    Task<AgentDiagnosticsSnapshot> CaptureAsync(
        RegisteredAgent agent,
        CancellationToken cancellationToken = default);
}

using Zagent.Shared.Contracts;

namespace Zagent.Core.Abstractions;

public interface ICapabilityRegistry
{
    RegistrationResult Register(
        AgentManifest manifest,
        bool productionApproved = false);

    bool TryGet(string agentId, out RegisteredAgent? agent);

    bool TrySetHealth(
        string agentId,
        AgentHealthState health,
        string? lastError = null);

    IReadOnlyList<RegisteredAgent> Snapshot();

    IReadOnlyList<RegisteredAgent> FindOwners(string capabilityName);
}

using Zagent.Core.Abstractions;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Registry;

public sealed class CapabilityRegistry : ICapabilityRegistry
{
    private readonly object _gate = new();
    private readonly Dictionary<string, RegisteredAgent> _agents =
        new(StringComparer.Ordinal);
    private readonly IAgentManifestValidator _validator;
    private readonly TimeProvider _timeProvider;

    public CapabilityRegistry(
        IAgentManifestValidator? validator = null,
        TimeProvider? timeProvider = null)
    {
        _validator = validator ?? new AgentManifestValidator();
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public RegistrationResult Register(
        AgentManifest manifest,
        bool productionApproved = false)
    {
        ArgumentNullException.ThrowIfNull(manifest);

        var validation = _validator.Validate(manifest);
        if (!validation.IsValid)
        {
            return new RegistrationResult(false, null, validation.Errors);
        }

        if (manifest.Environment == AgentEnvironment.Production &&
            !productionApproved)
        {
            return RegistrationResult.Rejected(
                "Production registration requires explicit production approval.");
        }

        lock (_gate)
        {
            if (_agents.ContainsKey(manifest.Agent.Id))
            {
                return RegistrationResult.Rejected(
                    $"Agent '{manifest.Agent.Id}' is already registered.");
            }

            var registered = new RegisteredAgent(
                Manifest: manifest,
                RegistrationState: RegistrationState.Registered,
                Health: AgentHealthState.Unknown,
                ProductionApproved: productionApproved,
                RegisteredAtUtc: _timeProvider.GetUtcNow());

            _agents.Add(manifest.Agent.Id, registered);
            return RegistrationResult.Accepted(registered);
        }
    }

    public bool TryGet(string agentId, out RegisteredAgent? agent)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(agentId);

        lock (_gate)
        {
            if (_agents.TryGetValue(agentId, out var found))
            {
                agent = found;
                return true;
            }

            agent = null;
            return false;
        }
    }

    public bool TrySetHealth(
        string agentId,
        AgentHealthState health,
        string? lastError = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(agentId);

        lock (_gate)
        {
            if (!_agents.TryGetValue(agentId, out var current))
            {
                return false;
            }

            _agents[agentId] = current with
            {
                Health = health,
                LastError = lastError
            };
            return true;
        }
    }

    public IReadOnlyList<RegisteredAgent> Snapshot()
    {
        lock (_gate)
        {
            return _agents.Values
                .OrderBy(agent => agent.Manifest.Agent.Id, StringComparer.Ordinal)
                .ToArray();
        }
    }

    public IReadOnlyList<RegisteredAgent> FindOwners(string capabilityName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(capabilityName);

        lock (_gate)
        {
            return _agents.Values
                .Where(agent => agent.Manifest.Capabilities.Any(
                    capability => string.Equals(
                        capability.Name,
                        capabilityName,
                        StringComparison.Ordinal)))
                .OrderBy(agent => agent.Manifest.Agent.Id, StringComparer.Ordinal)
                .ToArray();
        }
    }
}

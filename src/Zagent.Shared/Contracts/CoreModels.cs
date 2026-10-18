namespace Zagent.Shared.Contracts;

public sealed record CoreRuntimeSnapshot(
    string ProductName,
    string CoreVersion,
    string AgentProtocolVersion,
    string CapabilityRegistryVersion,
    int RegisteredAgents,
    DateTimeOffset CapturedAtUtc);

public sealed record LifecycleOperationResult(
    bool Success,
    string AgentId,
    string Operation,
    string? Message = null);

public sealed record AgentDiagnosticsSnapshot(
    string AgentId,
    AgentHealthState Health,
    IReadOnlyDictionary<string, string> Values,
    DateTimeOffset CapturedAtUtc);

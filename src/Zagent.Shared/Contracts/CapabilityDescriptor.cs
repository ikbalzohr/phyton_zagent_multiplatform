namespace Zagent.Shared.Contracts;

public sealed record CapabilityDescriptor(
    string Name,
    string Description,
    CapabilityAccess Access,
    CapabilityExecution Execution,
    CapabilityApproval Approval,
    bool SupportsCancel,
    bool SupportsProgress = false,
    bool SupportsResume = false,
    ResourcePolicy ResourcePolicy = ResourcePolicy.None);

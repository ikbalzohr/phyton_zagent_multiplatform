namespace Zagent.Shared.Contracts;

public enum AgentEnvironment
{
    Development,
    Staging,
    Production
}

public enum AgentHealthState
{
    Unknown,
    Ready,
    Degraded,
    Offline,
    Failed
}

public enum RegistrationState
{
    Discovered,
    Validating,
    Registered,
    Quarantined,
    Disabled
}

public enum CapabilityAccess
{
    Read,
    Write,
    Action,
    Admin
}

public enum CapabilityExecution
{
    Fast,
    Background,
    Exclusive
}

public enum CapabilityApproval
{
    None,
    Policy,
    User,
    Admin
}

public enum ResourcePolicy
{
    None,
    Shared,
    ReadLock,
    WriteLock,
    Exclusive
}

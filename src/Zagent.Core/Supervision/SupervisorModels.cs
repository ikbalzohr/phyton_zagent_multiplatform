using Zagent.Shared.Contracts;

namespace Zagent.Core.Supervision;

public enum DesiredProcessState
{
    Stopped,
    Running
}

public enum AgentProcessState
{
    Stopped,
    Starting,
    Running,
    Stopping,
    Faulted,
    BackingOff
}

public sealed record AgentProcessDefinition(
    string AgentId,
    string ExecutablePath,
    IReadOnlyList<string> Arguments,
    string? WorkingDirectory = null,
    IReadOnlyDictionary<string, string>? EnvironmentVariables = null,
    int GracefulShutdownSeconds = 5,
    bool AutoRestart = false,
    int MaxRestartAttempts = 3,
    int RestartBackoffMilliseconds = 250,
    int RestartBackoffMaxMilliseconds = 5000,
    int HealthRestartGraceMilliseconds = 0);

public sealed record AgentProcessSnapshot(
    string AgentId,
    DesiredProcessState DesiredState,
    AgentProcessState State,
    int? ProcessId,
    DateTimeOffset? StartedAtUtc,
    int? LastExitCode,
    string? LastError,
    bool ProcessTreeOwned,
    int RestartAttempts,
    DateTimeOffset? NextRestartAtUtc,
    AgentHealthState LastReportedHealth);

public sealed record SupervisorShutdownResult(
    bool Success,
    IReadOnlyList<string> FailedAgents);

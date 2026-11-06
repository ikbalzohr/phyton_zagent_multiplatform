using System.Text.Json;
using Zagent.Shared.Contracts;
using Zagent.Shared.Installation;

namespace Zagent.Shared.Manager;

public static class ManagerProtocol
{
    public const string Version = "1.0";
    public const string DefaultPipeName = "Zagent.Manager.v1";
    public static string ForRoot(string installRoot) =>
        ZagentInstanceScope.PipeName(installRoot);
}

public sealed record ManagerRequestEnvelope(
    string ProtocolVersion,
    string RequestId,
    string Method,
    JsonElement? Parameters = null);

public sealed record ManagerResponseEnvelope(
    string ProtocolVersion,
    string RequestId,
    bool Success,
    JsonElement? Result = null,
    string? Error = null);

public sealed record ManagerVisualSnapshot(
    bool Available,
    string? Id,
    string? Source,
    string? Kind,
    string? Label,
    DateTimeOffset? CapturedAtUtc,
    string? MimeType,
    long Bytes,
    string? DeviceId,
    string? DeviceName,
    string? WorkspaceId,
    string? Sha256,
    string? Error = null);

public sealed record ManagerDashboardSnapshot(
    string ProductName,
    string CoreVersion,
    int RegisteredAgents,
    int CapabilityCount,
    int RunningProcesses,
    int ActiveTasks,
    int PendingApprovals,
    IReadOnlyList<ManagerAgentRow> Agents,
    DateTimeOffset CapturedAtUtc)
{
    public IReadOnlyList<string> UnavailableDependencies { get; init; } = Array.Empty<string>();
}

public sealed record ManagerAgentRow(
    string AgentId,
    string Name,
    string Version,
    AgentEnvironment Environment,
    RegistrationState RegistrationState,
    AgentHealthState Health,
    bool ProductionApproved,
    string ProcessId,
    string DesiredState,
    string ProcessState,
    int? OsProcessId,
    bool ProcessTreeOwned,
    int RestartAttempts,
    string Endpoint,
    int CapabilityCount,
    string? LastError = null,
    string? Detail = null);

public sealed record ManagerCapabilityRow(
    string AgentId,
    string AgentName,
    string AgentVersion,
    string Capability,
    CapabilityAccess Access,
    CapabilityExecution Execution,
    CapabilityApproval Approval,
    ResourcePolicy ResourcePolicy,
    bool SupportsCancel,
    bool SupportsProgress,
    bool SupportsResume,
    AgentEnvironment Environment,
    AgentHealthState Health);

public sealed record ManagerTaskRow(
    string TaskId,
    string PrincipalId,
    string WorkspaceId,
    string RequestId,
    string Agent,
    string Tool,
    string State,
    double Progress,
    string AccessMode,
    int Priority,
    string ResourceKey,
    double? CreatedAt,
    double? StartedAt,
    double? FinishedAt,
    string StopMode,
    bool CanStop,
    bool IsWrite,
    bool IsDestructive,
    string Risk,
    string Details);

public sealed record ManagerProfileRow(
    string Name,
    string Root,
    string Mode,
    bool Enabled,
    bool Active,
    bool AuthorizedByUser,
    string AuthorizationSource,
    string ExecutionAccess = "legacy");

public sealed record ManagerApprovalRow(
    string RequestId,
    string Kind,
    string Status,
    string RequestedBy,
    double? CreatedAt,
    string Summary,
    bool PrivilegeEscalation,
    string Source = "Files",
    bool CanResolveLocally = true);

public sealed record ManagerTechnicalLogRow(
    DateTimeOffset TimestampUtc,
    string Level,
    string Source,
    string Event,
    string Message);

public sealed record ManagerMonitoringSnapshot(
    IReadOnlyList<ManagerTaskRow> Tasks,
    int QueueDepth,
    IReadOnlyDictionary<string, int> QueueDepths,
    DateTimeOffset CapturedAtUtc);

public sealed record ManagerWorkspaceRow(
    string WorkspaceId,
    string ActiveProfile,
    string MountedProfiles,
    double? Updated);

public sealed record ManagerProfilesSnapshot(
    IReadOnlyList<ManagerProfileRow> Profiles,
    IReadOnlyList<ManagerWorkspaceRow> Workspaces,
    IReadOnlyList<ManagerApprovalRow> PendingApprovals,
    string DefaultProfile,
    DateTimeOffset CapturedAtUtc,
    bool WebBridgeConnected = false,
    bool WebBridgeAuthorized = false)
{
    public IReadOnlyList<string> UnavailableDependencies { get; init; } = Array.Empty<string>();
}

public sealed record ManagerRouterServiceRow(
    string Id,
    string Type,
    string Name,
    string Namespace,
    string Url,
    string AgentStatus,
    string McpStatus,
    string Routing,
    int Tools,
    bool Permanent,
    bool Enabled,
    string LastError);

public sealed record ManagerRouterSnapshot(
    IReadOnlyList<ManagerRouterServiceRow> Services,
    int ToolCount,
    string RouterStatus,
    DateTimeOffset CapturedAtUtc);

public sealed record ManagerLogsSnapshot(
    IReadOnlyList<ManagerTechnicalLogRow> Technical,
    DateTimeOffset CapturedAtUtc);

public sealed record ManagerLifecycleRequest(string AgentId, string Operation);
public sealed record ManagerProfileSwitchRequest(string Name);
public sealed record ManagerRouterActionRequest(string Action, string? ServiceId = null);
public sealed record ManagerTaskCancelRequest(string TaskId);
public sealed record ManagerApprovalActionRequest(string RequestId, string Action, string? Reason = null, string Source = "Files");
public sealed record ManagerProfileAddRequest(string Name, string Root, string Mode = "read-only");
public sealed record ManagerProfileRemoveRequest(string Name);
public sealed record ManagerProfileUpdateRequest(string Name, string? Root = null, string? Mode = null, bool? Enabled = null, string? Description = null);
public sealed record ManagerRefreshRequest(bool IncludeCompletedTasks = false, int TaskLimit = 100);

public sealed record ManagerTunnelSettingsSnapshot(
    string TunnelId, bool ApiKeyConfigured, string ApiKeyMasked, bool RequiresCoreRestart, string CredentialProtection);
public sealed record ManagerTunnelSettingsUpdateRequest(string TunnelId, string? ApiKey = null);

public sealed record ManagerDevelopmentAgentRow(
    string Id, string Name, string Namespace, string Url, bool Enabled, int TimeoutSeconds);
public sealed record ManagerDevelopmentAgentRequest(string Name, string Namespace, string Url, int TimeoutSeconds = 25);
public sealed record ManagerDevelopmentAgentRemoveRequest(string Id);

public sealed record ManagerMachineIdentitySnapshot(
    string DeviceId,
    string DeviceName,
    string BindingFingerprint,
    DateTimeOffset CreatedAtUtc,
    string BindingState,
    string Protection,
    string TargetValidationMode,
    string DeviceAlias = "",
    string InstallationId = "",
    string ShortFingerprint = "",
    string TrustState = "unverified",
    int SessionBindingCount = 0,
    bool NoSilentFallback = true,
    string RegistryScope = "",
    bool SharedAuthorityConfigured = false);

public sealed record ManagerMachineIdentityRenameRequest(string DeviceAlias);

public sealed record ManagerIntegrationSnapshot(
    string ChromeExtensionStatus,
    string ChromeNativeBridgeStatus,
    bool ChromeConnected,
    bool ChromeAuthorized,
    bool ChromeNativeAttached,
    bool ChromeProfileBound,
    string ChromeProfile,
    string ArcMapDesktopStatus,
    string ArcMapAddInStatus,
    string ArcMapToolsStatus,
    string ArcMapMcpStatus,
    string ArcMapBridgeStatus,
    string ArcMapCurrentMxdStatus,
    DateTimeOffset CapturedAtUtc)
{
    public bool ChromePersistentConsent { get; init; }
    public bool ChromeReconnectAvailable { get; init; }
    public int ChromeApprovedTabCount { get; init; }
    public IReadOnlyList<string> ChromeProfileOptions { get; init; } = Array.Empty<string>();
}

public sealed record ManagerIntegrationActionRequest(
    string Action,
    string? ChromeProfile = null);

public sealed record ManagerIntegrationActionResult(
    bool Success,
    string Action,
    string Message,
    ManagerIntegrationSnapshot Snapshot);

public sealed record ManagerOperationResult(bool Success, string Operation, string Target, string Message);

public sealed record ManagerHealthSummary(
    bool TunnelReachable,
    bool FilesReachable,
    bool WebReachable,
    bool ArcMapMcpReachable,
    bool ArcMapBridgeReady,
    int RoutedToolCount,
    DateTimeOffset CapturedAtUtc);

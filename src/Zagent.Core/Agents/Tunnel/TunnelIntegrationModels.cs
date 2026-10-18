namespace Zagent.Core.Agents.Tunnel;

public sealed record TunnelServiceDefinition(
    string Id,
    string Name,
    string Namespace,
    string Url,
    bool Enabled = true,
    bool Permanent = true,
    int TimeoutSeconds = 30);

public sealed record TunnelIntegrationOptions(
    string PythonExecutable,
    string EngineRoot,
    string ConfigRoot,
    string RuntimeRoot,
    string ChatLogPath,
    string BindHost,
    int RouterPort,
    string McpPath = "/mcp",
    string LogLevel = "info",
    string DeviceId = "",
    string DeviceName = "",
    string DeviceAlias = "",
    string DeviceFingerprint = "",
    string InstallationId = "",
    string DeviceBinding = "",
    string IdentityEnforcement = "mandatory",
    string ControlPlaneTunnelId = "",
    string ControlPlaneApiKey = "",
    string PluginAudience = "zagent-production",
    string PluginDisplayName = "Zagent",
    string PluginAccessMode = "manager-approval",
    string PluginAccessRoot = "",
    string PluginAccessEnforcement = "mandatory",
    string PluginFallback = "",
    string PluginParentAudience = "zagent-production",
    string ArcMapMcpUrl = "");

public sealed record TunnelTransportOptions(
    string ClientExecutable,
    string WorkingDirectory,
    string TunnelId,
    string ApiKey,
    string HealthListenAddress,
    string RouterMcpUrl,
    string DeviceId = "",
    string DeviceName = "",
    string DeviceBinding = "");

public sealed record TunnelRouterHealthSnapshot(
    bool Ready,
    string? Version,
    int ToolCount,
    bool PluginConfigured,
    bool PluginConnected,
    string? Error);
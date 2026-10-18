namespace Zagent.Core.Agents.ArcMap;

public sealed record ArcMapIntegrationOptions(
    string PythonExecutable,
    string EngineRoot,
    string DataRoot,
    string ConfigRoot,
    string IpcRoot,
    string RuntimeRoot,
    string LogRoot,
    string BindHost,
    int Port,
    string McpPath = "/mcp",
    string? LegacyManualBaseline = null,
    int CommandTimeoutSeconds = 15,
    string DeviceId = "",
    string DeviceName = "",
    int TunnelPort = 18810);

public sealed record ArcMapHealthSnapshot(
    bool McpReady,
    bool BridgeReady,
    int ToolCount,
    bool Stage2Loaded,
    bool Stage3Loaded,
    string? ArcGisVersion,
    string? CurrentMxd,
    string? ServerName,
    string? ProtocolVersion,
    string? Error);
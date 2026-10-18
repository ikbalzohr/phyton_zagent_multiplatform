namespace Zagent.Core.Agents.Web;

public sealed record WebIntegrationOptions(
    string NodeExecutable,
    string EngineRoot,
    string DataRoot,
    string ConfigRoot,
    string RuntimeRoot,
    string ArtifactsRoot,
    string LogRoot,
    string BindHost,
    int Port,
    string Browser = "chrome",
    string RuntimeMode = "native_attach",
    string SessionIsolationMode = "tabs",
    string? ChromeExecutablePath = null,
    bool BridgeRequired = true,
    bool NativeAutoAttach = true,
    bool NativeAttachOnDemand = true,
    string DeviceId = "",
    string DeviceName = "",
    string BridgeEnvironment = "PRODUCTION");

public sealed record WebHealthSnapshot(
    bool Ready,
    string? Service,
    string? Version,
    bool NativeAttached,
    bool BridgeRequired,
    bool BridgeConnected,
    bool BridgeAuthorized,
    string? Error);
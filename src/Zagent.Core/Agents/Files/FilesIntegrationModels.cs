namespace Zagent.Core.Agents.Files;

public sealed record FilesIntegrationOptions(
    string PythonExecutable,
    string EngineRoot,
    string DataRoot,
    string ConfigRoot,
    string RuntimeRoot,
    string LogRoot,
    string BackupRoot,
    string UpdateStateRoot,
    string BindHost,
    int Port,
    string DefaultProfileName,
    string DefaultProfileRoot,
    string DefaultProfileMode = "read-write",
    string DeviceId = "",
    string DeviceName = "");

public sealed record FilesHealthSnapshot(
    bool Ready,
    string? ServerName,
    string? ServerVersion,
    string? ProtocolVersion,
    string? Error);
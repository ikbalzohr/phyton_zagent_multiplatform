namespace Zagent.Shared.Paths;

public sealed record ZagentPathLayout(
    string InstallRoot,
    string FilesDefaultProfile,
    string DataRoot,
    string ConfigRoot,
    string LogsRoot,
    string RuntimeRoot,
    string StateRoot,
    string BackupRoot);

namespace Zagent.Shared.Configuration;

public sealed record ZagentMachineConfiguration(
    string SchemaVersion,
    string InstallRoot,
    string FilesDefaultProfile,
    string DataRoot,
    string BindHost,
    int CorePort,
    int TunnelPort,
    int TunnelHealthPort,
    int FilesPort,
    int WebPort,
    int ArcMapPort,
    int DevelopmentPortStart,
    int DevelopmentPortEnd,
    string InstallationRole = "Master")
{
    public const string CurrentSchemaVersion = "1.0";
}

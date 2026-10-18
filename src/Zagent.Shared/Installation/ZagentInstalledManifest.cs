namespace Zagent.Shared.Installation;

public sealed record InstalledComponent(
    string Id,
    string Version,
    string RelativePath,
    string? SourceFingerprint = null);

public sealed record ZagentInstalledManifest(
    string SchemaVersion,
    string Product,
    string ProductVersion,
    string InstallRoot,
    string DataRoot,
    string FilesDefaultProfile,
    DateTimeOffset InstalledAtUtc,
    IReadOnlyList<InstalledComponent> Components)
{
    public const string CurrentSchemaVersion = "1.0";
}

using System.Text.Json.Serialization;

namespace Zagent.Setup;

public sealed record PayloadFileEntry(
    string Path,
    long Size,
    string Sha256);

public sealed record PayloadRuntimeInfo(
    string Dotnet,
    string FilesPython,
    string TunnelPython,
    string ArcmapPython,
    string Node,
    string Playwright,
    IReadOnlyList<string> Browsers);

public sealed record PayloadManifest(
    [property: JsonPropertyName("schema_version")]
    string SchemaVersion,
    [property: JsonPropertyName("product")]
    string Product,
    [property: JsonPropertyName("core_version")]
    string CoreVersion,
    [property: JsonPropertyName("platform")]
    string Platform,
    [property: JsonPropertyName("install_root_policy")]
    string InstallRootPolicy,
    [property: JsonPropertyName("default_data_root")]
    string DefaultDataRoot,
    [property: JsonPropertyName("default_files_profile")]
    string DefaultFilesProfile,
    [property: JsonPropertyName("file_count")]
    int FileCount,
    [property: JsonPropertyName("total_bytes")]
    long TotalBytes,
    [property: JsonPropertyName("generated_at_utc")]
    string GeneratedAtUtc,
    [property: JsonPropertyName("runtime")]
    PayloadRuntimeInfo Runtime,
    [property: JsonPropertyName("files")]
    IReadOnlyList<PayloadFileEntry> Files)
{
    [JsonPropertyName("product_line")]
    public string? ProductLine { get; init; }

    [JsonPropertyName("suite_version")]
    public string? SuiteVersion { get; init; }
}

public enum SetupMode
{
    Install,
    Repair,
    Uninstall,
    Verify
}

public sealed record SetupRequest(
    SetupMode Mode,
    string TargetRoot,
    string? SourceRoot = null,
    string? DataRoot = null,
    string? FilesProfile = null,
    string? ProductVersion = null,
    bool KeepData = true);

public sealed record SetupProgress(
    int Percent,
    string Stage,
    string Message);

public sealed record SetupResult(
    bool Success,
    SetupMode Mode,
    string TargetRoot,
    int FilesChanged,
    int FilesVerified,
    string Message,
    string? BackupRoot = null);

public interface IWindowsInstallationIntegration
{
    void Register(
        string targetRoot,
        string productVersion);

    void Unregister(
        string targetRoot);
}

public interface IInstallInitializer
{
    Task InitializeAsync(
        string targetRoot,
        string dataRoot,
        string filesProfile,
        string productVersion,
        CancellationToken cancellationToken);
}
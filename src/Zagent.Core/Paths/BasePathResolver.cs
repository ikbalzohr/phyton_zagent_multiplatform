using Zagent.Shared.Paths;

namespace Zagent.Core.Paths;

public sealed class BasePathResolver : IBasePathResolver
{
    public ZagentPathLayout Resolve(
        string installRoot,
        string? filesDefaultProfile = null,
        string? dataRoot = null)
    {
        var normalizedInstallRoot = NormalizeRoot(installRoot);

        var normalizedProfile = string.IsNullOrWhiteSpace(filesDefaultProfile)
            ? Path.Combine(normalizedInstallRoot, "workspace")
            : NormalizeRoot(filesDefaultProfile);

        var normalizedDataRoot = string.IsNullOrWhiteSpace(dataRoot)
            ? Path.Combine(normalizedInstallRoot, "data")
            : NormalizeRoot(dataRoot);

        var layout = new ZagentPathLayout(
            InstallRoot: normalizedInstallRoot,
            FilesDefaultProfile: normalizedProfile,
            DataRoot: normalizedDataRoot,
            ConfigRoot: Path.Combine(normalizedDataRoot, "config"),
            LogsRoot: Path.Combine(normalizedDataRoot, "logs"),
            RuntimeRoot: Path.Combine(normalizedDataRoot, "runtime"),
            StateRoot: Path.Combine(normalizedDataRoot, "state"),
            BackupRoot: Path.Combine(normalizedDataRoot, "backups"));

        Validate(layout);
        return layout;
    }

    public static void Validate(ZagentPathLayout layout)
    {
        ArgumentNullException.ThrowIfNull(layout);

        _ = NormalizeRoot(layout.InstallRoot);
        _ = NormalizeRoot(layout.FilesDefaultProfile);
        _ = NormalizeRoot(layout.DataRoot);

        if (!IsDescendantOfOrEqual(layout.ConfigRoot, layout.DataRoot) ||
            !IsDescendantOfOrEqual(layout.LogsRoot, layout.DataRoot) ||
            !IsDescendantOfOrEqual(layout.RuntimeRoot, layout.DataRoot) ||
            !IsDescendantOfOrEqual(layout.StateRoot, layout.DataRoot) ||
            !IsDescendantOfOrEqual(layout.BackupRoot, layout.DataRoot))
        {
            throw new InvalidOperationException(
                "Zagent mutable subdirectories must remain inside DataRoot.");
        }
    }

    private static string NormalizeRoot(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
    }

    private static bool IsDescendantOfOrEqual(string child, string parent)
    {
        var normalizedChild = NormalizeRoot(child);
        var normalizedParent = NormalizeRoot(parent);

        if (string.Equals(
                normalizedChild,
                normalizedParent,
                StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return (
            normalizedChild + Path.DirectorySeparatorChar
        ).StartsWith(
            normalizedParent + Path.DirectorySeparatorChar,
            StringComparison.OrdinalIgnoreCase);
    }
}

namespace Zagent.Shared.Installation;

public static class InstallTargetResolver
{
    public const string ProductFolderName = "Zagent";

    public static string ResolveFromBaseFolder(
        string baseFolder,
        string installationRole = "Master")
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(
            baseFolder);

        var fullBase = Path.GetFullPath(
            baseFolder.Trim());

        if (string.Equals(
                Path.GetFileName(
                    Path.TrimEndingDirectorySeparator(
                        fullBase)),
                ProductFolderName,
                StringComparison.OrdinalIgnoreCase) ||
            string.Equals(Path.GetFileName(Path.TrimEndingDirectorySeparator(fullBase)),
                ZagentInstallationProfile.FolderName(installationRole),
                StringComparison.OrdinalIgnoreCase))
        {
            return fullBase;
        }

        return Path.Combine(
            fullBase,
            ZagentInstallationProfile.FolderName(installationRole));
    }
}

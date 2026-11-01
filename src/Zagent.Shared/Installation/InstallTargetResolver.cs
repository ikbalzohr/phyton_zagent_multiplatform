namespace Zagent.Shared.Installation;

public static class InstallTargetResolver
{
    public const string ProductFolderName = "Zagent";

    public static string ResolveFromBaseFolder(string baseFolder)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(baseFolder);
        var fullBase = Path.GetFullPath(baseFolder.Trim());
        if (string.Equals(
                Path.GetFileName(Path.TrimEndingDirectorySeparator(fullBase)),
                ProductFolderName, StringComparison.OrdinalIgnoreCase) ||
            File.Exists(Path.Combine(fullBase, "payload-manifest.json")) ||
            File.Exists(Path.Combine(fullBase, "Zagent.Core.exe")))
        {
            return fullBase;
        }
        return Path.Combine(fullBase, ProductFolderName);
    }
}

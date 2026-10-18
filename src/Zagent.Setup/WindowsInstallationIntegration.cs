using Microsoft.Win32;
using System.Reflection;
using Zagent.Shared.Installation;

namespace Zagent.Setup;

public sealed class WindowsInstallationIntegration : IWindowsInstallationIntegration
{
    private static string UninstallKeyFor(string role) =>
        @"Software\Microsoft\Windows\CurrentVersion\Uninstall\Zagent-" +
        ZagentInstallationProfile.Normalize(role);

    public void Register(
        string targetRoot,
        string productVersion)
    {
        var root = Path.GetFullPath(targetRoot);
        var role = ZagentInstallationProfile.InferRole(root);
        var displayName = ZagentInstallationProfile.DisplayName(role);
        var manager = Path.Combine(root, "Zagent.Core.exe");
        var setup = Path.Combine(root, "Zagent.Setup.exe");

        if (!File.Exists(manager) || !File.Exists(setup))
        {
            throw new InvalidOperationException(
                "Installed Core/Setup executable is missing.");
        }

        var uninstallCache = Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "Zagent",
            "Uninstall",
            role);

        Directory.CreateDirectory(uninstallCache);

        var cachedSetup = Path.Combine(
            uninstallCache,
            "Zagent.Setup.exe");

        File.Copy(
            setup,
            cachedSetup,
            overwrite: true);

        var uninstallCommand =
            Quote(cachedSetup) +
            " uninstall --target " +
            Quote(root) +
            " --keep-data true";

        using var key = Registry.CurrentUser.CreateSubKey(
            UninstallKeyFor(role),
            writable: true) ??
            throw new InvalidOperationException(
                "Could not create Zagent Installed Apps registry entry.");

        key.SetValue("DisplayName", displayName, RegistryValueKind.String);
        key.SetValue("DisplayVersion", productVersion, RegistryValueKind.String);
        key.SetValue("Publisher", "Zagent", RegistryValueKind.String);
        key.SetValue("InstallLocation", root, RegistryValueKind.String);
        key.SetValue("DisplayIcon", manager, RegistryValueKind.String);
        key.SetValue("UninstallString", uninstallCommand, RegistryValueKind.String);
        key.SetValue("QuietUninstallString", uninstallCommand, RegistryValueKind.String);
        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
        key.SetValue("NoRepair", 0, RegistryValueKind.DWord);

        RemoveMatchingLegacyRegistration(root);
        CreateShortcuts(root, manager, role);
    }

    public void Unregister(
        string targetRoot)
    {
        var root = Path.GetFullPath(targetRoot);
        var role = ZagentInstallationProfile.InferRole(root);

        try
        {
            Registry.CurrentUser.DeleteSubKeyTree(
                UninstallKeyFor(role),
                throwOnMissingSubKey: false);
        }
        catch
        {
        }

        RemoveMatchingLegacyRegistration(root);
        foreach (var shortcut in ShortcutPaths(role))
        {
            try
            {
                if (File.Exists(shortcut))
                {
                    File.Delete(shortcut);
                }
            }
            catch
            {
            }
        }

        try
        {
            var startMenuFolder = Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.Programs),
                ZagentInstallationProfile.DisplayName(role));

            if (Directory.Exists(startMenuFolder) &&
                !Directory.EnumerateFileSystemEntries(startMenuFolder).Any())
            {
                Directory.Delete(startMenuFolder);
            }
        }
        catch
        {
        }

        ArcMapAddInIntegration.Uninstall(root);
        ScheduleUninstallCacheCleanup(root);
    }

    private static void RemoveMatchingLegacyRegistration(string root)
    {
        const string legacyKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\Zagent";
        using var existing = Registry.CurrentUser.OpenSubKey(legacyKey);
        var legacyRoot = existing?.GetValue("InstallLocation") as string;
        if (string.IsNullOrWhiteSpace(legacyRoot) ||
            !string.Equals(Path.GetFullPath(legacyRoot), Path.GetFullPath(root),
                StringComparison.OrdinalIgnoreCase))
            return;
        existing?.Close();
        Registry.CurrentUser.DeleteSubKeyTree(legacyKey, throwOnMissingSubKey: false);
    }

    private static void CreateShortcuts(
        string root,
        string manager,
        string role)
    {
        var displayName = ZagentInstallationProfile.DisplayName(role);
        var startMenuFolder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Programs),
            displayName);
        Directory.CreateDirectory(startMenuFolder);
        var linkName = displayName + " Manager.lnk";
        CreateShortcut(Path.Combine(startMenuFolder, linkName), manager, root,
            displayName + " Manager");
        var desktop = Environment.GetFolderPath(
            Environment.SpecialFolder.DesktopDirectory);
        if (!string.IsNullOrWhiteSpace(desktop))
            CreateShortcut(Path.Combine(desktop, linkName), manager, root,
                displayName + " Manager");
    }

    private static IEnumerable<string> ShortcutPaths(string role)
    {
        var name = ZagentInstallationProfile.DisplayName(role);
        var linkName = name + " Manager.lnk";
        yield return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Programs),
            name, linkName);
        var desktop = Environment.GetFolderPath(
            Environment.SpecialFolder.DesktopDirectory);
        if (!string.IsNullOrWhiteSpace(desktop))
            yield return Path.Combine(desktop, linkName);
    }

    private static void CreateShortcut(
        string shortcutPath,
        string targetPath,
        string workingDirectory,
        string description)
    {
        var shellType = Type.GetTypeFromProgID("WScript.Shell") ??
            throw new PlatformNotSupportedException(
                "Windows Script Host shortcut API is unavailable.");

        object? shell = null;
        object? shortcut = null;

        try
        {
            shell = Activator.CreateInstance(shellType) ??
                throw new InvalidOperationException(
                    "Could not create WScript.Shell.");

            shortcut = shellType.InvokeMember(
                "CreateShortcut",
                BindingFlags.InvokeMethod,
                binder: null,
                shell,
                [shortcutPath]) ??
                throw new InvalidOperationException(
                    "Could not create shortcut object.");

            var type = shortcut.GetType();

            type.InvokeMember(
                "TargetPath",
                BindingFlags.SetProperty,
                null,
                shortcut,
                [targetPath]);

            type.InvokeMember(
                "Arguments",
                BindingFlags.SetProperty,
                null,
                shortcut,
                ["--dashboard --root " + Quote(workingDirectory)]);

            type.InvokeMember(
                "WorkingDirectory",
                BindingFlags.SetProperty,
                null,
                shortcut,
                [workingDirectory]);

            type.InvokeMember(
                "Description",
                BindingFlags.SetProperty,
                null,
                shortcut,
                [description]);

            type.InvokeMember(
                "IconLocation",
                BindingFlags.SetProperty,
                null,
                shortcut,
                [targetPath + ",0"]);

            type.InvokeMember(
                "Save",
                BindingFlags.InvokeMethod,
                null,
                shortcut,
                null);
        }
        finally
        {
            if (shortcut is not null &&
                System.Runtime.InteropServices.Marshal.IsComObject(shortcut))
            {
                System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shortcut);
            }

            if (shell is not null &&
                System.Runtime.InteropServices.Marshal.IsComObject(shell))
            {
                System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
            }
        }
    }

    private static void ScheduleUninstallCacheCleanup(
        string targetRoot)
    {
        var processPath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(processPath))
        {
            return;
        }

        var cacheRoot = Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "Zagent",
            "Uninstall",
            ZagentInstallationProfile.InferRole(targetRoot));

        if (!Path.GetFullPath(processPath).StartsWith(
                Path.GetFullPath(cacheRoot) +
                Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        try
        {
            var command =
                "/d /c ping 127.0.0.1 -n 3 >nul & " +
                "del /f /q " + Quote(processPath) + " & " +
                "rmdir /s /q " + Quote(cacheRoot);

            System.Diagnostics.Process.Start(
                new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = command,
                    CreateNoWindow = true,
                    UseShellExecute = false
                });
        }
        catch
        {
        }
    }

    private static string Quote(string value) =>
        "\"" + value.Replace("\"", "\\\"") + "\"";
}
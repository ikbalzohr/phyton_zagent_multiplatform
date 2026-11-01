using Microsoft.Win32;
using System.Reflection;
using Zagent.Shared.Installation;

namespace Zagent.Setup;

public sealed class WindowsInstallationIntegration : IWindowsInstallationIntegration
{
    private static string UninstallKeyFor(string root) =>
        @"Software\Microsoft\Windows\CurrentVersion\Uninstall\Zagent-" +
        ZagentInstanceScope.Key(root);

    public void Register(
        string targetRoot,
        string productVersion,
        string dataRoot)
    {
        var root = Path.GetFullPath(targetRoot);
        var key = ZagentInstanceScope.Key(root);
        const string displayName = "Zagent";
        var core = Path.Combine(root, "Zagent.Core.exe");
        var launcher = Path.Combine(root, "Zagent.Launcher.exe");
        var setup = Path.Combine(root, "Zagent.Setup.exe");

        if (!File.Exists(core) || !File.Exists(launcher) || !File.Exists(setup))
        {
            throw new InvalidOperationException(
                "Installed Core/Launcher/Setup executable is missing.");
        }

        var uninstallCache = Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "Zagent",
            "Uninstall",
            key);

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

        using var registration = Registry.CurrentUser.CreateSubKey(
            UninstallKeyFor(root),
            writable: true) ??
            throw new InvalidOperationException(
                "Could not create Zagent Installed Apps registry entry.");

        registration.SetValue("DisplayName", displayName, RegistryValueKind.String);
        registration.SetValue("DisplayVersion", productVersion, RegistryValueKind.String);
        registration.SetValue("Publisher", "Zagent", RegistryValueKind.String);
        registration.SetValue("InstallLocation", root, RegistryValueKind.String);
        registration.SetValue("DataRoot", Path.GetFullPath(dataRoot), RegistryValueKind.String);
        registration.SetValue("DisplayIcon", launcher, RegistryValueKind.String);
        registration.SetValue("UninstallString", uninstallCommand, RegistryValueKind.String);
        registration.SetValue("QuietUninstallString", uninstallCommand, RegistryValueKind.String);
        registration.SetValue("NoModify", 1, RegistryValueKind.DWord);
        registration.SetValue("NoRepair", 0, RegistryValueKind.DWord);

        RemoveMatchingLegacyRegistration(root);
        CreateShortcuts(root, launcher, key);
    }

    public void Unregister(
        string targetRoot)
    {
        var root = Path.GetFullPath(targetRoot);
        var key = ZagentInstanceScope.Key(root);

        try
        {
            Registry.CurrentUser.DeleteSubKeyTree(
                UninstallKeyFor(root),
                throwOnMissingSubKey: false);
        }
        catch
        {
        }

        RemoveMatchingLegacyRegistration(root);
        foreach (var shortcut in ShortcutPaths(key))
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
                "Zagent", key);

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
        const string parentPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall";
        using var parent = Registry.CurrentUser.OpenSubKey(parentPath);
        if (parent is null) return;
        var current = UninstallKeyFor(root);
        foreach (var name in parent.GetSubKeyNames())
        {
            if (!name.StartsWith("Zagent", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(parentPath + @"\" + name, current, StringComparison.OrdinalIgnoreCase))
                continue;
            string? previousLocation;
            using (var existing = parent.OpenSubKey(name))
                previousLocation = existing?.GetValue("InstallLocation") as string;
            if (string.IsNullOrWhiteSpace(previousLocation)) continue;
            try
            {
                if (!string.Equals(Path.GetFullPath(previousLocation), Path.GetFullPath(root),
                    StringComparison.OrdinalIgnoreCase)) continue;
            }
            catch (Exception ex) when (ex is ArgumentException or IOException or NotSupportedException) { continue; }
            Registry.CurrentUser.DeleteSubKeyTree(parentPath + @"\" + name,
                throwOnMissingSubKey: false);
        }
    }

    private static void CreateShortcuts(string root, string manager, string key)
    {
        var startMenuFolder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Programs),
            "Zagent", key);
        Directory.CreateDirectory(startMenuFolder);
        CreateShortcut(Path.Combine(startMenuFolder, "Zagent Manager.lnk"),
            manager, root, "Zagent Manager");
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (!string.IsNullOrWhiteSpace(desktop))
            CreateShortcut(Path.Combine(desktop, "Zagent Manager (" + key + ").lnk"),
                manager, root, "Zagent Manager");
    }

    private static IEnumerable<string> ShortcutPaths(string key)
    {
        yield return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Programs),
            "Zagent", key, "Zagent Manager.lnk");
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (!string.IsNullOrWhiteSpace(desktop))
            yield return Path.Combine(desktop, "Zagent Manager (" + key + ").lnk");
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
                [""]);

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
            ZagentInstanceScope.Key(targetRoot));

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
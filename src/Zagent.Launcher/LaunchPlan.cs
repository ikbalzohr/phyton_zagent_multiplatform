using System.Diagnostics;
using System.Text.Json;
using Microsoft.Win32;
using Zagent.Shared.Installation;

namespace Zagent.Launcher;

/// <summary>
/// The launcher belongs to this install root. No sibling Zagent installations,
/// global *Zagent* scans, or ambient plugin settings may select its data.
/// </summary>
public static class LaunchPlan
{
    public static bool IsInstalledProduct(string root) =>
        File.Exists(Path.Combine(root, "payload-manifest.json")) &&
        File.Exists(Path.Combine(root, "Zagent.Core.exe"));

    public static bool IsSourceCheckout(string root) =>
        File.Exists(Path.Combine(root, "component-manifest.json")) &&
        File.Exists(Path.Combine(root, "src", "Zagent.Core", "Zagent.Core.csproj"));

    public static string DiscoverDataRoot(string installRoot, string? explicitDataRoot = null,
        Func<string, string?>? registeredDataRoot = null)
    {
        var install = Path.TrimEndingDirectorySeparator(Path.GetFullPath(installRoot));
        if (!IsInstalledProduct(install) && !IsSourceCheckout(install))
            throw new InvalidOperationException("INSTALL_ROOT_NOT_FOUND");

        // Setup records a per-install DataRoot in its HKCU uninstall entry.
        // The entry is merely a locator: both machine config and installed
        // manifest must independently bind the same root and data directory.
        var selected = !string.IsNullOrWhiteSpace(explicitDataRoot)
            ? explicitDataRoot
            : (IsInstalledProduct(install)
                ? (registeredDataRoot ?? ReadRegisteredDataRoot)(install)
                : null);
        var data = Path.TrimEndingDirectorySeparator(Path.GetFullPath(
            string.IsNullOrWhiteSpace(selected)
                ? Path.Combine(install, "data") : selected));

        var config = Path.Combine(data, "config");
        var machinePath = Path.Combine(config, "zagent.machine.json");
        var dashboard = Path.Combine(config, "dashboard.json");
        var secrets = Path.Combine(config, "internal-secrets.dpapi.json");
        if (!File.Exists(machinePath) || !File.Exists(dashboard) || !File.Exists(secrets))
            throw new InvalidOperationException("ENROLLMENT_SELECTION_REQUIRED");

        VerifyBinding(machinePath, install, data);
        if (IsInstalledProduct(install))
        {
            var installedManifest = Path.Combine(config, "installed-manifest.json");
            if (!File.Exists(installedManifest))
                throw new InvalidOperationException("ENROLLMENT_SELECTION_REQUIRED");
            VerifyBinding(installedManifest, install, data);
        }
        return data;
    }

    private static string? ReadRegisteredDataRoot(string installRoot)
    {
        using var key = Registry.CurrentUser.OpenSubKey(
            @"Software\Microsoft\Windows\CurrentVersion\Uninstall\Zagent-" +
            ZagentInstanceScope.Key(installRoot));
        if (key is null) return null;
        var recordedInstall = key.GetValue("InstallLocation") as string;
        if (string.IsNullOrWhiteSpace(recordedInstall) ||
            !string.Equals(Path.TrimEndingDirectorySeparator(Path.GetFullPath(recordedInstall)),
                installRoot, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("ENROLLMENT_INSTALL_MISMATCH");
        return key.GetValue("DataRoot") as string;
    }

    private static void VerifyBinding(string file, string installRoot, string dataRoot)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllBytes(file));
            var root = document.RootElement;
            var installed = ReadString(root, "InstallRoot");
            var data = ReadString(root, "DataRoot");
            if (installed is null || data is null ||
                !string.Equals(Path.TrimEndingDirectorySeparator(Path.GetFullPath(installed)),
                    installRoot, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(Path.TrimEndingDirectorySeparator(Path.GetFullPath(data)),
                    dataRoot, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("ENROLLMENT_INSTALL_MISMATCH");
        }
        catch (Exception ex) when (ex is JsonException or IOException or ArgumentException or NotSupportedException)
        {
            throw new InvalidOperationException("ENROLLMENT_INSTALL_MISMATCH");
        }
    }

    private static string? ReadString(JsonElement root, string key)
    {
        if (root.ValueKind != JsonValueKind.Object) return null;
        foreach (var property in root.EnumerateObject())
            if (string.Equals(property.Name, key, StringComparison.OrdinalIgnoreCase))
                return property.Value.ValueKind == JsonValueKind.String
                    ? property.Value.GetString() : null;
        return null;
    }

    public static ProcessStartInfo Create(string installRoot, string dataRoot)
    {
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(installRoot));
        var data = Path.TrimEndingDirectorySeparator(Path.GetFullPath(dataRoot));
        var installed = IsInstalledProduct(root);
        if (!installed && !IsSourceCheckout(root))
            throw new InvalidOperationException("INSTALL_ROOT_NOT_FOUND");

        var core = installed
            ? Path.Combine(root, "Zagent.Core.exe")
            : Path.Combine(root, "src", "Zagent.Core", "bin", "Debug", "net10.0", "Zagent.Core.exe");

        var start = new ProcessStartInfo(core)
        {
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        foreach (var arg in new[] { "--dashboard", "--root", root, "--data-root", data,
                    "--dashboard-config", Path.Combine(data, "config", "dashboard.json") })
            start.ArgumentList.Add(arg);

        // Strip inherited privileges/production settings from unrelated agent products.
        foreach (var key in start.Environment.Keys.ToArray())
            if (key.StartsWith("ZAGENT_PLUGIN_", StringComparison.OrdinalIgnoreCase) ||
                key.StartsWith("ZAGENT_INTERNAL_", StringComparison.OrdinalIgnoreCase) ||
                key.StartsWith("CONTROL_PLANE_", StringComparison.OrdinalIgnoreCase) ||
                key is "ZAGENT_MANAGER_PIPE" or "ZAGENT_SUPERVISOR_LEASE_NAME" or
                    "ZAGENT_DEVICE_BINDING" or "ZAGENT_DEVICE_ID" or "ZAGENT_INSTALLATION_ID" or
                    "ZAGENT_ENVIRONMENT")
                start.Environment.Remove(key);
        start.Environment["ZAGENT_ENVIRONMENT"] = "Production";

        var binaries = new (string Variable, string Relative, string Explicit)[]
        {
            ("ZAGENT_FILES_PYTHON", @"agents\files\runtime\python\python.exe",
                "ZAGENT_LAUNCHER_FILES_PYTHON"),
            ("ZAGENT_TUNNEL_PYTHON", @"agents\tunnel\runtime\python\python.exe",
                "ZAGENT_LAUNCHER_TUNNEL_PYTHON"),
            ("ZAGENT_WEB_NODE", @"agents\web\runtime\node\node.exe",
                "ZAGENT_LAUNCHER_WEB_NODE"),
            ("ZAGENT_ARCMAP_PYTHON", @"agents\arcmap\runtime\python\python.exe",
                "ZAGENT_LAUNCHER_ARCMAP_PYTHON")
        };
        foreach (var binary in binaries)
        {
            var selected = installed ? Path.Combine(root, binary.Relative) :
                Environment.GetEnvironmentVariable(binary.Explicit);
            if (string.IsNullOrWhiteSpace(selected))
                throw new InvalidOperationException("REQUIRED_RUNTIME_MISSING");
            start.Environment[binary.Variable] = Path.GetFullPath(selected);
        }

        // A published install is self-contained; checkout use requires a
        // deliberately selected SDK/runtime, not a sibling appBridge path.
        if (installed)
            start.Environment.Remove("DOTNET_ROOT");
        else
        {
            var explicitDotnet = Environment.GetEnvironmentVariable("ZAGENT_LAUNCHER_DOTNET_ROOT");
            if (string.IsNullOrWhiteSpace(explicitDotnet))
                throw new InvalidOperationException("REQUIRED_RUNTIME_MISSING");
            start.Environment["DOTNET_ROOT"] = Path.GetFullPath(explicitDotnet);
        }
        return start;
    }
}

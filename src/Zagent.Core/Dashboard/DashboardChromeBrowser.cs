using System.Diagnostics;
using Microsoft.Win32;

namespace Zagent.Core.Dashboard;

/// <summary>Open the owner-local Dashboard in Chrome, never a remote MCP surface.</summary>
public static class DashboardChromeBrowser
{
    public static ProcessStartInfo BuildStartInfo(string chromeExecutable, Uri origin)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(chromeExecutable);
        if (!string.Equals(Path.GetFileName(chromeExecutable), "chrome.exe", StringComparison.OrdinalIgnoreCase) ||
            !Path.IsPathFullyQualified(chromeExecutable) || !File.Exists(chromeExecutable))
            throw new FileNotFoundException("Chrome executable not found.", chromeExecutable);
        if (origin.Scheme != Uri.UriSchemeHttps || !origin.IsLoopback ||
            origin.AbsolutePath != "/" || origin.Query.Length != 0 || origin.Fragment.Length != 0)
            throw new ArgumentException("Dashboard browser requires the provisioned HTTPS loopback origin.");

        var start = new ProcessStartInfo(Path.GetFullPath(chromeExecutable))
        {
            UseShellExecute = false,
            CreateNoWindow = true
        };
        start.ArgumentList.Add("--new-tab");
        start.ArgumentList.Add(origin.AbsoluteUri);
        return start;
    }

    public static void Open(Uri origin)
    {
        var chrome = FindChromeExecutable() ?? throw new FileNotFoundException(
            "Google Chrome is not installed for this Windows owner.");
        using var process = Process.Start(BuildStartInfo(chrome, origin))
            ?? throw new InvalidOperationException("Could not open Chrome Dashboard tab.");
    }

    public static string? FindChromeExecutable()
    {
        if (!OperatingSystem.IsWindows()) return null;
        foreach (var hive in new[] { Microsoft.Win32.Registry.CurrentUser, Microsoft.Win32.Registry.LocalMachine })
        {
            using var key = hive.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe");
            var path = key?.GetValue(null) as string;
            if (IsChromePath(path)) return Path.GetFullPath(path!);
        }
        foreach (var root in new[] {
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData)
        })
        {
            if (string.IsNullOrWhiteSpace(root)) continue;
            var path = Path.Combine(root, "Google", "Chrome", "Application", "chrome.exe");
            if (IsChromePath(path)) return path;
        }
        return null;
    }

    private static bool IsChromePath(string? path) =>
        !string.IsNullOrWhiteSpace(path) && Path.IsPathFullyQualified(path) &&
        string.Equals(Path.GetFileName(path), "chrome.exe", StringComparison.OrdinalIgnoreCase) &&
        File.Exists(path);
}

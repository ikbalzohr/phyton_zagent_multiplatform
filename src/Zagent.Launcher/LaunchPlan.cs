namespace Zagent.Launcher;
public static class LaunchPlan
{
    public static System.Diagnostics.ProcessStartInfo Create(string install, string data, string local)
    {
        var start = new System.Diagnostics.ProcessStartInfo(Path.Combine(install, "src", "Zagent.Core", "bin", "Debug", "net10.0", "Zagent.Core.exe"))
        { WorkingDirectory = install, UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { "--dashboard", "--root", install, "--data-root", data, "--dashboard-config", Path.Combine(data, "config", "dashboard.json") }) start.ArgumentList.Add(arg);
        start.Environment["DOTNET_ROOT"] = Path.GetFullPath(Path.Combine(install, "..", "appBridge", "toolchain", "dotnet10"));
        start.Environment["ZAGENT_FILES_PYTHON"] = Path.Combine(local, "Zagent-Envs", "files", "Scripts", "python.exe");
        start.Environment["ZAGENT_TUNNEL_PYTHON"] = Path.Combine(local, "Zagent-Envs", "tunnel", "Scripts", "python.exe");
        return start;
    }
    // Same discovery locations as Start-OwnerCore.ps1. Never read enrollment contents.
    public static string DiscoverDataRoot(string installRoot, string localAppData)
    {
        var candidates = new List<string> { Path.Combine(installRoot, "dev", "data"), Path.Combine(installRoot, "data") };
        if (Directory.Exists(localAppData)) candidates.AddRange(Directory.EnumerateDirectories(localAppData, "*Zagent*"));
        var matches = candidates.Select(Path.GetFullPath).Distinct(StringComparer.OrdinalIgnoreCase)
            .Where(p => File.Exists(Path.Combine(p, "config", "dashboard.json")) &&
                        File.Exists(Path.Combine(p, "config", "internal-secrets.dpapi.json"))).ToArray();
        if (matches.Length != 1) throw new InvalidOperationException("ENROLLMENT_SELECTION_REQUIRED");
        return matches[0];
    }
}

using System.Text.Json;

namespace Zagent.Shared.Installation;

/// <summary>Local installation identity, distinct from the bound operator/device alias.</summary>
public static class ZagentInstallationProfile
{
    public const string Master = "Primary";
    public const string User = "Secondary";

    public static string Normalize(string? role) =>
        (role ?? "").Trim().ToLowerInvariant() switch
        {
            "" or "primary" or "master" => Master,
            "secondary" or "user" => User,
            _ => throw new ArgumentException("Installation slot must be Primary or Secondary.", nameof(role))
        };

    public static string FromAudience(string? audience) =>
        string.Equals(audience?.Trim(), "tryplugin", StringComparison.OrdinalIgnoreCase)
            ? User : Master;

    public static string DisplayName(string? role) => "Zagent " + Normalize(role);
    public static string FolderName(string? role) => "Zagent " + Normalize(role);
    public static string PipeName(string? role) => "Zagent.Manager." + Normalize(role) + ".v1";
    public static string SupervisorLeaseName(string? role) =>
        @"Local\Zagent." + Normalize(role) + ".Supervisor.v3";

    public static string InferRole(string installRoot)
    {
        var root = Path.GetFullPath(installRoot);
        var configPath = Path.Combine(root, "data", "config", "zagent.machine.json");
        if (File.Exists(configPath))
        {
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(configPath));
                if ((doc.RootElement.TryGetProperty("installation_role", out var value) ||
                     doc.RootElement.TryGetProperty("InstallationRole", out value)) &&
                    value.ValueKind == JsonValueKind.String)
                    return Normalize(value.GetString());
            }
            catch (JsonException) { }
        }
        var pluginPath = Path.Combine(root, "data", "config", "plugin-access.json");
        if (File.Exists(pluginPath))
        {
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(pluginPath));
                if (doc.RootElement.TryGetProperty("audience", out var value))
                    return FromAudience(value.GetString());
            }
            catch (JsonException) { }
        }
        return Path.GetFileName(Path.TrimEndingDirectorySeparator(root))
            .Equals(FolderName(User), StringComparison.OrdinalIgnoreCase) ? User : Master;
    }
}

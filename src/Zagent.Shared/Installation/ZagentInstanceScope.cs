using System.Security.Cryptography;
using System.Text;

namespace Zagent.Shared.Installation;

/// <summary>
/// Namespaces per-user Windows resources by the selected install directory.
/// This is a collision-avoidance key, not an operator, device, or authorization identity.
/// </summary>
public static class ZagentInstanceScope
{
    public static string Key(string installRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(installRoot);
        var canonical = Path.TrimEndingDirectorySeparator(Path.GetFullPath(installRoot))
            .ToUpperInvariant();
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(canonical));
        return Convert.ToHexString(digest)[..16];
    }

    public static string PipeName(string installRoot) =>
        "Zagent.Manager." + Key(installRoot) + ".v1";

    public static string SupervisorLeaseName(string installRoot) =>
        @"Local\Zagent." + Key(installRoot) + ".Supervisor.v3";
}

using System.Net;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Security.Principal;

namespace Zagent.Core.Dashboard;

/// <summary>Provisioned out of band under the Windows owner's ACL. Remote access is not implemented.</summary>
public sealed record DashboardOptions(string Url, string CertificateThumbprint, string WorkspaceId,
    string Administrator, string PasswordHash, string SecurityStamp, bool RemoteEnabled = false)
{
    public Uri Origin => new(Url, UriKind.Absolute);
    public void Validate()
    {
        if (!Uri.TryCreate(Url, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps ||
            !uri.IsLoopback || uri.AbsolutePath != "/" || uri.Query != "" || uri.Fragment != "" ||
            uri.UserInfo != "" || RemoteEnabled)
            throw new ArgumentException("Dashboard requires an exact HTTPS loopback origin; remote management is disabled.");
        // Dashboard authorization is the interactive Windows owner identity,
        // never a browser username/password. PasswordHash is legacy metadata.
        if (string.IsNullOrWhiteSpace(CertificateThumbprint) || string.IsNullOrWhiteSpace(WorkspaceId) ||
            string.IsNullOrWhiteSpace(Administrator) || string.IsNullOrWhiteSpace(SecurityStamp))
            throw new ArgumentException("Dashboard provisioning is incomplete.");
        if (!Regex.IsMatch(WorkspaceId, "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"))
            throw new ArgumentException("Invalid installation workspace identifier.");
    }
    public static DashboardOptions Load(string path)
    {
        var options = JsonSerializer.Deserialize<DashboardOptions>(File.ReadAllText(path),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
            ?? throw new InvalidDataException("Dashboard is not provisioned.");
        options.Validate(); return options;
    }
    public X509Certificate2 LoadCertificate()
    {
        using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
        store.Open(OpenFlags.ReadOnly);
        var certificates = store.Certificates.Find(X509FindType.FindByThumbprint, CertificateThumbprint.Trim(), validOnly: true);
        if (certificates.Count != 1 || !certificates[0].HasPrivateKey)
            throw new InvalidOperationException("Provision a valid CurrentUser dashboard TLS certificate with private key.");
        return certificates[0];
    }
    public static void ProvisionLocalOwner(string path, string url, string thumbprint, string workspace)
    {
        if (!OperatingSystem.IsWindows() || !Environment.UserInteractive)
            throw new InvalidOperationException("Enrollment requires the interactive Windows owner session.");
        using var identity = WindowsIdentity.GetCurrent();
        if (identity.IsSystem || identity.IsAnonymous || !identity.IsAuthenticated ||
            string.IsNullOrWhiteSpace(identity.User?.Value))
            throw new InvalidOperationException("Authenticated Windows owner identity is required.");
        if (File.Exists(path)) throw new InvalidOperationException(
            "Already enrolled. Do not replace another dashboard identity.");
        // Browser access is authenticated by DashboardOwnerAuthenticationHandler.
        // There is intentionally no dashboard username/password to enter or persist.
        var options = new DashboardOptions(url, thumbprint, workspace,
            identity.Name, "", Guid.NewGuid().ToString("N"));
        options.Validate();
        using var certificate = options.LoadCertificate();
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        JsonSerializer.Serialize(stream, options, new JsonSerializerOptions { WriteIndented = true });
        stream.Flush(true);
    }
}

public static partial class DashboardSecurity
{
    public static bool IsExpectedHost(string host, Uri origin) =>
        string.Equals(host, origin.Authority, StringComparison.OrdinalIgnoreCase);
    public static bool IsSameOrigin(string? supplied, Uri origin) =>
        !string.IsNullOrWhiteSpace(supplied) &&
        string.Equals(supplied, origin.GetLeftPart(UriPartial.Authority), StringComparison.OrdinalIgnoreCase);
    public static string Redact(string text) => SecretPattern().Replace(text, "$1[REDACTED]");
    [GeneratedRegex(@"(?i)((?:authorization\s*:\s*(?:bearer\s+)?|(?:api[_-]?key|token|password|secret|cookie)\s*[=:]\s*))[^\s,;]+")]
    private static partial Regex SecretPattern();
}

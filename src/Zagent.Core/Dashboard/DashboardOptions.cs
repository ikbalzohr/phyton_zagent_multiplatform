using System.Net;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Identity;

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
        if (string.IsNullOrWhiteSpace(CertificateThumbprint) || string.IsNullOrWhiteSpace(WorkspaceId) ||
            string.IsNullOrWhiteSpace(Administrator) || string.IsNullOrWhiteSpace(PasswordHash) ||
            string.IsNullOrWhiteSpace(SecurityStamp))
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
    public static void ProvisionInteractive(string path, string url, string thumbprint, string workspace, string account)
    {
        if (!OperatingSystem.IsWindows() || !Environment.UserInteractive || Console.IsInputRedirected)
            throw new InvalidOperationException("Enrollment requires the interactive Windows owner console.");
        if (File.Exists(path)) throw new InvalidOperationException("Already enrolled. Account recovery requires an explicit offline replacement and restart.");
        Console.Write("New dashboard password (minimum 14 characters): ");
        var password = ReadPassword();
        Console.Write("Confirm password: ");
        if (password != ReadPassword() || password.Length < 14 || password.Length > 256)
            throw new ArgumentException("Password confirmation or length is invalid.");
        var options = new DashboardOptions(url, thumbprint, workspace, account,
            new PasswordHasher<string>().HashPassword(account, password), Guid.NewGuid().ToString("N"));
        options.Validate();
        using var certificate = options.LoadCertificate();
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        // Installer must ACL the enclosing directory BEFORE enrollment; never replace an existing account.
        using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        JsonSerializer.Serialize(stream, options, new JsonSerializerOptions { WriteIndented = true });
        stream.Flush(true);
    }
    private static string ReadPassword()
    {
        var chars = new List<char>();
        for (;;) {
            var key = Console.ReadKey(intercept: true);
            if (key.Key == ConsoleKey.Enter) { Console.WriteLine(); return new string(chars.ToArray()); }
            if (key.Key == ConsoleKey.Backspace) { if (chars.Count > 0) chars.RemoveAt(chars.Count - 1); }
            else if (!char.IsControl(key.KeyChar) && chars.Count < 257) chars.Add(key.KeyChar);
        }
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

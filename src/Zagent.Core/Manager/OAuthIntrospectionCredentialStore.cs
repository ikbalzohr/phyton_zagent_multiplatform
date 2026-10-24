using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace Zagent.Core.Manager;

/// <summary>Separate, owner-local OAuth credential. Never uses ambient secrets or internal tokens.</summary>
public static class OAuthIntrospectionCredentialStore
{
    public const string FileName = "oauth-introspection.dpapi.json";
    public const string Issuer = "https://vmi3669591.contaboserver.net/realms/zagent";
    public const string ClientId = "zagent-resource-server";
    public const string EnvironmentName = "ZAGENT_OAUTH_INTROSPECTION_SECRET";
    public const int MaxFileBytes = 16384;
    private const string Error = "OAuth credentials are invalid or unavailable for this Windows owner.";
    private static readonly JsonDocumentOptions JsonOptions = new() { MaxDepth = 16 };

    /// <summary>Null means not provisioned; malformed configured state throws without disclosing values.</summary>
    public static string? LoadOptional(string dataRoot, string tunnelConfigRoot)
    {
        try
        {
            var configPath = Path.Combine(tunnelConfigRoot, "tunnel.json");
            if (!ExistsStrict(configPath)) return null;
            using var config = JsonDocument.Parse(ReadBounded(configPath, 1048576), JsonOptions);
            var root = config.RootElement;
            if (root.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
            RejectDuplicateKeys(root);
            if (!root.TryGetProperty("resource_server", out var resource)) return null;
            if (resource.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
            if (!resource.EnumerateObject().Any()) return null;
            RejectDuplicateKeys(resource);
            if (Text(resource, "issuer") != Issuer || Text(resource, "introspection_client_id") != ClientId ||
                Text(resource, "introspection_endpoint") != Issuer + "/protocol/openid-connect/token/introspect" ||
                Text(resource, "introspection_secret_env") != EnvironmentName) throw new InvalidDataException();
            var path = Path.Combine(dataRoot, "config", FileName);
            if (!ExistsStrict(path)) return null;
            ValidatePaths(dataRoot, path);
            using var envelope = JsonDocument.Parse(ReadBounded(path, MaxFileBytes), JsonOptions);
            var e = envelope.RootElement;
            Keys(e, "version", "scope", "protected_payload");
            if (e.GetProperty("version").GetInt32() != 1 || Text(e, "scope") != "CurrentUser") throw new InvalidDataException();
            var encrypted = Base64(Text(e, "protected_payload"));
            var clear = TunnelCredentialStore.Crypt(encrypted, protect: false);
            try
            {
                if (clear.Length > 2048) throw new InvalidDataException();
                using var payload = JsonDocument.Parse(clear, JsonOptions);
                var p = payload.RootElement;
                Keys(p, "issuer", "client_id", "secret");
                if (Text(p, "issuer") != Text(resource, "issuer") || Text(p, "client_id") != Text(resource, "introspection_client_id"))
                    throw new InvalidDataException();
                var secret = Text(p, "secret");
                if (!Hex(secret, 64)) throw new InvalidDataException();
                return secret;
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
        }
        catch (Exception ex) when (SafeFailure(ex)) { throw new InvalidDataException(Error); }
    }

    /// <summary>Trusted-operator import. Package contains RSA ciphertext only. Returns no credential.</summary>
    public static void Import(string dataRoot, byte[] packageUtf8, string certificateThumbprint)
    {
        byte[]? clear = null;
        byte[]? payload = null;
        try
        {
            if (!OperatingSystem.IsWindows() || packageUtf8.Length is < 2 or > MaxFileBytes ||
                certificateThumbprint.Length != 40 || !certificateThumbprint.All(Uri.IsHexDigit)) throw new InvalidDataException();
            using var package = JsonDocument.Parse(packageUtf8, JsonOptions);
            var p = package.RootElement;
            Keys(p, "version", "purpose", "issuer", "client_id", "cert_sha256", "ciphertext_algorithm", "ciphertext", "expires_at");
            var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            var expires = p.GetProperty("expires_at").GetInt64();
            if (p.GetProperty("version").GetInt32() != 1 || Text(p, "purpose") != "zagent-oauth-introspection" ||
                Text(p, "issuer") != Issuer || Text(p, "client_id") != ClientId ||
                Text(p, "ciphertext_algorithm") != "RSA-OAEP-256" || !Hex(Text(p, "cert_sha256"), 64) ||
                expires <= now || expires - now > 86400) throw new InvalidDataException();
            var ciphertext = Base64(Text(p, "ciphertext"));
            if (ciphertext.Length is < 256 or > 1024) throw new InvalidDataException();
            var target = Path.Combine(Path.GetFullPath(dataRoot), "config", FileName);
            ValidateDirectories(dataRoot);
            // Reject any preexisting object, including dangling links; never overwrite or repair it.
            if (ExistsStrict(target)) throw new InvalidDataException();
            using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
            store.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
            var matches = store.Certificates.Find(X509FindType.FindByThumbprint, certificateThumbprint, validOnly: false);
            try
            {
                if (matches.Count != 1) throw new InvalidDataException();
                var cert = matches[0];
                var utcNow = DateTime.UtcNow;
                if (!cert.HasPrivateKey || cert.NotBefore.ToUniversalTime() > utcNow || cert.NotAfter.ToUniversalTime() <= utcNow ||
                    Convert.ToHexString(SHA256.HashData(cert.RawData)).ToLowerInvariant() != Text(p, "cert_sha256")) throw new InvalidDataException();
                using RSA? rsa = cert.GetRSAPrivateKey();
                // Only verifiable non-exportable CurrentUser CNG keys are accepted; no CSP fallback/export attempt.
                if (rsa is not RSACng cng || cng.Key.IsMachineKey || cng.Key.ExportPolicy != CngExportPolicies.None ||
                    rsa.KeySize is < 2048 or > 8192 || ciphertext.Length != rsa.KeySize / 8) throw new InvalidDataException();
                clear = rsa.Decrypt(ciphertext, RSAEncryptionPadding.OaepSHA256);
                if (clear.Length != 64 || !clear.All(b => b is >= (byte)'0' and <= (byte)'9' or >= (byte)'a' and <= (byte)'f')) throw new InvalidDataException();
                payload = JsonSerializer.SerializeToUtf8Bytes(new { issuer = Issuer, client_id = ClientId, secret = Encoding.ASCII.GetString(clear) });
                var encrypted = TunnelCredentialStore.Crypt(payload, protect: true);
                var envelope = JsonSerializer.SerializeToUtf8Bytes(new { version = 1, scope = "CurrentUser", protected_payload = Convert.ToBase64String(encrypted) });
                var owner = WindowsIdentity.GetCurrent().User ?? throw new InvalidDataException();
                var acl = new FileSecurity(); acl.SetOwner(owner); acl.SetAccessRuleProtection(true, false);
                acl.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl, AccessControlType.Allow));
                // Create atomically with the final protected DACL, not permissive create-then-chmod.
                using (var stream = new FileInfo(target).Create(FileMode.CreateNew, FileSystemRights.FullControl, FileShare.None, 4096, FileOptions.WriteThrough, acl))
                { stream.Write(envelope); stream.Flush(flushToDisk: true); }
                ValidatePaths(dataRoot, target);
                using var readback = JsonDocument.Parse(ReadBounded(target, MaxFileBytes), JsonOptions);
                Keys(readback.RootElement, "version", "scope", "protected_payload");
                var verified = TunnelCredentialStore.Crypt(Base64(Text(readback.RootElement, "protected_payload")), protect: false);
                try { if (!CryptographicOperations.FixedTimeEquals(payload, verified)) throw new InvalidDataException(); }
                finally { CryptographicOperations.ZeroMemory(verified); }
                // Failed/partial state is retained for explicit owner recovery; never auto-delete/replace.
            }
            finally { foreach (var cert in matches) cert.Dispose(); }
        }
        catch (Exception ex) when (SafeFailure(ex)) { throw new InvalidDataException(Error); }
        finally
        {
            if (clear is not null) CryptographicOperations.ZeroMemory(clear);
            if (payload is not null) CryptographicOperations.ZeroMemory(payload);
            // Immutable managed JSON/string copies cannot be reliably zeroed, and never leave process memory.
        }
    }

    public static byte[] ReadPackage(string path)
    {
        try { return ReadBounded(path, MaxFileBytes); }
        catch (Exception ex) when (SafeFailure(ex)) { throw new InvalidDataException(Error); }
    }
    private static byte[] ReadBounded(string path, int maximum)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length is < 2 || stream.Length > maximum) throw new InvalidDataException();
        var bytes = new byte[(int)stream.Length]; stream.ReadExactly(bytes);
        if (stream.ReadByte() != -1) throw new InvalidDataException();
        return bytes;
    }
    private static bool ExistsStrict(string path)
    {
        try { _ = File.GetAttributes(path); return true; }
        catch (FileNotFoundException) { return false; }
        catch (DirectoryNotFoundException) { return false; }
    }
    private static void ValidateDirectories(string dataRoot)
    {
        InternalSecretStore.ValidatePrivatePath(dataRoot, directory: true);
        InternalSecretStore.ValidatePrivatePath(Path.Combine(dataRoot, "config"), directory: true);
    }
    private static void ValidatePaths(string dataRoot, string path)
    { ValidateDirectories(dataRoot); InternalSecretStore.ValidatePrivatePath(path, directory: false); }
    private static bool SafeFailure(Exception e) => e is IOException or UnauthorizedAccessException or System.Security.SecurityException or
        JsonException or InvalidOperationException or ArgumentException or FormatException or CryptographicException or NotSupportedException or OverflowException or KeyNotFoundException;
    private static bool Hex(string s, int length) => s.Length == length && s.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static string Text(JsonElement e, string key) => e.GetProperty(key).GetString() ?? throw new InvalidDataException();
    private static byte[] Base64(string s)
    {
        if (s.Length > MaxFileBytes) throw new InvalidDataException();
        var bytes = Convert.FromBase64String(s);
        if (bytes.Length == 0 || Convert.ToBase64String(bytes) != s) throw new InvalidDataException();
        return bytes;
    }
    private static void RejectDuplicateKeys(JsonElement e)
    {
        var keys = e.EnumerateObject().Select(p => p.Name).ToArray();
        if (keys.Distinct(StringComparer.Ordinal).Count() != keys.Length) throw new InvalidDataException();
    }
    private static void Keys(JsonElement e, params string[] expected)
    {
        if (e.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
        var keys = e.EnumerateObject().Select(p => p.Name).ToArray();
        if (keys.Length != expected.Length || !keys.Order(StringComparer.Ordinal).SequenceEqual(expected.Order(StringComparer.Ordinal))) throw new InvalidDataException();
    }
}

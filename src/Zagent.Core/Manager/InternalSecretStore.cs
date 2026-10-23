using System.Security.AccessControl;
using System.Security.Principal;
using System.Security.Cryptography;
using System.Text.Json;

namespace Zagent.Core.Manager;

/// <summary>Read-only provisioning contract. Enrollment belongs to the interactive Windows owner.</summary>
public static class InternalSecretStore
{
    public const string FileName = "internal-secrets.dpapi.json";

    public static (string Token, string ContextKey) Load(string dataRoot)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("Private credentials require Windows CurrentUser DPAPI.");
        var data = Path.GetFullPath(dataRoot);
        var config = Path.Combine(data, "config");
        var path = Path.Combine(config, FileName);
        ValidatePrivatePath(data, directory: true);
        ValidatePrivatePath(config, directory: true);
        ValidatePrivatePath(path, directory: false);
        try
        {
            using var envelope = JsonDocument.Parse(File.ReadAllBytes(path));
            var root = envelope.RootElement;
            RequireKeys(root, "version", "scope", "protected_payload");
            if (root.GetProperty("version").GetInt32() != 1 || root.GetProperty("scope").GetString() != "CurrentUser")
                throw new InvalidDataException();
            var encrypted = Convert.FromBase64String(root.GetProperty("protected_payload").GetString()!);
            var clear = TunnelCredentialStore.Crypt(encrypted, protect: false);
            try
            {
                using var payload = JsonDocument.Parse(clear);
                RequireKeys(payload.RootElement, "internal_token", "internal_context_key");
                var token = payload.RootElement.GetProperty("internal_token").GetString();
                var key = payload.RootElement.GetProperty("internal_context_key").GetString();
                if (!IsSecret(token) || !IsSecret(key) || token == key) throw new InvalidDataException();
                return (token!, key!);
            }
            finally { CryptographicOperations.ZeroMemory(clear); }
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException or InvalidDataException or ArgumentException)
        {
            // Never include decrypted JSON, ciphertext or parser values in diagnostics.
            throw new InvalidDataException("Private credentials are invalid or cannot be decrypted by this Windows owner.");
        }
    }

    private static bool IsSecret(string? value) => value is { Length: 64 } &&
        value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static void RequireKeys(JsonElement value, params string[] expected)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
        var keys = value.EnumerateObject().Select(p => p.Name).ToArray();
        if (keys.Length != expected.Length || !keys.Order(StringComparer.Ordinal).SequenceEqual(expected.Order(StringComparer.Ordinal)))
            throw new InvalidDataException();
    }

    public static void ValidatePrivatePath(string path, bool directory)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Owner ACL validation requires Windows.");
        var full = Path.GetFullPath(path);
        // Reject junction/symlink ancestors, including outside the private DataRoot.
        for (var current = full; current is not null; current = Path.GetDirectoryName(current))
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Private provisioning paths cannot traverse reparse points.");
        var owner = WindowsIdentity.GetCurrent().User ?? throw new InvalidOperationException("Windows owner SID is unavailable.");
        FileSystemSecurity acl = directory
            ? new DirectoryInfo(full).GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access)
            : new FileInfo(full).GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access);
        var rules = acl.GetAccessRules(includeExplicit: true, includeInherited: true, typeof(SecurityIdentifier))
            .Cast<FileSystemAccessRule>().ToArray();
        if (!owner.Equals(acl.GetOwner(typeof(SecurityIdentifier))) || !acl.AreAccessRulesProtected || rules.Length != 1 ||
            !owner.Equals(rules[0].IdentityReference) || rules[0].AccessControlType != AccessControlType.Allow ||
            rules[0].IsInherited || rules[0].FileSystemRights != FileSystemRights.FullControl ||
            rules[0].PropagationFlags != PropagationFlags.None ||
            rules[0].InheritanceFlags != (directory ? InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit : InheritanceFlags.None))
            throw new InvalidDataException("Private provisioning requires a protected owner-only FullControl ACL.");
    }
}

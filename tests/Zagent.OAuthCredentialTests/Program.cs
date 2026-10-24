using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using Zagent.Core.Manager;

// Windows-only behavioral harness. Synthetic fixture secret, never a deployment credential.
if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows owner required.");
var root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Zagent-OAuth-Tests-" + Guid.NewGuid().ToString("N"));
void PrivateDirectory(string path)
{
    Directory.CreateDirectory(path);
    var sid = WindowsIdentity.GetCurrent().User!;
    var acl = new DirectorySecurity(); acl.SetOwner(sid); acl.SetAccessRuleProtection(true, false);
    acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
    new DirectoryInfo(path).SetAccessControl(acl);
}
void Check(bool condition) { if (!condition) throw new Exception("OAuth credential assertion failed."); }
void Reject(Action action)
{
    try { action(); } catch (InvalidDataException e) { Check(e.InnerException is null); Check(!e.Message.Contains(new string('a', 64))); return; }
    throw new Exception("Unsafe OAuth input accepted.");
}
PrivateDirectory(root); PrivateDirectory(Path.Combine(root, "config"));
var tunnel = Path.Combine(root, "tunnel", "config"); Directory.CreateDirectory(tunnel);
try
{
    Check(OAuthIntrospectionCredentialStore.LoadOptional(root, tunnel) is null);
    var resource = new { issuer = OAuthIntrospectionCredentialStore.Issuer, introspection_endpoint = OAuthIntrospectionCredentialStore.Issuer + "/protocol/openid-connect/token/introspect", introspection_client_id = OAuthIntrospectionCredentialStore.ClientId, introspection_secret_env = OAuthIntrospectionCredentialStore.EnvironmentName };
    File.WriteAllText(Path.Combine(tunnel, "tunnel.json"), JsonSerializer.Serialize(new { resource_server = resource }));
    Check(OAuthIntrospectionCredentialStore.LoadOptional(root, tunnel) is null);
    var path = Path.Combine(root, "config", OAuthIntrospectionCredentialStore.FileName);
    // Missing store differs from a present but malformed/unreadable store: fail closed.
    File.WriteAllText(path, "{}");
    var sid = WindowsIdentity.GetCurrent().User!;
    var acl = new FileSecurity(); acl.SetOwner(sid); acl.SetAccessRuleProtection(true, false);
    acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, AccessControlType.Allow));
    new FileInfo(path).SetAccessControl(acl);
    Reject(() => OAuthIntrospectionCredentialStore.LoadOptional(root, tunnel));
    File.Delete(path);
    // Package validation is strict and happens before certificate/private-key access.
    var package = new Dictionary<string, object> {
        ["version"] = 1, ["purpose"] = "zagent-oauth-introspection", ["issuer"] = OAuthIntrospectionCredentialStore.Issuer,
        ["client_id"] = OAuthIntrospectionCredentialStore.ClientId, ["cert_sha256"] = new string('b', 64),
        ["ciphertext_algorithm"] = "RSA-OAEP-256", ["ciphertext"] = Convert.ToBase64String(new byte[256]),
        ["expires_at"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 300 };
    foreach (var mutation in new (string Key, object Value)[] {
        ("issuer", "http://insecure.invalid/realms/zagent"), ("client_id", "other"), ("version", 2),
        ("purpose", "other"), ("ciphertext_algorithm", "RSA1_5"), ("expires_at", 0),
        ("expires_at", DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 90000), ("extra", "reject") })
    {
        var invalid = new Dictionary<string, object>(package) { [mutation.Key] = mutation.Value };
        Reject(() => OAuthIntrospectionCredentialStore.Import(root, Encoding.UTF8.GetBytes(JsonSerializer.Serialize(invalid)), new string('0', 40)));
        Check(!File.Exists(path));
    }
    Reject(() => OAuthIntrospectionCredentialStore.Import(root, new byte[16385], new string('0',40)));
    var duplicate = JsonSerializer.Serialize(package).Replace("\"version\":1", "\"version\":1,\"version\":1");
    Reject(() => OAuthIntrospectionCredentialStore.Import(root, Encoding.UTF8.GetBytes(duplicate), new string('0',40)));
    // Disposable non-exportable CurrentUser key/certificate. No key export/PFX is used.
    var keyName = "Zagent-OAuth-Test-" + Guid.NewGuid().ToString("N");
    using var key = CngKey.Create(CngAlgorithm.Rsa, keyName, new CngKeyCreationParameters {
        Provider = CngProvider.MicrosoftSoftwareKeyStorageProvider, ExportPolicy = CngExportPolicies.None,
        KeyUsage = CngKeyUsages.AllUsages,
        Parameters = { new CngProperty("Length", BitConverter.GetBytes(2048), CngPropertyOptions.None) } });
    using var rsa = new RSACng(key);
    var request = new System.Security.Cryptography.X509Certificates.CertificateRequest("CN=Zagent OAuth disposable test", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
    using var certificate = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-1), DateTimeOffset.UtcNow.AddHours(1));
    using var store = new System.Security.Cryptography.X509Certificates.X509Store(System.Security.Cryptography.X509Certificates.StoreName.My, System.Security.Cryptography.X509Certificates.StoreLocation.CurrentUser);
    store.Open(System.Security.Cryptography.X509Certificates.OpenFlags.ReadWrite);
    try
    {
        store.Add(certificate);
        package["cert_sha256"] = Convert.ToHexString(SHA256.HashData(certificate.RawData)).ToLowerInvariant();
        package["ciphertext"] = Convert.ToBase64String(rsa.Encrypt(Encoding.ASCII.GetBytes(new string('a', 64)), RSAEncryptionPadding.OaepSHA256));
        var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(package));
        OAuthIntrospectionCredentialStore.Import(root, bytes, certificate.Thumbprint);
        InternalSecretStore.ValidatePrivatePath(path, directory: false);
        Check(OAuthIntrospectionCredentialStore.LoadOptional(root, tunnel) == new string('a', 64));
        foreach (var endpoint in new[] { "https://untrusted.invalid/introspect", resource.introspection_endpoint + "?redirect=1", resource.introspection_endpoint + "/", "http://vmi3669591.contaboserver.net/realms/zagent/protocol/openid-connect/token/introspect" })
        {
            File.WriteAllText(Path.Combine(tunnel, "tunnel.json"), JsonSerializer.Serialize(new { resource_server = new { issuer = resource.issuer, introspection_endpoint = endpoint, introspection_client_id = resource.introspection_client_id, introspection_secret_env = resource.introspection_secret_env } }));
            Reject(() => OAuthIntrospectionCredentialStore.LoadOptional(root, tunnel));
        }
        File.WriteAllText(Path.Combine(tunnel, "tunnel.json"), JsonSerializer.Serialize(new { resource_server = resource }));
        var original = File.ReadAllBytes(path);
        Reject(() => OAuthIntrospectionCredentialStore.Import(root, bytes, certificate.Thumbprint));
        Check(original.SequenceEqual(File.ReadAllBytes(path)));
        File.WriteAllText(Path.Combine(tunnel, "tunnel.json"), JsonSerializer.Serialize(new { resource_server = new { issuer = resource.issuer, introspection_client_id = "wrong", introspection_secret_env = resource.introspection_secret_env } }));
        Reject(() => OAuthIntrospectionCredentialStore.LoadOptional(root, tunnel));
        File.WriteAllText(Path.Combine(tunnel, "tunnel.json"), "{\"resource_server\":{}}");
        Check(OAuthIntrospectionCredentialStore.LoadOptional(root, tunnel) is null);
        Check(!File.Exists(Path.Combine(root, "config", InternalSecretStore.FileName)));
    }
    finally { store.Remove(certificate); key.Delete(); }
    // Inspect child ProcessStartInfo only: do not launch any product process.
    var environmentName = OAuthIntrospectionCredentialStore.EnvironmentName;
    var previous = Environment.GetEnvironmentVariable(environmentName);
    try
    {
        Environment.SetEnvironmentVariable(environmentName, "ambient-fixture-not-authority");
        var create = typeof(Zagent.Core.Supervision.NativeAgentSupervisor).GetMethod("CreateProcess", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!;
        foreach (var id in new[] { "agent.files", "agent.web", "agent.arcmap", "system.tunnel.transport", "system.tunnel.router" })
        {
            var definition = new Zagent.Core.Supervision.AgentProcessDefinition(id, Environment.ProcessPath!, [],
                EnvironmentVariables: new Dictionary<string, string> { [environmentName] = "explicit-fixture" });
            using var process = (System.Diagnostics.Process)create.Invoke(null, [definition])!;
            Check(id == "system.tunnel.router" ? process.StartInfo.Environment[environmentName] == "explicit-fixture" : !process.StartInfo.Environment.ContainsKey(environmentName));
        }
    }
    finally { Environment.SetEnvironmentVariable(environmentName, previous); }
    Console.WriteLine("PASS: optional missing, malformed/mismatch fail-closed, strict package validation, RSA/DPAPI roundtrip, ACL, no overwrite and Router-only environment.");
}
finally { Directory.Delete(root, recursive: true); }

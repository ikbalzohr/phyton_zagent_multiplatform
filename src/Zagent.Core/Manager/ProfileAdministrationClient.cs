using System.Security.AccessControl;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Zagent.Core.Manager;

/// <summary>Exact typed adapter to the existing private Files MCP endpoint. Not a native Files authority broker.</summary>
public sealed class ProfileAdministrationClient : IDisposable
{
    public static readonly string[] Actions = ["list", "get", "create", "update", "delete", "set_default"];
    private readonly Uri _endpoint;
    private readonly HttpClient _http;
    private readonly Func<OwnerProfileAdministrationBinding> _binding;
    public ProfileAdministrationClient(Uri endpoint, Func<OwnerProfileAdministrationBinding> binding, HttpMessageHandler? handler = null)
    {
        if (!endpoint.IsAbsoluteUri || endpoint.Scheme is not ("http" or "https") ||
            endpoint.Host is not ("127.0.0.1" or "127.0.0.3" or "localhost" or "[::1]" or "::1") ||
            endpoint.UserInfo != "" || endpoint.Query != "" || endpoint.Fragment != "" || endpoint.AbsolutePath != "/mcp")
            throw new ArgumentException("Exact private loopback Files /mcp endpoint required.");
        _endpoint = endpoint; _binding = binding;
        // Deliberately NOT InternalManagementChannel.CreateClient: that handler rewrites actor/resources.
        _http = new HttpClient(handler ?? new SocketsHttpHandler { UseProxy = false, AllowAutoRedirect = false })
            { Timeout = TimeSpan.FromSeconds(300) };
    }
    public Task<JsonObject> CatalogAsync(string actor, CancellationToken cancellationToken) =>
        SendAsync("files_profile_catalog_snapshot", new JsonObject(), actor, null, cancellationToken);
    public Task<JsonObject> AdminAsync(string action, JsonObject arguments, string actor, CancellationToken cancellationToken)
    {
        if (!Actions.Contains(action, StringComparer.Ordinal)) throw new ArgumentException("Unknown profile action.");
        return SendAsync("files_profile_admin_" + action, arguments, actor, action, cancellationToken);
    }
    public static string PayloadDigest(JsonObject arguments) => Convert.ToHexString(SHA256.HashData(
        Encoding.UTF8.GetBytes(InternalManagementChannel.Canonicalize(arguments)))).ToLowerInvariant();
    public static JsonObject BuildContext(OwnerProfileAdministrationBinding binding, string actor, string tool,
        string? action, JsonObject arguments, long deadline, string requestId, string operationId)
    {
        if (string.IsNullOrWhiteSpace(actor) || actor.Length > 256) throw new ArgumentException("Authenticated actor required.");
        var context = new JsonObject {
            ["version"] = 1, ["source"] = "dashboard", ["actor_id"] = actor,
            ["principal_id"] = binding.PrincipalId, ["workspace_id"] = binding.WorkspaceId,
            ["device_id"] = binding.DeviceId, ["installation_id"] = binding.InstallationId, ["deadline"] = deadline
        };
        if (action is not null) {
            if (!Actions.Contains(action, StringComparer.Ordinal) || tool != "files_profile_admin_" + action)
                throw new ArgumentException("Tool/action mismatch.");
            context["action"] = action; context["public_tool"] = tool;
            context["request_id"] = requestId; context["operation_id"] = operationId;
            context["capability_revision"] = binding.CapabilityRevision; context["payload_digest"] = PayloadDigest(arguments);
            context["bootstrap_resource"] = binding.BootstrapResource.DeepClone();
        } else if (tool != "files_profile_catalog_snapshot") throw new ArgumentException("Unknown catalog method.");
        return context;
    }
    private async Task<JsonObject> SendAsync(string tool, JsonObject arguments, string actor, string? action, CancellationToken cancellationToken)
    {
        // Re-read the exact active owner mapping on EVERY call. No owner selection by browser argument.
        var binding = _binding();
        var id = Guid.NewGuid().ToString("N");
        var context = BuildContext(binding, actor, tool, action, arguments,
            Math.Min(DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 300, binding.ExpiresAt), id, id);
        var body = new JsonObject { ["jsonrpc"] = "2.0", ["id"] = id, ["method"] = "tools/call",
            ["params"] = new JsonObject { ["name"] = tool, ["arguments"] = arguments.DeepClone(),
                ["_meta"] = new JsonObject { [action is null ? "zagent.profile_catalog_context" : "zagent.profile_admin_context"] = context } } };
        using var request = new HttpRequestMessage(HttpMethod.Post, _endpoint) { Content = JsonContent.Create(body) };
        request.Headers.Add("X-Zagent-Internal-Token", InternalManagementChannel.GetChildSecret("ZAGENT_INTERNAL_TOKEN"));
        using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        response.EnsureSuccessStatusCode();
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var bytes = new MemoryStream();
        var buffer = new byte[8192]; int count;
        while ((count = await stream.ReadAsync(buffer, cancellationToken)) != 0) {
            if (bytes.Length + count > 262144) throw new InvalidDataException("Private profile response too large.");
            bytes.Write(buffer, 0, count);
        }
        var outcome = DecodeResponse(bytes.ToArray());
        if (action is null) outcome["default_profile_id"] = outcome["owner"]?["default_profile_id"]?.DeepClone()
            ?? binding.BootstrapResource["default_profile_id"]!.DeepClone();
        return outcome;
    }
    public static JsonObject DecodeResponse(byte[] bytes)
    {
        using var strict = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 32 });
        OwnerProfileAdministrationBinding.RejectDuplicates(strict.RootElement);
        var rpc = JsonNode.Parse(bytes)!.AsObject();
        if (rpc.ContainsKey("error") || rpc["result"] is not JsonObject result)
            throw new InvalidDataException("Private profile RPC failed; outcome not assumed.");
        if (result["isError"]?.GetValue<bool>() == true) {
            var texts = result["content"]?.ToJsonString() ?? "";
            foreach (var code in new[] { "REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "PROFILE_ALREADY_EXISTS", "PROFILE_NOT_FOUND",
                "EXPLICIT_REPLACEMENT_DEFAULT_REQUIRED", "DEFAULT_PROFILE_NOT_USABLE", "INVALID_PROFILE_CHANGES", "INVALID_PROFILE_ROOT",
                "LOCAL_ABSOLUTE_ROOT_REQUIRED", "LOCAL_DRIVE_ABSOLUTE_ROOT_REQUIRED", "PRIVATE_ROOT_OVERLAP", "REPARSE_PROFILE_ROOT",
                "PROFILE_ROOT_ALREADY_EXISTS", "INVALID_ADMIN_ARGUMENT_FIELDS", "INVALID_PROFILE_ID", "INVALID_PROFILE_MODE",
                "INVALID_PROFILE_ENABLED", "INVALID_PROFILE_DESCRIPTION", "INVALID_EXPECTED_REVISION", "INVALID_IDEMPOTENCY_KEY",
                "REPLACEMENT_NOT_IN_OWNER_MEMBERSHIP", "PROFILE_NOT_IN_OWNER_MEMBERSHIP", "PROFILE_CONTEXT_EXPIRED" })
                if (System.Text.RegularExpressions.Regex.IsMatch(texts, @"\b" + code + @"\b")) throw new ProfileAdministrationDeniedException(code);
            throw new InvalidDataException("Private profile administration denied.");
        }
        JsonObject? data = result["structuredContent"] as JsonObject;
        if (data is null && result["content"] is JsonArray content) {
            var texts = content.OfType<JsonObject>().Where(c => c["type"]?.GetValue<string>() == "text").ToArray();
            if (texts.Length == 1) {
                var text = texts[0]["text"]!.GetValue<string>();
                using var parsed = JsonDocument.Parse(text); OwnerProfileAdministrationBinding.RejectDuplicates(parsed.RootElement);
                data = JsonNode.Parse(text) as JsonObject;
            }
        }
        // Files FastMCP may expose a plain result object. Never treat a protocol envelope as committed domain state.
        data ??= result.ContainsKey("revision") ? result : null;
        if (data is null || data["revision"] is not JsonValue revision || !revision.TryGetValue<string>(out var value) ||
            value.Length != 64 || !value.All(Uri.IsHexDigit)) throw new InvalidDataException("Missing authoritative catalog revision.");
        return (JsonObject)data.DeepClone();
    }
    public void Dispose() => _http.Dispose();
}

public sealed class ProfileAdministrationDeniedException(string code) : InvalidOperationException("Profile administration rejected.")
{
    public string Code { get; } = code;
}

public sealed record OwnerProfileAdministrationBinding(string PrincipalId, string WorkspaceId, string DeviceId,
    string InstallationId, string CapabilityRevision, JsonObject BootstrapResource, long ExpiresAt)
{
    public static OwnerProfileAdministrationBinding Load(string dataRoot, string workspaceId, string deviceId, string installationId)
    {
        var path = Path.Combine(dataRoot, "tunnel", "config", "tunnel.json");
        ValidatePrivateConfig(dataRoot, path);
        using var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (file.Length is < 2 or > 1048576) throw new InvalidDataException("Profile capability configuration size invalid.");
        var bytes = new byte[(int)file.Length]; file.ReadExactly(bytes);
        if (file.ReadByte() != -1) throw new InvalidDataException("Profile capability configuration changed.");
        using var doc = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 32 });
        RejectDuplicates(doc.RootElement);
        return Parse(doc.RootElement, workspaceId, deviceId, installationId, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
    }
    public static OwnerProfileAdministrationBinding Parse(JsonElement config, string workspaceId, string deviceId, string installationId, long now)
    {
        RejectDuplicates(config);
        var rs = config.GetProperty("resource_server");
        if (rs.GetProperty("workspace_id").GetString() != workspaceId) throw new InvalidDataException("Owner workspace mismatch.");
        var owners = rs.GetProperty("grants").EnumerateObject().Where(g =>
            g.Value.TryGetProperty("profile_management", out var c) && c.ValueKind == JsonValueKind.Object &&
            c.TryGetProperty("enabled", out var e) && e.ValueKind == JsonValueKind.True).ToArray();
        if (owners.Length != 1) throw new InvalidDataException("Exactly one explicit enabled owner capability mapping required.");
        var owner = owners[0]; var grant = owner.Value; var cap = grant.GetProperty("profile_management");
        ExactKeys(cap, "version", "enabled", "workspace_id", "device_id", "installation_id", "actions");
        if (!cap.GetProperty("version").TryGetInt32(out var version) || version != 1 ||
            cap.GetProperty("workspace_id").GetString() != workspaceId || cap.GetProperty("device_id").GetString() != deviceId ||
            cap.GetProperty("installation_id").GetString() != installationId ||
            grant.GetProperty("revoked").ValueKind != JsonValueKind.False ||
            !grant.GetProperty("expires_at").TryGetInt64(out var expiry) || expiry <= now)
            throw new InvalidDataException("Inactive or mismatched owner capability.");
        foreach (var value in new[] { owner.Name, workspaceId, deviceId, installationId })
            if (value.Length is < 1 or > 256 || string.IsNullOrWhiteSpace(value)) throw new InvalidDataException("Invalid owner binding.");
        var actions = Strings(cap.GetProperty("actions"), 6);
        if (!actions.Order(StringComparer.Ordinal).SequenceEqual(ProfileAdministrationClient.Actions.Order(StringComparer.Ordinal)))
            throw new InvalidDataException("Exact owner action set required.");
        var scopes = Strings(grant.GetProperty("scopes"), 128); var tools = Strings(grant.GetProperty("tools"), 512);
        foreach (var action in ProfileAdministrationClient.Actions) {
            var tool = "files_profile_admin_" + action; var scope = action is "list" or "get" ? "files:read" : "files:write";
            var policy = config.GetProperty("tool_policy").GetProperty(tool);
            if (!scopes.Contains(scope) || !tools.Contains(tool) || policy.GetProperty("scope").GetString() != scope ||
                (policy.TryGetProperty("enabled", out var enabled) && enabled.ValueKind != JsonValueKind.True))
                throw new InvalidDataException("Exact enabled profile management scope/tool policy required.");
        }
        var resource = grant.GetProperty("files_resource");
        if (resource.GetProperty("kind").GetString() != "files" || resource.GetProperty("revoked").ValueKind != JsonValueKind.False ||
            resource.GetProperty("device_id").GetString() != deviceId || resource.GetProperty("installation_id").GetString() != installationId)
            throw new InvalidDataException("Owner resource placement mismatch.");
        var defaultId = resource.GetProperty("profile_id").GetString() ?? throw new InvalidDataException("Missing owner default profile.");
        var allowed = resource.TryGetProperty("allowed_profile_ids", out var ids) ? Strings(ids, 128) : new[] { defaultId };
        if (!allowed.Contains(defaultId)) throw new InvalidDataException("Owner default outside membership.");
        foreach (var id in allowed) if (id.Length is < 1 or > 256 || !id.All(c => char.IsAsciiLetterOrDigit(c) || c is '_' or '-'))
            throw new InvalidDataException("Invalid profile identifier.");
        var resourceId = resource.GetProperty("resource_id").GetString();
        if (resourceId is null || resourceId.Length is < 1 or > 256) throw new InvalidDataException("Invalid owner resource.");
        var capNode = JsonNode.Parse(cap.GetRawText())!;
        var revision = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(InternalManagementChannel.Canonicalize(capNode)))).ToLowerInvariant();
        return new(owner.Name, workspaceId, deviceId, installationId, revision,
            new JsonObject { ["resource_id"] = resourceId, ["default_profile_id"] = defaultId,
                ["allowed_profile_ids"] = new JsonArray(allowed.Select(x => (JsonNode?)JsonValue.Create(x)).ToArray()) }, expiry);
    }
    private static string[] Strings(JsonElement array, int max)
    {
        if (array.ValueKind != JsonValueKind.Array || array.GetArrayLength() is < 1 || array.GetArrayLength() > max) throw new InvalidDataException();
        var values = array.EnumerateArray().Select(x => x.GetString() ?? throw new InvalidDataException()).ToArray();
        if (values.Any(x => x.Length is < 1 or > 256) || values.Distinct(StringComparer.Ordinal).Count() != values.Length) throw new InvalidDataException();
        return values;
    }
    public static void RejectDuplicates(JsonElement node)
    {
        if (node.ValueKind == JsonValueKind.Object) {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var p in node.EnumerateObject()) { if (!seen.Add(p.Name)) throw new InvalidDataException("Duplicate JSON key."); RejectDuplicates(p.Value); }
        } else if (node.ValueKind == JsonValueKind.Array) foreach (var v in node.EnumerateArray()) RejectDuplicates(v);
    }
    private static void ExactKeys(JsonElement node, params string[] keys)
    {
        if (node.ValueKind != JsonValueKind.Object || !node.EnumerateObject().Select(p => p.Name).Order(StringComparer.Ordinal).SequenceEqual(keys.Order(StringComparer.Ordinal)))
            throw new InvalidDataException("Invalid capability schema.");
    }
    private static void ValidatePrivateConfig(string dataRoot, string path)
    {
        // Mirror the platform guard used by InternalSecretStore.ValidatePrivatePath so the
        // analyzer can prove this Windows-only ACL walk is unreachable on other platforms.
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Owner ACL validation requires Windows.");
        InternalSecretStore.ValidatePrivatePath(dataRoot, directory: true);
        var owner = WindowsIdentity.GetCurrent().User ?? throw new InvalidDataException();
        for (var walk = path; !string.Equals(walk, dataRoot, StringComparison.OrdinalIgnoreCase); walk = Path.GetDirectoryName(walk) ?? throw new InvalidDataException()) {
            // Configs produced by Core may inherit the protected owner's ACL.
            for (var ancestor = walk; ancestor is not null; ancestor = Path.GetDirectoryName(ancestor))
                if ((File.GetAttributes(ancestor) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Reparse private config.");
            var directory = Directory.Exists(walk);
            System.Security.AccessControl.FileSystemSecurity acl = directory
                ? new DirectoryInfo(walk).GetAccessControl() : new FileInfo(walk).GetAccessControl();
            var rules = acl.GetAccessRules(true, true, typeof(System.Security.Principal.SecurityIdentifier)).Cast<System.Security.AccessControl.FileSystemAccessRule>().ToArray();
            var inheritance = directory ? System.Security.AccessControl.InheritanceFlags.ContainerInherit | System.Security.AccessControl.InheritanceFlags.ObjectInherit : System.Security.AccessControl.InheritanceFlags.None;
            if (!owner.Equals(acl.GetOwner(typeof(System.Security.Principal.SecurityIdentifier))) || rules.Length != 1 ||
                !owner.Equals(rules[0].IdentityReference) || rules[0].AccessControlType != System.Security.AccessControl.AccessControlType.Allow ||
                rules[0].FileSystemRights != System.Security.AccessControl.FileSystemRights.FullControl || rules[0].InheritanceFlags != inheritance ||
                rules[0].PropagationFlags != System.Security.AccessControl.PropagationFlags.None) throw new InvalidDataException("Private owner ACL required.");
        }
    }
}

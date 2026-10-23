using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;

namespace Zagent.Core.Manager;

/// <summary>Private owner-to-agent channel. Never accepts browser/model supplied authority metadata.</summary>
public static class InternalManagementChannel
{
    private sealed record Provisioning(string Token, string ContextKey, string WorkspaceId,
        string DeviceId, string InstallationId, string FilesConfigRoot);
    private static Provisioning? _provisioning;

    internal static void Configure(string token, string contextKey, string workspaceId,
        string deviceId, string installationId, string filesConfigRoot)
    {
        foreach (var value in new[] { workspaceId, deviceId, installationId })
            if (string.IsNullOrWhiteSpace(value) || value.Length > 128)
                throw new InvalidOperationException("Private management identity is not provisioned.");
        _provisioning = new(token, contextKey, workspaceId, deviceId, installationId, filesConfigRoot);
        ValidateProvisioning();
    }

    public static string GetChildSecret(string name)
    {
        ValidateProvisioning();
        return name switch {
            "ZAGENT_INTERNAL_TOKEN" => _provisioning!.Token,
            "ZAGENT_INTERNAL_CONTEXT_KEY" => _provisioning!.ContextKey,
            _ => throw new ArgumentException("Unknown private channel secret.", nameof(name))
        };
    }

    public static HttpClient CreateClient(TimeSpan timeout) => new(new ManagementHandler {
        InnerHandler = new SocketsHttpHandler { UseProxy = false, AllowAutoRedirect = false }
    }) { Timeout = timeout };

    public static void ValidateProvisioning()
    {
        var p = _provisioning ?? throw new InvalidOperationException("Private management channel is not provisioned.");
        foreach (var secret in new[] { p.Token, p.ContextKey })
            if (Encoding.UTF8.GetByteCount(secret) < 32 || secret.Any(char.IsWhiteSpace))
                throw new InvalidOperationException("Private management channel credentials are invalid.");
    }

    // Explicit local management surface, not an arbitrary tool-call authority broker.
    private static (string Kind, bool Write) ToolPolicy(string tool) => tool switch {
        "files_workspace_list" => ("files", false),
        "arcmap_ping" => ("arcmap", false),
        "web_bridge_status" or "web_bridge_pair_status" => ("browser", false),
        // Backend treats chrome_launch_status as write; do not weaken its gate.
        "web_chrome_launch_status" or "web_bridge_pair" or "web_bridge_disconnect" or
        "web_bridge_reconnect" or "web_bridge_authorize_request" => ("browser", true),
        _ => throw new InvalidOperationException("Tool is not in the local management allowlist.")
    };

    private static JsonArray Resources(Provisioning p, string kind)
    {
        if (kind != "files") return new JsonArray(new JsonObject {
            ["resource_id"] = "installation:" + p.InstallationId, ["kind"] = kind });
        // Re-read locally approved state for every call; names/arguments never grant scope.
        var document = JsonNode.Parse(File.ReadAllText(Path.Combine(p.FilesConfigRoot, "profiles.json")))!.AsObject();
        var name = document["active_profile"]?.GetValue<string>();
        var approved = document["profiles"]!.AsArray().OfType<JsonObject>().Where(profile =>
            profile["name"]?.GetValue<string>() == name &&
            profile["enabled"]?.GetValue<bool>() == true &&
            profile["authorized_by_user"]?.GetValue<bool>() == true).ToArray();
        if (string.IsNullOrWhiteSpace(name) || approved.Length != 1 ||
            approved[0]["mode"]?.GetValue<string>() is not ("read-only" or "read-write"))
            throw new InvalidOperationException("An enabled locally approved Files profile is required.");
        return new JsonArray(new JsonObject {
            ["resource_id"] = "files:" + name, ["kind"] = "files", ["profile_id"] = name });
    }

    private sealed class ManagementHandler : DelegatingHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            ValidateProvisioning();
            var p = _provisioning!;
            if (request.RequestUri is not { } uri || uri.Scheme is not ("http" or "https") ||
                uri.Host is not ("127.0.0.1" or "127.0.0.3" or "localhost" or "[::1]" or "::1") ||
                uri.UserInfo != "" || uri.Fragment != "" ||
                (uri.Query != "" && !uri.AbsolutePath.StartsWith("/router/", StringComparison.Ordinal)))
                throw new InvalidOperationException("Private agent channels require an exact loopback URL.");
            request.Headers.Remove("X-Zagent-Internal-Token");
            request.Headers.Add("X-Zagent-Internal-Token", p.Token);
            if (request.Content is not null && request.Content.Headers.ContentType?.MediaType == "application/json") {
                var body = JsonNode.Parse(await request.Content.ReadAsStringAsync(cancellationToken))!.AsObject();
                if (body["method"]?.GetValue<string>() == "tools/call" && body["params"] is JsonObject parameters) {
                    var tool = parameters["name"]!.GetValue<string>();
                    var (kind, write) = ToolPolicy(tool);
                    var scope = (kind == "browser" ? "web" : kind) + (write ? ":write" : ":read");
                    var context = new JsonObject {
                        ["context_version"] = 1,
                        ["principal_id"] = "windows-management:" + Environment.UserDomainName + "/" + Environment.UserName,
                        ["workspace_id"] = p.WorkspaceId, ["device_id"] = p.DeviceId,
                        ["installation_id"] = p.InstallationId,
                        ["operation_id"] = Guid.NewGuid().ToString("N"), ["request_id"] = Guid.NewGuid().ToString("N"),
                        ["trace_id"] = Guid.NewGuid().ToString("N"), ["task_id"] = Guid.NewGuid().ToString("N"),
                        ["deadline"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 300,
                        ["effective_access"] = write ? "write" : "read", ["policy_revision"] = "local-management-v1",
                        ["required_scope"] = scope, ["public_tool"] = tool,
                        ["scopes"] = new JsonArray(JsonValue.Create(scope)), ["effective_resources"] = Resources(p, kind)
                    };
                    // The authenticated HTTP token establishes trust; no backend verifies a custom HMAC.
                    parameters["_meta"] = new JsonObject { ["zagent.execution_context"] = context };
                    request.Content.Dispose();
                    request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
                }
            }
            return await base.SendAsync(request, cancellationToken);
        }
    }

    // Retained canonical JSON utility for callers; not an authentication mechanism.
    public static string Canonicalize(JsonNode? value)
    {
        if (value is JsonObject obj) return "{" + string.Join(",", obj.OrderBy(p => p.Key, StringComparer.Ordinal)
            .Select(p => Quote(p.Key) + ":" + Canonicalize(p.Value))) + "}";
        if (value is JsonArray arr) return "[" + string.Join(",", arr.Select(Canonicalize)) + "]";
        if (value is null) return "null";
        if (value is JsonValue scalar && scalar.TryGetValue<string>(out var text)) return Quote(text);
        return value.ToJsonString();
    }
    private static string Quote(string value)
    {
        var b = new StringBuilder("\"");
        foreach (var c in value) b.Append(c switch { '"' => "\\\"", '\\' => "\\\\", '\b' => "\\b", '\f' => "\\f", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t",
            < ' ' or > '~' => "\\u" + ((int)c).ToString("x4", CultureInfo.InvariantCulture), _ => c.ToString() });
        return b.Append('"').ToString();
    }
}

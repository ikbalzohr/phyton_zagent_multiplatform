using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Zagent.Core.Manager;

/// <summary>Private owner-to-agent channel. Never accepts browser/model supplied authority metadata.</summary>
public static class InternalManagementChannel
{
    public static HttpClient CreateClient(TimeSpan timeout) => new(new ManagementHandler {
        InnerHandler = new SocketsHttpHandler { UseProxy = false, AllowAutoRedirect = false }
    }) { Timeout = timeout };

    public static void ValidateProvisioning()
    {
        foreach (var name in new[] { "ZAGENT_INTERNAL_TOKEN", "ZAGENT_INTERNAL_CONTEXT_KEY" })
            if (Encoding.UTF8.GetByteCount(Environment.GetEnvironmentVariable(name) ?? "") < 32)
                throw new InvalidOperationException("Private management channel is not provisioned: " + name);
        if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ZAGENT_DEFAULT_WORKSPACE_ID")))
            throw new InvalidOperationException("Installation workspace must be provisioned.");
    }

    private sealed class ManagementHandler : DelegatingHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            ValidateProvisioning();
            if (request.RequestUri is null || !request.RequestUri.IsLoopback)
                throw new InvalidOperationException("Private agent channels cannot leave loopback.");
            request.Headers.Remove("X-Zagent-Internal-Token");
            request.Headers.Add("X-Zagent-Internal-Token", Environment.GetEnvironmentVariable("ZAGENT_INTERNAL_TOKEN"));
            if (request.Content is not null && request.Content.Headers.ContentType?.MediaType == "application/json") {
                var body = JsonNode.Parse(await request.Content.ReadAsStringAsync(cancellationToken))!;
                if (body["method"]?.GetValue<string>() == "tools/call" && body["params"] is JsonObject parameters) {
                    var tool = parameters["name"]!.GetValue<string>();
                    var arguments = parameters["arguments"] is null ? new JsonObject() : parameters["arguments"].DeepClone()!.AsObject();
                    var profile = arguments["profile_id"]?.GetValue<string>() ?? arguments["name"]?.GetValue<string>() ?? "appBridge";
                    var context = new JsonObject {
                        ["context_version"] = 1, ["principal_id"] = "windows-management:" + Environment.UserDomainName + "/" + Environment.UserName,
                        ["workspace_id"] = Environment.GetEnvironmentVariable("ZAGENT_DEFAULT_WORKSPACE_ID"),
                        ["device_id"] = Environment.GetEnvironmentVariable("ZAGENT_DEVICE_ID"),
                        ["installation_id"] = Environment.GetEnvironmentVariable("ZAGENT_INSTALLATION_ID"),
                        ["operation_id"] = Guid.NewGuid().ToString("N"), ["request_id"] = Guid.NewGuid().ToString("N"),
                        ["trace_id"] = Guid.NewGuid().ToString("N"), ["expires_at"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 60,
                        ["effective_access"] = "write", ["policy_revision"] = "local-management-v1",
                        ["effective_resources"] = new JsonArray(
                            new JsonObject { ["resource_id"] = "files:" + profile, ["kind"] = "files", ["profile_id"] = profile },
                            new JsonObject { ["resource_id"] = "browser", ["kind"] = "browser" },
                            new JsonObject { ["resource_id"] = "desktop", ["kind"] = "arcmap" })
                    };
                    var payload = Canonicalize(new JsonObject { ["tool"] = tool, ["arguments"] = arguments, ["context"] = context.DeepClone() });
                    var signature = Convert.ToHexString(HMACSHA256.HashData(
                        Encoding.UTF8.GetBytes(Environment.GetEnvironmentVariable("ZAGENT_INTERNAL_CONTEXT_KEY")!), Encoding.UTF8.GetBytes(payload))).ToLowerInvariant();
                    parameters["_meta"] = new JsonObject { ["zagent.execution_context"] = context.DeepClone(),
                        ["zagent.context_signature"] = signature, ["zagent.context_payload"] = payload };
                    request.Content.Dispose();
                    request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
                }
            }
            return await base.SendAsync(request, cancellationToken);
        }
    }
    // Python json.dumps(sort_keys=True,separators=(',', ':'),ensure_ascii=True) wire contract.
    public static string Canonicalize(JsonNode? value) => JsonCanonical(value);
    private static string JsonCanonical(JsonNode? value)
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

using System.Text.Json;
using System.Text.Json.Nodes;
using Zagent.Core.Manager;

internal static class OwnerBindingReasonTests
{
    private const long Now = 1_900_000_000;
    internal static async Task Run()
    {
        using (var duplicate = JsonDocument.Parse("{\"fixture-key\":1,\"fixture-key\":2}")) {
            try { OwnerProfileAdministrationBinding.Parse(duplicate.RootElement, "fixture-workspace", "fixture-device", "fixture-installation", Now); throw new Exception("Duplicate accepted"); }
            catch (InvalidDataException ex) { if ((string?)ex.Data["ZagentProfileReason"] != "CONFIG_DUPLICATE_KEY") throw new Exception("Duplicate gate reason missing"); }
        }
        if (!OperatingSystem.IsWindows()) {
            try { OwnerProfileAdministrationBinding.Load("fixture-not-a-real-path", "fixture-workspace", "fixture-device", "fixture-installation"); throw new Exception("Windows guard bypassed"); }
            catch (PlatformNotSupportedException ex) { if ((string?)ex.Data["ZagentProfileReason"] != "CONFIG_PLATFORM") throw new Exception("Platform gate reason missing"); }
        }
        var valid = Fixture();
        using (var document = JsonDocument.Parse(valid.ToJsonString())) {
            var binding = OwnerProfileAdministrationBinding.Parse(document.RootElement, "fixture-workspace", "fixture-device", "fixture-installation", Now);
            if (binding.PrincipalId != "fixture-principal" || binding.BootstrapResource["default_profile_id"]!.GetValue<string>() != "fixture-root")
                throw new Exception("Valid binding changed");
        }
        await Reject("CAPABILITY_MISSING", c => Grant(c).Remove("profile_management"));
        await Reject("CAPABILITY_MISSING", c => Grant(c)["profile_management"]!["enabled"] = false);
        await Reject("CAPABILITY_AMBIGUOUS", c => c["resource_server"]!["grants"]!["other-fixture-principal"] = Grant(c).DeepClone());
        await Reject("CONFIG_SCHEMA", c => c.Remove("resource_server"));
        await Reject("WORKSPACE_MISMATCH", c => c["resource_server"]!["workspace_id"] = "other-fixture");
        await Reject("CAPABILITY_SCHEMA", c => Grant(c)["profile_management"]!["extra"] = true);
        await Reject("CAPABILITY_VERSION", c => Grant(c)["profile_management"]!["version"] = 2);
        await Reject("CAPABILITY_WORKSPACE", c => Grant(c)["profile_management"]!["workspace_id"] = "other-fixture");
        await Reject("CAPABILITY_DEVICE", c => Grant(c)["profile_management"]!["device_id"] = "other-fixture");
        await Reject("CAPABILITY_INSTALLATION", c => Grant(c)["profile_management"]!["installation_id"] = "other-fixture");
        await Reject("GRANT_REVOKED", c => Grant(c)["revoked"] = true);
        await Reject("GRANT_EXPIRY", c => Grant(c)["expires_at"] = Now);
        await Reject("GRANT_EXPIRY", c => Grant(c).Remove("expires_at"));
        await Reject("CAPABILITY_ACTIONS", c => Grant(c)["profile_management"]!["actions"] = new JsonArray("list"));
        await Reject("GRANT_SCOPES", c => Grant(c)["scopes"] = new JsonArray("files:read"));
        await Reject("GRANT_TOOLS", c => Grant(c)["tools"]!.AsArray().RemoveAt(0));
        await Reject("TOOL_POLICY", c => c["tool_policy"]!.AsObject().Remove("files_profile_admin_list"));
        await Reject("TOOL_POLICY", c => c["tool_policy"]!["files_profile_admin_list"]!["enabled"] = false);
        await Reject("TOOL_POLICY", c => c["tool_policy"]!["files_profile_admin_list"]!["scope"] = "files:write");
        await Reject("RESOURCE_SCHEMA", c => Grant(c).Remove("files_resource"));
        await Reject("RESOURCE_KIND", c => Grant(c)["files_resource"]!["kind"] = "other-fixture");
        await Reject("RESOURCE_REVOKED", c => Grant(c)["files_resource"]!["revoked"] = true);
        await Reject("RESOURCE_DEVICE", c => Grant(c)["files_resource"]!["device_id"] = "other-fixture");
        await Reject("RESOURCE_INSTALLATION", c => Grant(c)["files_resource"]!["installation_id"] = "other-fixture");
        await Reject("RESOURCE_DEFAULT", c => Grant(c)["files_resource"]!.AsObject().Remove("profile_id"));
        await Reject("RESOURCE_DEFAULT", c => Grant(c)["files_resource"]!["profile_id"] = null);
        await Reject("RESOURCE_MEMBERSHIP", c => Grant(c)["files_resource"]!["allowed_profile_ids"] = new JsonArray("other-fixture"));
        await Reject("RESOURCE_MEMBERSHIP", c => Grant(c)["files_resource"]!["allowed_profile_ids"] = new JsonArray("fixture-root", "fixture-root"));
        await Reject("RESOURCE_PROFILE_ID", c => { Grant(c)["files_resource"]!["profile_id"] = "invalid.fixture"; Grant(c)["files_resource"]!.AsObject().Remove("allowed_profile_ids"); });
        await Reject("GRANTS_SCHEMA", c => c["resource_server"]!.AsObject().Remove("grants"));
        await Reject("BINDING_IDENTIFIERS", c => { var grants = c["resource_server"]!["grants"]!.AsObject(); var grant = Grant(c).DeepClone(); grants.Clear(); grants[" "] = grant; });
        await Reject("RESOURCE_ID", c => Grant(c)["files_resource"]!.AsObject().Remove("resource_id"));
    }
    private static JsonObject Grant(JsonObject c) => c["resource_server"]!["grants"]!["fixture-principal"]!.AsObject();
    private static JsonObject Fixture()
    {
        var actions = ProfileAdministrationClient.Actions;
        var policies = new JsonObject();
        foreach (var action in actions) policies["files_profile_admin_" + action] = new JsonObject {
            ["scope"] = action is "list" or "get" ? "files:read" : "files:write", ["enabled"] = true };
        return new JsonObject {
            ["resource_server"] = new JsonObject { ["workspace_id"] = "fixture-workspace", ["grants"] = new JsonObject {
                ["fixture-principal"] = new JsonObject {
                    ["profile_management"] = new JsonObject { ["version"] = 1, ["enabled"] = true,
                        ["workspace_id"] = "fixture-workspace", ["device_id"] = "fixture-device", ["installation_id"] = "fixture-installation",
                        ["actions"] = new JsonArray(actions.Select(a => (JsonNode?)JsonValue.Create(a)).ToArray()) },
                    ["revoked"] = false, ["expires_at"] = Now + 3600,
                    ["scopes"] = new JsonArray("files:read", "files:write"),
                    ["tools"] = new JsonArray(actions.Select(a => (JsonNode?)JsonValue.Create("files_profile_admin_" + a)).ToArray()),
                    ["files_resource"] = new JsonObject { ["kind"] = "files", ["revoked"] = false,
                        ["device_id"] = "fixture-device", ["installation_id"] = "fixture-installation",
                        ["profile_id"] = "fixture-root", ["allowed_profile_ids"] = new JsonArray("fixture-root"), ["resource_id"] = "fixture-resource" }
                } } }, ["tool_policy"] = policies };
    }
    private static async Task Reject(string expected, Action<JsonObject> mutate)
    {
        var config = Fixture(); mutate(config);
        using var document = JsonDocument.Parse(config.ToJsonString());
        Exception? original = null;
        using var client = new ProfileAdministrationClient(new Uri("http://127.0.0.1:18811/mcp"), () => {
            try { return OwnerProfileAdministrationBinding.Parse(document.RootElement, "fixture-workspace", "fixture-device", "fixture-installation", Now); }
            catch (Exception ex) { original = ex; throw; }
        });
        try { await client.CatalogAsync("fixture-actor", CancellationToken.None); }
        catch (Exception ex) {
            if (!ReferenceEquals(original, ex) || ex.StackTrace?.Contains("OwnerProfileAdministrationBinding.Parse") != true)
                throw new Exception("Original validation exception/stack not preserved");
            if (ex.Data.Count != 2 || ex.Data.Values.Cast<object>().Any(v => v.ToString()!.Contains("fixture", StringComparison.Ordinal)))
                throw new Exception("Diagnostic data must contain only bounded reason and stage");
            if ((string?)ex.Data["ZagentProfileStage"] != "OWNER_BINDING") throw new Exception("Missing binding stage");
            if ((string?)ex.Data["ZagentProfileReason"] != expected)
                throw new Exception($"Expected {expected}, got {ex.Data["ZagentProfileReason"] ?? "<missing>"} ({ex.GetType().Name})");
            Console.WriteLine("PASS owner binding " + expected); return;
        }
        throw new Exception("Invalid fixture accepted: " + expected);
    }
}

using System.Net;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Zagent.Core.Manager;

internal static class TransportHeaderTests
{
    internal static async Task Run()
    {
        // Reuse the existing valid binding fixture without reading any enrollment/config files.
        var config = (JsonObject)typeof(OwnerBindingReasonTests)
            .GetMethod("Fixture", BindingFlags.Static | BindingFlags.NonPublic)!.Invoke(null, null)!;
        using var document = JsonDocument.Parse(config.ToJsonString());
        var binding = OwnerProfileAdministrationBinding.Parse(document.RootElement,
            "fixture-workspace", "fixture-device", "fixture-installation", DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        // Fixture-only provisioning, exactly as in ProfileAdministrationTests. No real secrets or live calls.
        typeof(InternalManagementChannel).GetMethod("Configure", BindingFlags.Static | BindingFlags.NonPublic)!
            .Invoke(null, [new string('a', 64), new string('b', 64), "fixture-workspace", "fixture-device",
                "fixture-installation", Path.Combine(Environment.CurrentDirectory, "fixture", "files", "config")]);

        var failures = new List<string>();
        foreach (var operation in new[] { "catalog", "admin-list" })
        {
            var handler = new McpAcceptRequirementHandler();
            using var client = new ProfileAdministrationClient(new Uri("http://127.0.0.1:18811/mcp"), () => binding, handler);
            JsonObject? outcome = null;
            HttpRequestException? rejected = null;
            try
            {
                outcome = operation == "catalog"
                    ? await client.CatalogAsync("fixture-actor", CancellationToken.None)
                    : await client.AdminAsync("list", new JsonObject(), "fixture-actor", CancellationToken.None);
            }
            catch (HttpRequestException ex) { rejected = ex; }

            if (handler.Calls != 1) throw new Exception("Expected exactly one real client request per operation");
            var missing = new[] { "application/json" }
                .Where(mediaType => !handler.Accept.Contains(mediaType, StringComparer.OrdinalIgnoreCase)).ToArray();
            if (missing.Length != 0)
            {
                if (rejected?.StatusCode != HttpStatusCode.NotAcceptable ||
                    (string?)rejected.Data["ZagentProfileStage"] != "PRIVATE_REQUEST")
                    throw new Exception("Fixture rejection must reach the real client's PRIVATE_REQUEST HTTP failure path");
                failures.Add($"{operation}: outgoing Accept=[{string.Join(", ", handler.Accept)}]; missing {string.Join(", ", missing)}; fixture HTTP 406, stage PRIVATE_REQUEST");
                continue;
            }
            if (rejected is not null) throw new Exception("MCP-compatible Accept unexpectedly rejected", rejected);
            if (outcome?["revision"]?.GetValue<string>() != new string('c', 64))
                throw new Exception("Real client did not decode the fixture success response");
            Console.WriteLine($"PASS real client {operation} advertises application/json for Files JSON-response mode (isolated handler fixture)");
        }
        if (failures.Count != 0)
            throw new Exception("MCP Accept header regression: " + string.Join("; ", failures));
    }

    // An isolated HTTP handler enforcing the MCP Accept requirement, NOT an actual Files backend.
    // Capture the request emitted by the production client; never add or repair its headers here.
    private sealed class McpAcceptRequirementHandler : HttpMessageHandler
    {
        internal int Calls;
        internal string[] Accept = [];
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            Accept = request.Headers.Accept.Where(value => value.Quality is null or > 0)
                .Select(value => value.MediaType!).ToArray();
            if (request.Headers.GetValues("X-Zagent-Internal-Token").Single() != new string('a', 64))
                throw new Exception("Expected fixture-only private token");
            if (request.Method != HttpMethod.Post || request.Content?.Headers.ContentType?.MediaType != "application/json")
                throw new Exception("Expected real MCP JSON POST");
            if (!Accept.Contains("application/json", StringComparer.OrdinalIgnoreCase))
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotAcceptable)
                {
                    Content = new StringContent("Files JSON-response fixture requires Accept: application/json")
                });
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(new JsonObject {
                    ["jsonrpc"] = "2.0", ["result"] = new JsonObject {
                        ["structuredContent"] = new JsonObject { ["revision"] = new string('c', 64), ["profiles"] = new JsonArray() }
                    }
                }.ToJsonString(), Encoding.UTF8, "application/json")
            });
        }
    }
}

using System.Reflection;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.HttpResults;
using Zagent.Core.Dashboard;
using Zagent.Core.Manager;

// Isolated exception/envelope regression. No Windows provisioning, server or credentials.
void Assert(bool condition, string label) { if (!condition) throw new Exception(label); }
var type = typeof(DashboardProfileAdministration);
var flags = BindingFlags.Static | BindingFlags.NonPublic;
var filter = type.GetMethod("DependencyFailure", flags)!;
var stage = type.GetMethod("DependencyStage", flags)!;
var problem = type.GetMethod("DependencyProblem", flags)!;
var injected = new InvalidDataException("fixture-only sensitive message must not escape");
using var client = new ProfileAdministrationClient(new Uri("http://127.0.0.1:18811/mcp"), () => throw injected);
try { await client.CatalogAsync("fixture-actor", CancellationToken.None); throw new Exception("Binding unexpectedly succeeded"); }
catch (InvalidDataException actual) {
    Assert(ReferenceEquals(actual, injected), "Original exception preserved");
    Assert((string?)actual.Data["ZagentProfileStage"] == "OWNER_BINDING", "Binding tagged before HTTP");
    Assert((bool)filter.Invoke(null, [actual])!, "InvalidDataException caught by dashboard");
    Assert((string)stage.Invoke(null, [actual])! == "OWNER_BINDING", "Stage propagated");
}
foreach (var value in new[] { "OWNER_BINDING", "PRIVATE_REQUEST", "RESPONSE_VALIDATION", "unsafe-secret", "" }) {
    var error = new InvalidDataException("private fixture text"); error.Data["ZagentProfileStage"] = value;
    var expected = value is "OWNER_BINDING" or "PRIVATE_REQUEST" or "RESPONSE_VALIDATION" ? value : "UNKNOWN";
    var safeStage = (string)stage.Invoke(null, [error])!;
    Assert(safeStage == expected, "Stage whitelist");
    var ctx = new DefaultHttpContext { TraceIdentifier = "fixture-request-123" };
    var result = (ProblemHttpResult)problem.Invoke(null, [ctx, 503, "Trusted profile catalog unavailable; no local fallback.", safeStage])!;
    Assert(result.ProblemDetails.Status == 503, "503 retained");
    Assert((string?)result.ProblemDetails.Extensions["requestId"] == ctx.TraceIdentifier, "Request ID retained");
    Assert((string?)result.ProblemDetails.Extensions["stage"] == expected, "Safe stage in response");
    Assert(result.ProblemDetails.Detail is null, "No exception detail");
    Assert(!result.ProblemDetails.Extensions.Values.Any(v => v?.ToString()?.Contains("private fixture text") == true), "No exception message leak");
}
Console.WriteLine("PASS real client binding InvalidDataException preserved/tagged/caught; safe 503 ProblemDetails and stage whitelist; no live services or credentials");

using System.Net;
using System.Text;
using Zagent.Core.Manager;
using Zagent.Core.Agents.ArcMap;

var passed = 0;
var failed = 0;

await RunAsync("workflow list is principal/workspace-scoped and parsed", async () =>
{
    var handler = new StubHttpHandler(request =>
    {
        var uri = request.RequestUri ?? throw new InvalidOperationException();
        True(uri.AbsolutePath == "/router/workflows", "unexpected path");
        True(uri.Query.Contains("principal_id=principal%20a"), "principal query missing");
        True(uri.Query.Contains("workspace_id=workspace%20a"), "workspace query missing");
        return Json("""
        {
          "ok": true,
          "count": 1,
          "runs": [
            {
              "run_id": "run_1",
              "plan_id": "plan_1",
              "state": "RECONCILING",
              "strategy": "A_EXISTING_MXD",
              "repair_count": 2,
              "created_at": 10.0,
              "updated_at": 20.0,
              "finished_at": null
            }
          ]
        }
        """);
    });
    using var http = new HttpClient(handler);
    var model = new TunnelManagerReadModel(new Uri("http://127.0.0.3:19999/"), http);
    var snapshot = await model.GetManagementWorkflowsAsync("principal a", "workspace a", null);
    Equal(1, snapshot.GetProperty("count").GetInt32());
    var firstRun = snapshot.GetProperty("runs")[0];
    Equal("run_1", firstRun.GetProperty("run_id").GetString());
    Equal("RECONCILING", firstRun.GetProperty("state").GetString());
    Equal(2, firstRun.GetProperty("repair_count").GetInt32());
});

await RunAsync("workflow evidence retains structured report and redacts secrets", async () =>
{
    var handler = new StubHttpHandler(request =>
    {
        var uri = request.RequestUri ?? throw new InvalidOperationException();
        True(uri.AbsolutePath == "/router/workflows/run_1", "unexpected evidence path");
        True(uri.Query.Contains("principal_id=p"), "principal query missing");
        True(uri.Query.Contains("workspace_id=w"), "workspace query missing");
        return Json("""
        {
          "ok": true,
          "report": {
            "run": {"run_id":"run_1","state":"FAILED","session_id":"private"},
            "validations":[{"status":"FAIL","token":"not-for-clients"}],
            "artifacts":[]
          }
        }
        """);
    });
    using var http = new HttpClient(handler);
    var model = new TunnelManagerReadModel(new Uri("http://127.0.0.3:19999/"), http);
    var evidence = await model.GetManagementWorkflowsAsync("p", "w", "run_1");
    var report = evidence.GetProperty("report");
    Equal("FAILED", report.GetProperty("run").GetProperty("state").GetString());
    True(!report.GetProperty("run").TryGetProperty("session_id", out _), "private session leaked");
    var validations = report.GetProperty("validations");
    Equal(1, validations.GetArrayLength());
    True(!validations[0].TryGetProperty("token", out _), "private token leaked");
});

await RunAsync("workflow read model rejects remote management endpoints", async () =>
{
    using var http = new HttpClient(new StubHttpHandler(_ => Json("{}")));
    try
    {
        _ = new TunnelManagerReadModel(new Uri("http://example.com:19999/"), http);
        throw new InvalidOperationException("remote Router management endpoint accepted");
    }
    catch (ArgumentException)
    {
    }
    await Task.CompletedTask;
});

await RunAsync("ArcMap manifest exposes all 160 current tools", async () =>
{
    Equal(160, ArcMapAgentManifestFactory.KnownToolNames.Count);
    var required = new[]
    {
        "arcmap_goal_build_map",
        "arcmap_goal_cancel",
        "arcmap_goal_execute",
        "arcmap_goal_plan",
        "arcmap_goal_report",
        "arcmap_goal_resume",
        "arcmap_goal_status",
        "arcmap_goal_validate"
    };
    foreach (var tool in required)
    {
        True(
            ArcMapAgentManifestFactory.KnownToolNames.Contains(tool),
            "missing tool: " + tool);
    }

    var manifest = ArcMapAgentManifestFactory.Create(
        "3.0.1-zagent.1",
        "127.0.0.3",
        19040);
    Equal(160, manifest.Capabilities.Count);
    Equal(
        160,
        manifest.Capabilities
            .Select(item => item.Name)
            .Distinct(StringComparer.Ordinal)
            .Count());

    await Task.CompletedTask;
});

await RunAsync("ArcMap goal manifest classifies reads and controls fail-safe", async () =>
{
    var manifest = ArcMapAgentManifestFactory.Create(
        "3.0.1-zagent.1",
        "127.0.0.3",
        19040);

    foreach (var name in new[]
             {
                 "arcmap.goal_plan",
                 "arcmap.goal_validate",
                 "arcmap.goal_status",
                 "arcmap.goal_report"
             })
    {
        var capability = manifest.Capabilities.Single(item => item.Name == name);
        Equal(Zagent.Shared.Contracts.CapabilityAccess.Read, capability.Access);
        Equal(Zagent.Shared.Contracts.ResourcePolicy.ReadLock, capability.ResourcePolicy);
    }

    foreach (var name in new[]
             {
                 "arcmap.goal_build_map",
                 "arcmap.goal_execute",
                 "arcmap.goal_resume",
                 "arcmap.goal_cancel"
             })
    {
        var capability = manifest.Capabilities.Single(item => item.Name == name);
        Equal(Zagent.Shared.Contracts.CapabilityAccess.Admin, capability.Access);
        Equal(Zagent.Shared.Contracts.CapabilityApproval.Policy, capability.Approval);
        Equal(Zagent.Shared.Contracts.ResourcePolicy.Exclusive, capability.ResourcePolicy);
    }

    await Task.CompletedTask;
});

Console.WriteLine($"PASS={passed} FAIL={failed}");
return failed == 0 ? 0 : 1;

async Task RunAsync(string name, Func<Task> test)
{
    try
    {
        await test();
        passed++;
        Console.WriteLine("PASS " + name);
    }
    catch (Exception ex)
    {
        failed++;
        Console.WriteLine("FAIL " + name + ": " + ex.Message);
    }
}

void True(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

void Equal<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
        throw new InvalidOperationException($"expected={expected} actual={actual}");
}

HttpResponseMessage Json(string json) =>
    new(HttpStatusCode.OK)
    {
        Content = new StringContent(json, Encoding.UTF8, "application/json")
    };

sealed class StubHttpHandler(Func<HttpRequestMessage, HttpResponseMessage> handler) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken) =>
        Task.FromResult(handler(request));
}
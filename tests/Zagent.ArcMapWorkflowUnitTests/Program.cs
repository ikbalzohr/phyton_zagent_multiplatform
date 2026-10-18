using System.Net;
using System.Text;
using Zagent.Core.Manager;
using Zagent.Core.Agents.ArcMap;

var passed = 0;
var failed = 0;

await RunAsync("workflow snapshot is session-scoped and parsed", async () =>
{
    var handler = new StubHttpHandler(request =>
    {
        var uri = request.RequestUri ?? throw new InvalidOperationException();
        True(uri.AbsolutePath == "/router/workflows", "unexpected path");
        True(uri.Query.Contains("session_id=chat_a"), "session query missing");
        return Json("""
        {
          "ok": true,
          "session_id": "chat_a",
          "count": 1,
          "runs": [
            {
              "run_id": "run_1",
              "plan_id": "plan_1",
              "state": "RECONCILING",
              "strategy": "A_EXISTING_MXD",
              "task_id": "task_1",
              "request_id": "req_1",
              "trace_id": "trc_1",
              "repair_count": 2,
              "cancel_requested": false,
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
    var snapshot = await model.GetArcMapWorkflowsAsync("chat_a");
    Equal(1, snapshot.Count);
    Equal("run_1", snapshot.Runs[0].RunId);
    Equal("chat_a", snapshot.Runs[0].SessionId);
    Equal("RECONCILING", snapshot.Runs[0].State);
    Equal(2, snapshot.Runs[0].RepairCount);
});

await RunAsync("workflow evidence retains structured report", async () =>
{
    var handler = new StubHttpHandler(request =>
    {
        var uri = request.RequestUri ?? throw new InvalidOperationException();
        True(uri.AbsolutePath == "/router/workflows/run_1", "unexpected evidence path");
        True(uri.Query.Contains("session_id=chat_a"), "session query missing");
        return Json("""
        {
          "ok": true,
          "report": {
            "run": {"run_id":"run_1","state":"FAILED"},
            "validations":[{"status":"FAIL"}],
            "artifacts":[]
          }
        }
        """);
    });
    using var http = new HttpClient(handler);
    var model = new TunnelManagerReadModel(new Uri("http://127.0.0.3:19999/"), http);
    var evidence = await model.GetArcMapWorkflowEvidenceAsync("chat_a", "run_1");
    Equal("FAILED", evidence.State);
    True(evidence.Report.TryGetProperty("validations", out var values), "validation evidence missing");
    Equal(1, values.GetArrayLength());
});

await RunAsync("workflow read model refuses blank session", async () =>
{
    using var http = new HttpClient(new StubHttpHandler(_ => Json("{}")));
    var model = new TunnelManagerReadModel(new Uri("http://127.0.0.3:19999/"), http);
    try
    {
        await model.GetArcMapWorkflowsAsync("");
        throw new InvalidOperationException("blank session was accepted");
    }
    catch (ArgumentException)
    {
    }
});

await RunAsync("ArcMap manifest exposes all 132 current tools", async () =>
{
    Equal(132, ArcMapAgentManifestFactory.KnownToolNames.Count);
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
    Equal(132, manifest.Capabilities.Count);
    Equal(
        132,
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

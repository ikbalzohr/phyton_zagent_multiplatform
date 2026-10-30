using System.Text.Json;
using Zagent.Core.Diagnostics;

namespace Zagent.Core.Dashboard;

public sealed record DiagnosticProcessStatus(string Component, string State, string DesiredState, int? ProcessId, int? LastExitCode);
public sealed record DiagnosticRuntimeSnapshot(string CoreState, string BindHost, int RouterPort, int RouterHealthPort, int FilesPort, IReadOnlyList<DiagnosticProcessStatus> Processes);
public static class DashboardDiagnostics
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    public static async Task HandleRequestAsync(HttpContext context, RequestDelegate next, DiagnosticEventStore store)
    {
        // Never trust caller headers, Activity IDs or server trace strings as diagnostic correlation IDs.
        context.TraceIdentifier = Guid.NewGuid().ToString("N");
        try { await next(context); }
        catch (Exception) {
            store.Record("dashboard.request", "DASHBOARD_REQUEST_FAILED", "error", context.TraceIdentifier);
            if (context.Response.HasStarted) throw;
            context.Response.ContentLength = null;
            context.Response.Headers.CacheControl = "no-store";
            context.Response.StatusCode = 503;
            context.Response.ContentType = "application/json";
            await context.Response.WriteAsync(JsonSerializer.Serialize(new { code = "DEPENDENCY_UNAVAILABLE", requestId = context.TraceIdentifier }, Json));
        }
    }
    public static DiagnosticRuntimeSnapshot CaptureRuntime(Zagent.Core.Manager.ManagerCoreHostOptions options, Zagent.Core.Abstractions.IAgentSupervisor supervisor, bool stopping)
    {
        // Only fixed component identifiers and typed supervisor states; never LastError/arguments/paths.
        var known = new Dictionary<string, string>(StringComparer.Ordinal) {
            ["files.service"] = "files", ["system.tunnel.router"] = "router", ["system.tunnel.transport"] = "transport",
            ["web.service"] = "web", ["arcmap.mcp"] = "arcmap"
        };
        var processes = supervisor.Snapshot().Where(p => known.ContainsKey(p.AgentId))
            .Select(p => new DiagnosticProcessStatus(known[p.AgentId], p.State.ToString(), p.DesiredState.ToString(), p.ProcessId, p.LastExitCode)).ToArray();
        return new(stopping ? "stopping" : "running", options.BindHost, options.TunnelPort, options.TunnelHealthPort, options.FilesPort, processes);
    }
    public static void MapDiagnostics(this WebApplication app, DiagnosticEventStore store, Func<DiagnosticRuntimeSnapshot> snapshot)
    {
        const string route = "/api/management/v1/diagnostics";
        IResult Read(HttpContext ctx, bool export) {
            var query = ctx.Request.Query;
            if (query.Keys.Any(key => key is not ("limit" or "component" or "severity" or "requestId")) || query.Any(pair => pair.Value.Count != 1)) return Results.BadRequest(new { code = "INVALID_DIAGNOSTIC_FILTER" });
            int limit = 200;
            if (query.TryGetValue("limit", out var raw) && (!int.TryParse(raw, out limit) || limit is < 1 or > 500)) return Results.BadRequest(new { code = "INVALID_DIAGNOSTIC_FILTER" });
            string? Value(string key) => query.TryGetValue(key, out var value) ? value.ToString() : null;
            if (!DiagnosticEventStore.ValidFilters(Value("component"), Value("severity"), Value("requestId"))) return Results.BadRequest(new { code = "INVALID_DIAGNOSTIC_FILTER" });
            var report = store.Read(limit, Value("component"), Value("severity"), Value("requestId"));
            var result = new { version = 1, requestId = ctx.TraceIdentifier, report.CapturedAtUtc, report.Status, runtime = snapshot(), report.Sources, report.Events,
                coverage = "Core dashboard unhandled exceptions, Core lifecycle and supervisor start/unexpected-exit errors; Router/Files instrumented auth, initialization and dispatch boundaries. Not universal error capture. Missing or empty diagnostics do not establish health. No automatic remediation." };
            ctx.Response.Headers.CacheControl = "no-store";
            return export ? Results.File(JsonSerializer.SerializeToUtf8Bytes(result, Json), "application/json", "zagent-diagnostics.json") : Results.Ok(result);
        }
        app.MapGet(route, (HttpContext ctx) => Read(ctx, false)).RequireAuthorization("Administrator");
        app.MapGet(route + "/export", (HttpContext ctx) => Read(ctx, true)).RequireAuthorization("Administrator");
    }
}

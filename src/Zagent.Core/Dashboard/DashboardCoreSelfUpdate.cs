using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Http;
using Zagent.Core.Manager;
using Zagent.Shared.Manager;

namespace Zagent.Core.Dashboard;

/// <summary>
/// Owner-authenticated, out-of-process Core executable self-update handoff.
/// The independent Python worker is spawned BEFORE Core shutdown; the worker's
/// checkpoint and rollback live under the enrolled DataRoot, not a MCP receipt.
/// </summary>
public static class DashboardCoreSelfUpdate
{
    public sealed record CoreUpdateRequest(string UpdateId, string ExpectedPlan);

    public static void MapCoreSelfUpdate(this WebApplication app, ManagerCoreHost runtime, DashboardOptions options)
    {
        const string api = "/api/management/v1/core-updates";

        app.MapGet(api + "/{id}", (string id) => {
            if (!ValidId(id)) return Results.BadRequest();
            var result = Path.Combine(runtime.Options.DataRoot, "core-updates", "results", id + ".json");
            if (!File.Exists(result)) return Results.NotFound();
            try
            {
                var bytes = File.ReadAllBytes(result);
                if (bytes.Length is < 2 or > 16_384) return Results.StatusCode(503);
                using var parsed = JsonDocument.Parse(bytes);
                return Results.Ok(parsed.RootElement.Clone());
            }
            catch { return Results.StatusCode(503); }
        }).RequireAuthorization("Administrator");

        app.MapPost(api + "/apply", async (CoreUpdateRequest request, HttpContext ctx) => {
            if (!ValidId(request.UpdateId) || !ValidHash(request.ExpectedPlan))
                return Results.BadRequest(new { code = "UPDATE_REQUEST_INVALID" });

            var root = Path.GetFullPath(runtime.Options.ZagentRoot);
            var data = Path.GetFullPath(runtime.Options.DataRoot);
            var stage = Path.Combine(data, "core-updates", "staged", request.UpdateId);
            var planPath = Path.Combine(stage, "plan.json");
            var candidate = Path.Combine(stage, "Zagent.Core.exe");
            var core = Path.Combine(root, "Zagent.Core.exe");
            var manifest = Path.Combine(root, "payload-manifest.json");
            var launcher = Path.Combine(root, "Zagent.Launcher.exe");
            var python = Path.Combine(root, "agents", "tunnel", "runtime", "python", "python.exe");
            var worker = Path.Combine(root, "maintenance", "core_self_update.py");
            var status = Path.Combine(data, "core-updates", "results", request.UpdateId + ".json");
            var backup = Path.Combine(data, "core-updates", "backups", request.UpdateId);

            // Explicit installed-product and owner-staged-file preflight.
            if (!File.Exists(manifest) || !File.Exists(core) || !File.Exists(launcher) ||
                !File.Exists(python) || !File.Exists(worker) || !File.Exists(planPath) ||
                !File.Exists(candidate) || File.Exists(status) || Directory.Exists(backup) ||
                HasReparsePoint(stage) || HasReparsePoint(candidate) || HasReparsePoint(planPath))
                return Results.Conflict(new { code = "UPDATE_STAGING_OR_RUNTIME_INVALID" });

            try
            {
                var planBytes = await File.ReadAllBytesAsync(planPath, ctx.RequestAborted);
                if (planBytes.Length is < 20 or > 8192 ||
                    !string.Equals(Convert.ToHexString(SHA256.HashData(planBytes)),
                        request.ExpectedPlan, StringComparison.OrdinalIgnoreCase))
                    return Results.Conflict(new { code = "UPDATE_PLAN_CHANGED" });

                using var parsed = JsonDocument.Parse(planBytes);
                var plan = parsed.RootElement;
                if (plan.ValueKind != JsonValueKind.Object ||
                    plan.EnumerateObject().Count() != 6 ||
                    plan.GetProperty("schema").GetInt32() != 1 ||
                    plan.GetProperty("update_id").GetString() != request.UpdateId ||
                    !ValidHash(plan.GetProperty("old_sha256").GetString()) ||
                    !ValidHash(plan.GetProperty("new_sha256").GetString()) ||
                    !ValidHash(plan.GetProperty("old_manifest_sha256").GetString()) ||
                    plan.GetProperty("new_size").GetInt64() is < 1 or > 536_870_912L ||
                    new FileInfo(candidate).Length != plan.GetProperty("new_size").GetInt64() ||
                    !FileHashMatches(core, plan.GetProperty("old_sha256").GetString()!) ||
                    !FileHashMatches(candidate, plan.GetProperty("new_sha256").GetString()!) ||
                    !FileHashMatches(manifest, plan.GetProperty("old_manifest_sha256").GetString()!))
                    return Results.Conflict(new { code = "UPDATE_BASELINE_OR_SOURCE_MISMATCH" });
            }
            catch (Exception ex) when (ex is JsonException or InvalidDataException or IOException or UnauthorizedAccessException or KeyNotFoundException)
            {
                return Results.Conflict(new { code = "UPDATE_PLAN_MALFORMED" });
            }

            // Do not interrupt a durable job to update Core. Read Core's own
            // management snapshot; unknown status means fail closed.
            try
            {
                var response = await new ManagementReadCache(runtime.ControlService).ReadAsync(
                    "monitoring.snapshot", new ManagerRefreshRequest(true, 100), ctx.RequestAborted);
                if (!response.Success || response.Result is not { } snapshot ||
                    !snapshot.TryGetProperty("tasks", out var jobs))
                    return Results.StatusCode(503);
                foreach (var job in jobs.EnumerateArray())
                {
                    if (!job.TryGetProperty("state", out var state)) continue;
                    if (state.GetString() is "accepted" or "queued" or "running" or
                        "waiting_capacity" or "waiting_lock" or "cancelling" or "recovering")
                        return Results.Conflict(new { code = "CORE_UPDATE_ACTIVE_JOBS" });
                }
            }
            catch { return Results.StatusCode(503); }

            // Start the updater as an independent Windows owner process.
            // No cmd.exe, shell execution, global PATH or token forwarding.
            try
            {
                var process = new ProcessStartInfo(python) {
                    WorkingDirectory = root,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                foreach (var argument in new[] { worker, "worker", root, data, request.UpdateId,
                         request.ExpectedPlan, Environment.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture),
                         "--health-port", options.Origin.Port.ToString(System.Globalization.CultureInfo.InvariantCulture) })
                    process.ArgumentList.Add(argument);
                foreach (var key in process.Environment.Keys.ToArray())
                    if (key.StartsWith("ZAGENT_INTERNAL_", StringComparison.OrdinalIgnoreCase) ||
                        key.StartsWith("ZAGENT_PLUGIN_", StringComparison.OrdinalIgnoreCase))
                        process.Environment.Remove(key);
                using var child = Process.Start(process);
                if (child is null) return Results.StatusCode(503);
                var updaterPid = child.Id;
                runtime.ControlService.Logs.Write("INFO", "CoreUpdate", "core.update.accepted",
                    "updateId=" + request.UpdateId + " workerPid=" + updaterPid);
                ctx.Response.OnCompleted(() => {
                    runtime.ControlService.Shutdown.Request();
                    return Task.CompletedTask;
                });
                return Results.Accepted(api + "/" + request.UpdateId,
                    new { updateId = request.UpdateId, state = "worker_started", workerPid = updaterPid,
                          note = "Independent worker owns apply, restart and rollback after Core exits." });
            }
            catch { return Results.StatusCode(503); }
        }).RequireAuthorization("Administrator").RequireRateLimiting("commands");
    }

    private static bool ValidId(string? value) => value is not null &&
        Regex.IsMatch(value, @"\A[A-Za-z0-9_-]{8,60}\z", RegexOptions.CultureInvariant);
    private static bool ValidHash(string? value) => value is not null &&
        Regex.IsMatch(value, @"\A[a-fA-F0-9]{64}\z", RegexOptions.CultureInvariant);
    private static bool HasReparsePoint(string path) =>
        (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
    private static bool FileHashMatches(string path, string expected)
    {
        using var stream = File.OpenRead(path);
        return string.Equals(Convert.ToHexString(SHA256.HashData(stream)),
            expected, StringComparison.OrdinalIgnoreCase);
    }
}

using System.Security.Claims;
using System.Text.Json.Nodes;
using Zagent.Core.Manager;

namespace Zagent.Core.Dashboard;

/// <summary>Administrator session adapter; all state and CAS authority remain in Files.</summary>
public static class DashboardProfileAdministration
{
    public static void MapProfileAdministration(this WebApplication app, ManagerCoreHost runtime, DashboardOptions options,
        ManagementReadCache queries)
    {
        const string route = "/api/management/v1/workspaces";
        ProfileAdministrationClient Client() => InternalManagementChannel.CreateProfileAdministrationClient(
            new Uri($"http://{runtime.Options.BindHost}:{runtime.Options.FilesPort}/mcp"));
        app.MapGet(route, async (HttpContext ctx) => {
            try {
                using var client = Client();
                var catalog = await client.CatalogAsync(Actor(ctx), ctx.RequestAborted);
                var legacy = await queries.ReadAsync("profiles.snapshot", null, ctx.RequestAborted);
                var pending = legacy.Success && legacy.Result is { } result && result.TryGetProperty("pendingApprovals", out var approvals)
                    ? JsonNode.Parse(approvals.GetRawText()) : new JsonArray();
                // Membership/default is taken only from this authenticated backend snapshot. Legacy fallback
                // is explicit trusted static owner resource, never a browser-selected active profile.
                var defaultProfile = catalog["default_profile_id"]?.GetValue<string>();
                return Results.Ok(new { requestId = ctx.TraceIdentifier, data = new {
                    workspaceId = options.WorkspaceId, revision = catalog["revision"]?.GetValue<string>(),
                    profiles = catalog["profiles"], defaultProfile, pendingApprovals = pending,
                    capturedAtUtc = DateTimeOffset.UtcNow,
                    unavailableDependencies = legacy.Success ? Array.Empty<string>() : new[] { "Other agent approvals unavailable." }
                } });
            } catch (Exception ex) when (DependencyFailure(ex)) {
                return Results.Problem(statusCode: 503, title: "Trusted profile catalog unavailable; no local fallback.");
            }
        }).RequireAuthorization("Administrator");
        app.MapGet(route + "/profiles/{id}", async (string id, HttpContext ctx) => {
            try { using var client = Client(); return Results.Ok(await client.AdminAsync("get", new JsonObject { ["target_profile_id"] = id }, Actor(ctx), ctx.RequestAborted)); }
            catch (Exception ex) when (DependencyFailure(ex)) { return Results.Problem(statusCode: 503, title: "Trusted profile unavailable."); }
        }).RequireAuthorization("Administrator");
        app.MapPost(route + "/profiles", async (JsonObject request, HttpContext ctx) =>
            await Mutate("create", null, request, ctx, Client)).RequireAuthorization("Administrator").RequireRateLimiting("commands");
        app.MapPut(route + "/profiles/{id}", async (string id, JsonObject request, HttpContext ctx) =>
            await Mutate("update", id, request, ctx, Client)).RequireAuthorization("Administrator").RequireRateLimiting("commands");
        app.MapDelete(route + "/profiles/{id}", async (string id, [Microsoft.AspNetCore.Mvc.FromBody] JsonObject request, HttpContext ctx) =>
            await Mutate("delete", id, request, ctx, Client)).RequireAuthorization("Administrator").RequireRateLimiting("commands");
        app.MapPost(route + "/profiles/{id}/default", async (string id, JsonObject request, HttpContext ctx) =>
            await Mutate("set_default", id, request, ctx, Client)).RequireAuthorization("Administrator").RequireRateLimiting("commands");
    }
    private static string Actor(HttpContext ctx) => ctx.User.FindFirstValue(ClaimTypes.NameIdentifier)
        ?? throw new InvalidOperationException("Authenticated Administrator session actor required.");
    private static bool DependencyFailure(Exception ex) => ex is HttpRequestException or IOException or InvalidOperationException or
        System.Text.Json.JsonException or ArgumentException or KeyNotFoundException or UnauthorizedAccessException or TaskCanceledException;
    private static async Task<IResult> Mutate(string action, string? id, JsonObject request, HttpContext ctx,
        Func<ProfileAdministrationClient> clientFactory)
    {
        var revision = ctx.Request.Headers.IfMatch.ToString(); var key = ctx.Request.Headers["Idempotency-Key"].ToString();
        if (revision.Length != 64 || !revision.All(Uri.IsHexDigit)) return Results.StatusCode(428);
        if (string.IsNullOrWhiteSpace(key) || key.Length > 128) return Results.BadRequest(new { code = "IDEMPOTENCY_KEY_REQUIRED" });
        // Browser body contains domain selectors/values only. Unknown fields, including authority, fail closed.
        var allowed = action switch {
            "create" => new[] { "target_profile_id", "root", "mode", "enabled", "description" },
            "update" => new[] { "changes" }, "delete" => new[] { "replacement_default_id" }, _ => Array.Empty<string>()
        };
        if (request.Any(p => !allowed.Contains(p.Key, StringComparer.Ordinal) || p.Value is null)) return Results.BadRequest(new { code = "INVALID_PROFILE_FIELDS" });
        if (id is not null) request["target_profile_id"] = id;
        request["expected_revision"] = revision; request["idempotency_key"] = key;
        try {
            using var client = clientFactory();
            var outcome = await client.AdminAsync(action, request, Actor(ctx), ctx.RequestAborted);
            if (outcome["status"]?.GetValue<string>() != "committed" || outcome["access_sync"]?.GetValue<string>() != "committed")
                return Results.Problem(statusCode: 502, title: "Backend did not report a committed profile outcome.");
            return Results.Ok(outcome);
        } catch (ProfileAdministrationDeniedException ex) {
            return Results.Json(new { code = ex.Code, status = "rejected" }, statusCode:
                ex.Code is "REVISION_CONFLICT" or "IDEMPOTENCY_CONFLICT" ? 409 : 400);
        } catch (Exception ex) when (DependencyFailure(ex)) {
            // A lost response may follow a commit: expose uncertainty, not a fabricated failed/successful receipt.
            return Results.Problem(statusCode: 503, title: "Profile outcome unavailable. Retry only the same payload and idempotency key.");
        }
    }
}

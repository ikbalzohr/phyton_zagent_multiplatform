using System.Net;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Antiforgery;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Identity;
using Zagent.Core.Manager;
using Zagent.Shared;
using Zagent.Shared.Manager;

namespace Zagent.Core.Dashboard;

public static class DashboardHost
{
    public static async Task RunAsync(ManagerCoreHost runtime, DashboardOptions options, string configPath)
    {
        if (!OperatingSystem.IsWindows() || !Environment.UserInteractive)
            throw new InvalidOperationException("Core1 requires the interactive Windows owner session.");
        options.Validate();
        using var certificate = options.LoadCertificate();
        var builder = WebApplication.CreateBuilder(new WebApplicationOptions {
            Args = [], ContentRootPath = AppContext.BaseDirectory, WebRootPath = "wwwroot",
            ApplicationName = typeof(DashboardHost).Assembly.GetName().Name
        });
        builder.WebHost.ConfigureKestrel(server => {
            server.Limits.MaxRequestBodySize = 32 * 1024;
            server.Limits.RequestHeadersTimeout = TimeSpan.FromSeconds(15);
            server.Listen(IPAddress.Loopback, options.Origin.Port, listen => listen.UseHttps(certificate));
        });
        var scope = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Path.GetFullPath(runtime.Options.DataRoot))));
        builder.Services.AddDataProtection().SetApplicationName("Zagent.Core1.UI1." + scope)
            .PersistKeysToFileSystem(new DirectoryInfo(Path.Combine(runtime.Options.DataRoot, "dashboard-keys")))
            .ProtectKeysWithDpapi(protectToLocalMachine: false);
        builder.Services.AddSingleton(options);
        builder.Services.AddSingleton(runtime.ControlService);
        builder.Services.AddSingleton(new DashboardArtifacts(Path.Combine(runtime.Options.DataRoot, "visual")));
        builder.Services.AddSingleton(_ => new ManagementOperations(runtime.ControlService, runtime.Options.DataRoot));
        builder.Services.AddHostedService(sp => sp.GetRequiredService<ManagementOperations>());
        builder.Services.Configure<HostOptions>(host => host.ShutdownTimeout = TimeSpan.FromSeconds(45));
        builder.Services.AddAntiforgery(af => {
            af.HeaderName = "X-CSRF-TOKEN";
            af.Cookie.Name = "__Host-Zagent.Antiforgery";
            af.Cookie.SecurePolicy = CookieSecurePolicy.Always;
            af.Cookie.SameSite = SameSiteMode.Strict;
        });
        builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme).AddCookie(cookie => {
            cookie.Cookie.Name = "__Host-Zagent.Dashboard";
            cookie.Cookie.HttpOnly = true; cookie.Cookie.SecurePolicy = CookieSecurePolicy.Always;
            cookie.Cookie.SameSite = SameSiteMode.Strict; cookie.Cookie.Path = "/";
            cookie.ExpireTimeSpan = TimeSpan.FromMinutes(20); cookie.SlidingExpiration = false;
            cookie.LoginPath = "/Login";
            cookie.Events.OnRedirectToLogin = ctx => {
                if (ctx.Request.Path.StartsWithSegments("/api")) ctx.Response.StatusCode = 401;
                else ctx.Response.Redirect("/Login");
                return Task.CompletedTask;
            };
            cookie.Events.OnRedirectToAccessDenied = ctx => { ctx.Response.StatusCode = 403; return Task.CompletedTask; };
            cookie.Events.OnValidatePrincipal = async ctx => {
                try {
                    var current = DashboardOptions.Load(configPath);
                    if (ctx.Principal?.FindFirstValue("security_stamp") != current.SecurityStamp ||
                        current.PasswordHash != options.PasswordHash || current.Administrator != options.Administrator)
                        ctx.RejectPrincipal();
                } catch { ctx.RejectPrincipal(); }
                if (ctx.Principal?.Identity?.IsAuthenticated != true) await ctx.HttpContext.SignOutAsync();
            };
        });
        builder.Services.AddAuthorization(auth => {
            auth.FallbackPolicy = new AuthorizationPolicyBuilder().RequireAuthenticatedUser().Build();
            auth.AddPolicy("Operator", p => p.RequireRole("Operator", "Administrator"));
            auth.AddPolicy("Administrator", p => p.RequireRole("Administrator"));
        });
        builder.Services.AddRazorPages(pages => pages.Conventions.AllowAnonymousToPage("/Login"));
        builder.Services.AddRateLimiter(limits => {
            limits.RejectionStatusCode = 429;
            limits.AddPolicy("login", _ => RateLimitPartition.GetFixedWindowLimiter("local-login", _ =>
                new FixedWindowRateLimiterOptions { PermitLimit = 5, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
            limits.AddPolicy("commands", _ => RateLimitPartition.GetFixedWindowLimiter("local-commands", _ =>
                new FixedWindowRateLimiterOptions { PermitLimit = 30, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
        });
        await using var app = builder.Build();
        runtime.ShutdownRequested += (_, _) => _ = app.StopAsync();
        app.Use(async (ctx, next) => {
            ctx.Response.Headers.CacheControl = "no-store";
            ctx.Response.Headers.ContentSecurityPolicy = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'";
            ctx.Response.Headers.XContentTypeOptions = "nosniff";
            ctx.Response.Headers.XFrameOptions = "DENY";
            if (!ctx.Request.IsHttps || !DashboardSecurity.IsExpectedHost(ctx.Request.Host.Value ?? "", options.Origin) ||
                ctx.Connection.RemoteIpAddress is not { } address || !IPAddress.IsLoopback(address)) {
                ctx.Response.StatusCode = 403; return;
            }
            try { await next(); }
            catch (Exception) when (!ctx.Response.HasStarted) {
                ctx.Response.StatusCode = 503;
                await ctx.Response.WriteAsJsonAsync(new { code = "DEPENDENCY_UNAVAILABLE", requestId = ctx.TraceIdentifier });
            }
        });
        // No forwarded-headers/CORS middleware: neither proxy identity nor cross-origin access is trusted.
        app.UseRouting(); app.UseRateLimiter(); app.UseAuthentication(); app.UseAuthorization();
        app.Use(async (ctx, next) => {
            if (ctx.Request.Method is not ("GET" or "HEAD" or "OPTIONS")) {
                if (!DashboardSecurity.IsSameOrigin(ctx.Request.Headers.Origin.ToString(), options.Origin)) {
                    ctx.Response.StatusCode = 403; return;
                }
                try { await ctx.RequestServices.GetRequiredService<IAntiforgery>().ValidateRequestAsync(ctx); }
                catch (AntiforgeryValidationException) { ctx.Response.StatusCode = 400; return; }
            }
            await next();
        });
        app.UseStaticFiles(new StaticFileOptions { OnPrepareResponse = ctx => ctx.Context.Response.Headers.CacheControl = "no-store" });
        app.MapRazorPages();
        // Login needs this single public stylesheet before a session exists. Keep
        // all other static files and management routes behind fallback authorization.
        app.MapMethods("/dashboard.css", ["GET", "HEAD"], () => Results.File(
            Path.Combine(app.Environment.WebRootPath, "dashboard.css"), contentType: "text/css")).AllowAnonymous();
        app.MapPost("/auth/login", async (HttpContext ctx) => {
            var form = await ctx.Request.ReadFormAsync();
            var name = form["account"].ToString(); var password = form["password"].ToString();
            // Always perform the password hash check, including unknown account names.
            var verified = password.Length <= 256 && new PasswordHasher<string>().VerifyHashedPassword(
                options.Administrator, options.PasswordHash, password) != PasswordVerificationResult.Failed;
            if (!verified || !string.Equals(name, options.Administrator, StringComparison.Ordinal))
                return Results.Redirect("/Login?failed=1");
            var stamp = options.SecurityStamp;
            var claims = new[] { new Claim(ClaimTypes.NameIdentifier, options.Administrator),
                new Claim(ClaimTypes.Name, options.Administrator), new Claim(ClaimTypes.Role, "Administrator"),
                new Claim("security_stamp", stamp) };
            await ctx.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
                new ClaimsPrincipal(new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme)),
                new AuthenticationProperties { IsPersistent = false, AllowRefresh = false });
            return Results.Redirect("/");
        }).AllowAnonymous().RequireRateLimiting("login");
        app.MapPost("/auth/logout", async (HttpContext ctx) => {
            await ctx.SignOutAsync(); return Results.Ok(new { signedOut = true });
        }).RequireAuthorization();
        MapManagement(app, runtime, options);
        // Only this process owns runtime. Browser unload/disconnect has no shutdown handler.
        await app.RunAsync();
    }

    private static void MapManagement(WebApplication app, ManagerCoreHost runtime, DashboardOptions options)
    {
        const string api = "/api/management/v1";
        var control = runtime.ControlService;
        var queries = new ManagementReadCache(control);
        app.MapGet(api + "/csrf", (HttpContext ctx, IAntiforgery af) =>
            Results.Ok(new { token = af.GetAndStoreTokens(ctx).RequestToken })).RequireAuthorization();
        foreach (var (path, method) in new[] { ("overview", "manager.dashboard"), ("agents", "manager.dashboard"),
            ("capabilities", "registry.capabilities"), ("connections", "integrations.snapshot"),
            ("routes", "router.snapshot"), ("workspaces", "profiles.snapshot"), ("jobs", "monitoring.snapshot") })
        {
            app.MapGet(api + "/" + path, async (HttpContext ctx) => {
                var response = await queries.ReadAsync(method, method == "monitoring.snapshot" ? new ManagerRefreshRequest(true, 100) : null, ctx.RequestAborted);
                if (!response.Success || response.Result is not { } data) return Results.Problem(statusCode: 503, title: "Dependency unavailable");
                object projection = data;
                if (path == "agents") projection = data.GetProperty("agents");
                if (path == "jobs") projection = new {
                    tasks = data.GetProperty("tasks").EnumerateArray().Select(t => new {
                        taskId = t.GetProperty("taskId"), principalId = t.GetProperty("principalId"), workspaceId = t.GetProperty("workspaceId"), requestId = t.GetProperty("requestId"), agent = t.GetProperty("agent"),
                        tool = t.GetProperty("tool"), state = t.GetProperty("state"), progress = t.GetProperty("progress"),
                        canStop = t.GetProperty("canStop"), stopMode = t.GetProperty("stopMode") }).ToArray(),
                    queueDepth = data.GetProperty("queueDepth"), capturedAtUtc = data.GetProperty("capturedAtUtc") };
                if (path == "workspaces") projection = new { workspaceId = options.WorkspaceId,
                    revision = DashboardRevision.Profiles(data), profiles = data.GetProperty("profiles"), defaultProfile = data.GetProperty("defaultProfile"),
                    pendingApprovals = data.GetProperty("pendingApprovals"), capturedAtUtc = data.GetProperty("capturedAtUtc"),
                    unavailableDependencies = data.GetProperty("unavailableDependencies").EnumerateArray().Select(x => x.GetString() ?? "").ToArray() };
                return Results.Ok(new { requestId = ctx.TraceIdentifier, capturedAtUtc = DateTimeOffset.UtcNow, data = projection });
            }).RequireAuthorization();
        }
        var visualReader = new ManagerVisualReadModel(Path.Combine(runtime.Options.DataRoot, "visual"));
        app.MapGet(api + "/visuals", async (HttpContext ctx) =>
            Results.Ok(await visualReader.GetLatestAsync(ctx.User.Identity?.Name, options.WorkspaceId, ctx.RequestAborted))).RequireAuthorization();
        var tunnel = new TunnelManagerReadModel(new Uri($"http://{runtime.Options.BindHost}:{runtime.Options.TunnelPort}/"));
        app.MapGet(api + "/workflows", async (string principalId, HttpContext ctx) => {
            if (!ValidPrincipal(principalId)) return Results.BadRequest();
            try { return Results.Ok(await DashboardWorkflowRead.ReadAsync(tunnel, principalId, options.WorkspaceId, null, ctx.RequestAborted)); }
            catch (Exception) when (!ctx.Response.HasStarted) { return Results.StatusCode(503); }
        }).RequireAuthorization("Administrator");
        app.MapGet(api + "/workflows/{id}/evidence", async (string id, string principalId, HttpContext ctx) => {
            if (!ValidPrincipal(principalId) || !ValidPrincipal(id)) return Results.BadRequest();
            try { return Results.Ok(await DashboardWorkflowRead.ReadAsync(tunnel, principalId, options.WorkspaceId, id, ctx.RequestAborted)); }
            catch (Exception) when (!ctx.Response.HasStarted) { return Results.StatusCode(503); }
        }).RequireAuthorization("Administrator");
        app.MapGet(api + "/logs", async (HttpContext ctx) => {
            var response = await queries.ReadAsync("logs.snapshot", null, ctx.RequestAborted);
            if (!response.Success || response.Result is not { } data) return Results.StatusCode(503);
            var snapshot = data.Deserialize<ManagerLogsSnapshot>(ManagerJson.Options)!;
            return Results.Ok(new { capturedAtUtc = snapshot.CapturedAtUtc, technical = snapshot.Technical.TakeLast(200)
                .Select(log => log with { Message = DashboardSecurity.Redact(log.Message) }) });
        }).RequireAuthorization("Administrator");
        app.MapGet(api + "/settings", async (HttpContext ctx) => {
            var settings = await queries.ReadAsync("settings.tunnel.snapshot", null, ctx.RequestAborted);
            return Results.Ok(new { coreVersion = ZagentProductInfo.CoreVersion, uiVersion = ZagentProductInfo.UiVersion,
                workspaceId = options.WorkspaceId, managementOrigin = options.Origin.GetLeftPart(UriPartial.Authority), remoteEnabled = false,
                account = ctx.User.Identity!.Name, role = "Administrator", credentialChanges = "Offline provisioning only; restart required",
                tunnel = settings.Success ? settings.Result : null });
        }).RequireAuthorization("Administrator");
        app.MapGet(api + "/artifacts", async (DashboardArtifacts artifacts, HttpContext ctx) =>
            Results.Ok(await artifacts.LatestAsync(options.WorkspaceId, ctx.RequestAborted))).RequireAuthorization();
        app.MapGet(api + "/artifacts/{id}/content", async (string id, DashboardArtifacts artifacts, HttpContext ctx) => {
            var content = await artifacts.ReadAsync(id, options.WorkspaceId, ctx.RequestAborted);
            return content is null ? Results.NotFound() : Results.File(content.Bytes, content.MimeType, content.FileName);
        }).RequireAuthorization();
        app.MapGet(api + "/operations/{id}", (string id, ManagementOperations operations, HttpContext ctx) => {
            var op = operations.Get(id, ctx.User.FindFirstValue(ClaimTypes.NameIdentifier)!);
            return op is null ? Results.NotFound() : Results.Ok(op);
        }).RequireAuthorization();
        app.MapPost(api + "/agents/{agentId}/actions", async (string agentId, DashboardAgentAction action, HttpContext ctx, ManagementOperations operations) => {
            if (action.Operation is not ("start" or "stop" or "restart" or "refresh")) return Results.BadRequest();
            return await Accept(operations, ctx, "lifecycle.agent", new ManagerLifecycleRequest(agentId, action.Operation));
        }).RequireAuthorization("Operator").RequireRateLimiting("commands");
        app.MapPost(api + "/runtime/actions", async (DashboardAgentAction action, HttpContext ctx, ManagementOperations operations) => {
            if (action.Operation is not ("startAll" or "stopAll")) return Results.BadRequest();
            return await Accept(operations, ctx, "lifecycle.all", new ManagerLifecycleRequest("", action.Operation == "startAll" ? "start" : "stop"));
        }).RequireAuthorization("Operator").RequireRateLimiting("commands");
        app.MapPost(api + "/runtime/shutdown", (DashboardShutdown request, HttpContext ctx) => {
            if (request.Confirmation != "STOP CORE") return Results.BadRequest();
            control.Logs.Write("INFO", "ManagementAudit", "system.shutdown", "actor=" + ctx.User.FindFirstValue(ClaimTypes.NameIdentifier));
            ctx.Response.OnCompleted(() => { control.Shutdown.Request(); return Task.CompletedTask; });
            return Results.Accepted(value: new { state = "accepted", message = "Core shutdown acknowledged. Use the Windows shortcut to start it again." });
        }).RequireAuthorization("Administrator").RequireRateLimiting("commands");
        app.MapPost(api + "/jobs/{id}/cancel", async (string id, HttpContext ctx, ManagementOperations operations) =>
            await Accept(operations, ctx, "task.cancel", new ManagerTaskCancelRequest(id)))
            .RequireAuthorization("Operator").RequireRateLimiting("commands");
        app.MapPost(api + "/workspaces/profiles", async (ManagerProfileAddRequest request, HttpContext ctx, ManagementOperations operations) =>
            await Accept(operations, ctx, "profiles.add", request)).RequireAuthorization("Administrator").RequireRateLimiting("commands");
        app.MapPut(api + "/workspaces/profiles/{id}", async (string id, ManagerProfileUpdateRequest request, HttpContext ctx, ManagementOperations operations) =>
            id != request.Name ? Results.BadRequest() : await Accept(operations, ctx, "profiles.update", request))
            .RequireAuthorization("Administrator").RequireRateLimiting("commands");
        app.MapDelete(api + "/workspaces/profiles/{id}", async (string id, HttpContext ctx, ManagementOperations operations) =>
            await Accept(operations, ctx, "profiles.remove", new ManagerProfileRemoveRequest(id)))
            .RequireAuthorization("Administrator").RequireRateLimiting("commands");
        app.MapPost(api + "/approvals/{id}/decision", async (string id, ManagerApprovalActionRequest request, HttpContext ctx, ManagementOperations operations) => {
            if (id != request.RequestId || request.Source != "Files" || request.Action is not ("approve" or "deny")) return Results.BadRequest();
            return await Accept(operations, ctx, "approval.resolve", request);
        }).RequireAuthorization("Administrator").RequireRateLimiting("commands");
        app.MapPost(api + "/connections/actions", async (ManagerIntegrationActionRequest request, HttpContext ctx, ManagementOperations operations) => {
            if (request.Action is not ("chrome.check" or "arcmap.check")) return Results.BadRequest();
            return await Accept(operations, ctx, "integrations.action", request);
        }).RequireAuthorization("Operator").RequireRateLimiting("commands");
    }
    private static bool ValidPrincipal(string value) => value.Length is > 0 and <= 256 &&
        value.All(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_' or '.' or ':');
    private static Task<ManagerResponseEnvelope> Query(ManagerControlService control, string method, object? payload, CancellationToken token) =>
        control.HandleAsync(new ManagerRequestEnvelope(ManagerProtocol.Version, Guid.NewGuid().ToString("N"), method,
            payload is null ? null : ManagerJson.ToElement(payload)), token);
    private static async Task<IResult> Accept(ManagementOperations operations, HttpContext ctx, string method, object? payload)
    {
        try {
            var requiresRevision = method.StartsWith("profiles.", StringComparison.Ordinal) || method == "approval.resolve";
            var revision = ctx.Request.Headers.IfMatch.ToString();
            if (requiresRevision && (revision.Length != 64 || !revision.All(Uri.IsHexDigit)))
                return Results.Problem(statusCode: 428, title: "Refresh workspace snapshot; If-Match revision is required.");
            var op = await operations.EnqueueAsync(ctx.User.FindFirstValue(ClaimTypes.NameIdentifier)!, ctx.Request.Headers["Idempotency-Key"].ToString(), method, payload,
                requiresRevision ? revision : null);
            return Results.Accepted("/api/management/v1/operations/" + op.OperationId, op);
        } catch (ArgumentException) { return Results.BadRequest(new { code = "INVALID_COMMAND" }); }
        catch (InvalidOperationException) { return Results.Conflict(new { code = "COMMAND_CONFLICT_OR_CAPACITY" }); }
    }
}
public sealed record DashboardAgentAction(string Operation);
public sealed record DashboardShutdown(string Confirmation);

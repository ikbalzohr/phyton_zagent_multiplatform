using System.Net;
using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Antiforgery;
using Microsoft.AspNetCore.DataProtection;
using Zagent.Core.Dashboard;

// Explicit request/identity fixture; does NOT boot Core, emulate Windows, or validate ACL/DPAPI.
static void Check(bool value, string name) { if (!value) throw new Exception(name); }
var builder = WebApplication.CreateBuilder();
var services = builder.Services;
services.AddLogging();
services.AddDataProtection().UseEphemeralDataProtectionProvider();
services.AddAntiforgery(a => { a.HeaderName = "X-CSRF-TOKEN"; a.Cookie.Name = "__Host-Fixture.Csrf"; a.Cookie.SecurePolicy = CookieSecurePolicy.Always; });
services.AddSingleton(new DashboardOptions("https://localhost:19443/", "fixture", "fixture", "legacy-admin", "unused", "unused"));
services.AddSingleton(new DashboardOwnerIdentity("S-1-5-21-100-200-300-1001", "fixture-owner"));
services.AddAuthentication(DashboardOwnerAuthenticationHandler.SchemeName)
    .AddScheme<AuthenticationSchemeOptions, DashboardOwnerAuthenticationHandler>(DashboardOwnerAuthenticationHandler.SchemeName, _ => { });
services.AddAuthorization(a => a.AddPolicy("Administrator", p => p.RequireRole("Administrator")));
await using var app = builder.Build();
var provider = app.Services;
async Task<AuthenticateResult> Authenticate(Action<DefaultHttpContext>? change = null) {
    var ctx = new DefaultHttpContext { RequestServices = provider };
    ctx.Request.Scheme = "https"; ctx.Request.Host = new HostString("localhost", 19443);
    ctx.Connection.RemoteIpAddress = IPAddress.Loopback;
    change?.Invoke(ctx);
    // Scoped handler provider per request, as in the production pipeline.
    await using var scope = provider.CreateAsyncScope(); ctx.RequestServices = scope.ServiceProvider;
    return await ctx.AuthenticateAsync();
}
var owner = await Authenticate();
Check(owner.Succeeded, "local HTTPS request authenticates with no password/cookie");
Check(owner.Principal!.FindFirstValue(ClaimTypes.NameIdentifier) == "S-1-5-21-100-200-300-1001", "actor is captured Windows SID, not provisioned login");
Check(owner.Principal!.Identity!.Name == "fixture-owner", "real owner name is retained");
var authorization = provider.GetRequiredService<IAuthorizationService>();
Check((await authorization.AuthorizeAsync(owner.Principal, null, "Administrator")).Succeeded, "owner satisfies protected Administrator policy");
Check(!(await authorization.AuthorizeAsync(new ClaimsPrincipal(new ClaimsIdentity()), null, "Administrator")).Succeeded, "anonymous cannot satisfy policy");
var rejected = new (string, Action<DefaultHttpContext>)[] {
    ("http", c => c.Request.Scheme = "http"),
    ("remote", c => c.Connection.RemoteIpAddress = IPAddress.Parse("192.0.2.1")),
    ("missing peer", c => c.Connection.RemoteIpAddress = null),
    ("wrong host", c => c.Request.Host = new HostString("evil.example", 19443)),
    ("wrong port", c => c.Request.Host = new HostString("localhost", 19444)),
    ("cross origin", c => c.Request.Headers.Origin = "https://evil.example"),
    ("null origin", c => c.Request.Headers.Origin = "null"),
    ("cross site", c => c.Request.Headers["Sec-Fetch-Site"] = "cross-site"),
    ("same site other origin", c => c.Request.Headers["Sec-Fetch-Site"] = "same-site")
};
foreach (var (name, change) in rejected) Check(!(await Authenticate(change)).Succeeded, "reject " + name);
Check((await Authenticate(c => { c.Request.Headers.Origin = "https://localhost:19443"; c.Request.Headers["Sec-Fetch-Site"] = "same-origin"; })).Succeeded, "same origin allowed");
await using (var scope = provider.CreateAsyncScope()) {
    var af = scope.ServiceProvider.GetRequiredService<IAntiforgery>();
    var issue = new DefaultHttpContext { RequestServices = scope.ServiceProvider, User = owner.Principal! };
    issue.Request.Scheme = "https"; issue.Request.Host = new HostString("localhost", 19443);
    var tokens = af.GetAndStoreTokens(issue);
    var mutate = new DefaultHttpContext { RequestServices = scope.ServiceProvider, User = owner.Principal! };
    mutate.Request.Method = "POST"; mutate.Request.Scheme = "https";
    mutate.Request.Host = new HostString("localhost", 19443);
    Check(!await af.IsRequestValidAsync(mutate), "owner authentication does not bypass CSRF");
    mutate.Request.Headers.Cookie = "__Host-Fixture.Csrf=" + tokens.CookieToken;
    mutate.Request.Headers["X-CSRF-TOKEN"] = tokens.RequestToken;
    await af.ValidateRequestAsync(mutate);
}
if (!OperatingSystem.IsWindows()) {
    try { DashboardOwnerIdentity.Capture(".", "."); throw new Exception("Linux owner capture accepted"); }
    catch (PlatformNotSupportedException) { }
}
Console.WriteLine("PASS: owner authentication, SID actor, protected policy, HTTPS/host/peer/origin/fetch rejection; Windows ACL/DPAPI/browser NOT_TESTED.");

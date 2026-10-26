using System.Net;
using System.Security.Claims;
using System.Security.Principal;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Options;
using Zagent.Core.Manager;

namespace Zagent.Core.Dashboard;

/// <summary>
/// Process owner, not a browser-supplied account. Loopback HTTP does not identify the
/// connecting Windows user: other local users/processes can access this dashboard.
/// This intentionally trusts the local machine, not a Windows multi-user boundary.
/// </summary>
public sealed record DashboardOwnerIdentity(string Sid, string Name)
{
    public static DashboardOwnerIdentity Capture(string dataRoot, string configPath)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("Dashboard owner authentication requires Windows.");
        if (!Environment.UserInteractive)
            throw new InvalidOperationException("Dashboard requires the interactive Windows owner session.");
        InternalSecretStore.ValidatePrivatePath(dataRoot, directory: true);
        InternalSecretStore.ValidatePrivatePath(configPath, directory: false);
        using var identity = WindowsIdentity.GetCurrent();
        var sid = identity.User?.Value;
        if (!identity.IsAuthenticated || identity.IsSystem || string.IsNullOrWhiteSpace(sid) || string.IsNullOrWhiteSpace(identity.Name))
            throw new InvalidOperationException("Authenticated interactive Windows owner identity is unavailable.");
        return new(sid, identity.Name);
    }
}

/// <summary>Dashboard-only scheme; never registered on the MCP/OAuth transport.</summary>
public sealed class DashboardOwnerAuthenticationHandler(
    IOptionsMonitor<AuthenticationSchemeOptions> schemes, ILoggerFactory logger,
    UrlEncoder encoder, DashboardOptions dashboard, DashboardOwnerIdentity owner)
    : AuthenticationHandler<AuthenticationSchemeOptions>(schemes, logger, encoder)
{
    public const string SchemeName = "DashboardLocalOwner";

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        // Recheck the network boundary here as well as in the outer host middleware.
        // Never trust forwarded headers, cookies, account form fields or bearer tokens.
        var origin = Request.Headers.Origin;
        var fetchSite = Request.Headers["Sec-Fetch-Site"];
        if (!Request.IsHttps || !DashboardSecurity.IsExpectedHost(Request.Host.Value ?? "", dashboard.Origin) ||
            Context.Connection.RemoteIpAddress is not { } address || !IPAddress.IsLoopback(address) ||
            (origin.Count != 0 && !DashboardSecurity.IsSameOrigin(origin.ToString(), dashboard.Origin)) ||
            (fetchSite.Count != 0 && fetchSite.ToString() is not ("none" or "same-origin")) ||
            string.IsNullOrWhiteSpace(owner.Sid) || string.IsNullOrWhiteSpace(owner.Name))
            return Task.FromResult(AuthenticateResult.Fail("Local owner dashboard boundary required."));
        var identity = new ClaimsIdentity([
            new Claim(ClaimTypes.NameIdentifier, owner.Sid),
            new Claim(ClaimTypes.Name, owner.Name),
            new Claim(ClaimTypes.Role, "Administrator")
        ], SchemeName);
        return Task.FromResult(AuthenticateResult.Success(new AuthenticationTicket(new ClaimsPrincipal(identity), SchemeName)));
    }
}

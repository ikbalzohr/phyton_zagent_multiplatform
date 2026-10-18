using Zagent.Shared.Installation;

namespace Zagent.Core.Network;

public sealed record ZagentPortProfile(
    string InstallationRole,
    int ProductionStart, int ProductionEnd,
    int Core, int Tunnel, int TunnelHealth, int Files, int Web, int ArcMap,
    int DevelopmentGatewayStart, int DevelopmentGatewayEnd,
    int DevRuntimeStart, int DevRuntimeEnd);

public static class ZagentNetworkPolicy
{
    public const string DefaultBindHost = "127.0.0.3";

    // Legacy Master constants retained for source compatibility.
    public const int CorePort = 18800;
    public const int TunnelPort = 18810;
    public const int TunnelHealthPort = 18811;
    public const int FilesPort = 18820;
    public const int WebPort = 18830;
    public const int ArcMapPort = 18840;
    public const int ProductionPortStart = 18800;
    public const int ProductionPortEnd = 18899;
    public const int DevelopmentPortStart = 18900;
    public const int DevelopmentPortEnd = 18999;

    public static ZagentPortProfile For(string? role) =>
        ZagentInstallationProfile.Normalize(role) switch
        {
            ZagentInstallationProfile.User => new(
                ZagentInstallationProfile.User,
                19100, 19199, 19100, 19110, 19111, 19120, 19130, 19140,
                19200, 19299, 19300, 19399),
            _ => new(
                ZagentInstallationProfile.Master,
                18800, 18899, 18800, 18810, 18811, 18820, 18830, 18840,
                18900, 18999, 19000, 19099)
        };

    public static bool IsDevelopmentPort(int port) =>
        port >= DevelopmentPortStart && port <= DevelopmentPortEnd;

    public static bool IsDevelopmentPort(int port, string? role)
    {
        var profile = For(role);
        return port >= profile.DevelopmentGatewayStart &&
               port <= profile.DevelopmentGatewayEnd;
    }
}

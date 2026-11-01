namespace Zagent.Core.Network;

public sealed record ZagentPortProfile(
    int ProductionStart, int ProductionEnd,
    int Core, int Tunnel, int TunnelHealth, int Files, int Web, int ArcMap,
    int DevelopmentGatewayStart, int DevelopmentGatewayEnd,
    int DevRuntimeStart, int DevRuntimeEnd);

public static class ZagentNetworkPolicy
{
    public const string DefaultBindHost = "127.0.0.3";
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

    // All new installations use one neutral port policy. Port availability is
    // checked when generating configuration; no operator or client role selects ports.
    public static ZagentPortProfile For() => new(
        18800, 18899, 18800, 18810, 18811, 18820, 18830, 18840,
        18900, 18999, 19000, 19099);

    public static bool IsDevelopmentPort(int port) =>
        port >= DevelopmentPortStart && port <= DevelopmentPortEnd;

    // Read-only compatibility with existing machine configs. These numeric
    // blocks do not confer a client/installation role or authorization.
    public static bool IsSupportedPortBlock(
        IReadOnlyList<int> productionPorts, int gatewayStart, int gatewayEnd)
    {
        if (gatewayEnd != gatewayStart + 99 ||
            gatewayStart is not (18900 or 19200))
            return false;
        var productionStart = gatewayStart - 100;
        return productionPorts.All(port =>
            port >= productionStart && port <= productionStart + 99);
    }
}

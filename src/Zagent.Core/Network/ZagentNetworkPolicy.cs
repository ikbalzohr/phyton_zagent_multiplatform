namespace Zagent.Core.Network;

public sealed record ZagentPortProfile(
    int ProductionStart, int ProductionEnd,
    int Core, int Tunnel, int TunnelHealth, int Files, int Web, int ArcMap,
    int DevelopmentGatewayStart, int DevelopmentGatewayEnd,
    int DevRuntimeStart, int DevRuntimeEnd);

public static class ZagentNetworkPolicy
{
    public const string DefaultBindHost = "127.0.0.3";
    // Multi Platform defaults are isolated from the separately installed
    // Zagent Production 188xx and 189xx ranges.
    public const int CorePort = 19100;
    public const int TunnelPort = 19110;
    public const int TunnelHealthPort = 19111;
    public const int FilesPort = 19120;
    public const int WebPort = 19130;
    public const int ArcMapPort = 19140;
    public const int QgisPort = 19150;
    public const int ProductionPortStart = 19100;
    public const int ProductionPortEnd = 19199;
    public const int DevelopmentPortStart = 19200;
    public const int DevelopmentPortEnd = 19299;

    // Fresh installs allocate within Multi Platform's independent range.
    // Existing deployments keep their persisted, externally routed ports.
    public static ZagentPortProfile For() => new(
        ProductionPortStart, ProductionPortEnd, CorePort, TunnelPort,
        TunnelHealthPort, FilesPort, WebPort, ArcMapPort,
        DevelopmentPortStart, DevelopmentPortEnd, 19300, 19399);

    public static bool IsDevelopmentPort(int port) =>
        port >= DevelopmentPortStart && port <= DevelopmentPortEnd;

    // Preserve the installed 188xx service endpoints without touching the
    // Cloudflare MCP route. An old Multi Platform machine configuration may
    // retain its unique 188xx service ports while moving its dev gateway to
    // 192xx. Fresh installations use the fully isolated 191xx + 192xx block.
    public static bool IsSupportedPortBlock(
        IReadOnlyList<int> productionPorts, int gatewayStart, int gatewayEnd)
    {
        if (gatewayEnd != gatewayStart + 99)
            return false;
        var validRange = gatewayStart switch
        {
            18900 => 18800, // Previously persisted 188xx installation.
            19200 when productionPorts.All(port => port is >= 18800 and <= 18899)
                => 18800, // Non-disruptive migration of existing installation.
            19200 => 19100,
            _ => -1
        };
        return validRange > 0 && productionPorts.All(port =>
            port >= validRange && port <= validRange + 99);
    }
}

using System.Net;
using System.Net.Sockets;
using Zagent.Shared.Configuration;

namespace Zagent.Core.Network;

public sealed class ZagentPortAllocator
{
    private readonly Func<string, int, bool> _isPortAvailable;

    public ZagentPortAllocator(
        Func<string, int, bool>? isPortAvailable = null)
    {
        _isPortAvailable = isPortAvailable ?? IsTcpPortAvailable;
    }

    public ZagentMachineConfiguration Allocate(
        ZagentMachineConfiguration preferred)
    {
        ArgumentNullException.ThrowIfNull(preferred);

        var used = new HashSet<int>();
        var range = ZagentNetworkPolicy.For(preferred.InstallationRole);

        var core = AllocateOne(
            preferred.BindHost,
            preferred.CorePort,
            used,
            range);
        var tunnel = AllocateOne(
            preferred.BindHost,
            preferred.TunnelPort,
            used,
            range);
        var tunnelHealth = AllocateOne(
            preferred.BindHost,
            preferred.TunnelHealthPort,
            used,
            range);
        var files = AllocateOne(
            preferred.BindHost,
            preferred.FilesPort,
            used,
            range);
        var web = AllocateOne(
            preferred.BindHost,
            preferred.WebPort,
            used,
            range);
        var arcMap = AllocateOne(
            preferred.BindHost,
            preferred.ArcMapPort,
            used,
            range);

        return preferred with
        {
            CorePort = core,
            TunnelPort = tunnel,
            TunnelHealthPort = tunnelHealth,
            FilesPort = files,
            WebPort = web,
            ArcMapPort = arcMap
        };
    }

    private int AllocateOne(
        string host,
        int preferred,
        HashSet<int> used,
        ZagentPortProfile range)
    {
        foreach (var candidate in Candidates(preferred, range))
        {
            if (used.Contains(candidate))
            {
                continue;
            }

            if (!_isPortAvailable(host, candidate))
            {
                continue;
            }

            used.Add(candidate);
            return candidate;
        }

        throw new InvalidOperationException(
            $"No free Zagent production port is available in " +
            $"{range.ProductionStart}-{range.ProductionEnd} ({range.InstallationRole}).");
    }

    private static IEnumerable<int> Candidates(int preferred, ZagentPortProfile range)
    {
        // Retain the legacy forward-first allocation order, but never cross
        // the installation role's reserved production port range.
        if (preferred >= range.ProductionStart && preferred <= range.ProductionEnd)
        {
            yield return preferred;
            for (var port = preferred + 1; port <= range.ProductionEnd; port++)
                yield return port;
            for (var port = range.ProductionStart; port < preferred; port++)
                yield return port;
        }
        else
        {
            for (var port = range.ProductionStart; port <= range.ProductionEnd; port++)
                yield return port;
        }
    }

    private static bool IsTcpPortAvailable(
        string host,
        int port)
    {
        IPAddress address;
        if (string.Equals(
                host,
                "localhost",
                StringComparison.OrdinalIgnoreCase))
        {
            address = IPAddress.Loopback;
        }
        else if (!IPAddress.TryParse(host, out address!))
        {
            return false;
        }

        TcpListener? listener = null;

        try
        {
            listener = new TcpListener(address, port);
            listener.Server.ExclusiveAddressUse = true;
            listener.Start();
            return true;
        }
        catch (SocketException)
        {
            return false;
        }
        finally
        {
            try
            {
                listener?.Stop();
            }
            catch
            {
            }
        }
    }
}
using System.Collections.Concurrent;

namespace Zagent.Core.Supervision;

internal sealed class SupervisorInstanceLease : IDisposable
{
    public const string DefaultName =
        "Local\\ZohrSystemAgent.Zagent.v2.Supervisor";

    private static readonly ConcurrentDictionary<string, byte> LocalLeases =
        new(StringComparer.Ordinal);

    private readonly string _name;
    private readonly Semaphore _semaphore;
    private int _disposed;

    private SupervisorInstanceLease(
        string name,
        Semaphore semaphore)
    {
        _name = name;
        _semaphore = semaphore;
    }

    public static bool TryAcquire(
        string name,
        out SupervisorInstanceLease? lease)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        lease = null;

        if (!LocalLeases.TryAdd(name, 0))
        {
            return false;
        }

        Semaphore? semaphore = null;
        try
        {
            semaphore = new Semaphore(
                initialCount: 1,
                maximumCount: 1,
                name);

            if (!semaphore.WaitOne(0))
            {
                semaphore.Dispose();
                LocalLeases.TryRemove(name, out _);
                return false;
            }

            lease = new SupervisorInstanceLease(
                name,
                semaphore);
            semaphore = null;
            return true;
        }
        catch
        {
            semaphore?.Dispose();
            LocalLeases.TryRemove(name, out _);
            throw;
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        try
        {
            _semaphore.Release();
        }
        finally
        {
            _semaphore.Dispose();
            LocalLeases.TryRemove(_name, out _);
        }
    }
}

namespace Zagent.Core.Manager;

/// <summary>One shutdown signal shared by private HTTP and maintenance adapters.</summary>
public sealed class CoreShutdownCoordinator
{
    private int _requested;
    public bool IsRequested => Volatile.Read(ref _requested) != 0;
    public event EventHandler? ShutdownRequested;
    public void Request()
    {
        if (Interlocked.Exchange(ref _requested, 1) == 0)
            ShutdownRequested?.Invoke(this, EventArgs.Empty);
    }
}

/// <summary>Serializes domain mutations across ALL adapters, not just per agent slots.</summary>
public sealed class CoreCommandGate
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    private int _stopping;
    public void BeginShutdown() => Interlocked.Exchange(ref _stopping, 1);
    public async ValueTask<IAsyncDisposable> EnterAsync(CancellationToken token = default)
    {
        await _gate.WaitAsync(token);
        if (Volatile.Read(ref _stopping) != 0)
        {
            _gate.Release();
            throw new InvalidOperationException("Core is shutting down.");
        }
        return new Lease(_gate);
    }
    public async ValueTask<IAsyncDisposable> DrainAsync()
    {
        BeginShutdown();
        await _gate.WaitAsync();
        return new Lease(_gate);
    }
    private sealed class Lease(SemaphoreSlim gate) : IAsyncDisposable
    {
        public ValueTask DisposeAsync() { gate.Release(); return ValueTask.CompletedTask; }
    }
}

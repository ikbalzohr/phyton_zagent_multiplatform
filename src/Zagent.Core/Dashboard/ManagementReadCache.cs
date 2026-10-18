using System.Collections.Concurrent;
using System.Text.Json;
using Zagent.Core.Manager;
using Zagent.Shared.Manager;

namespace Zagent.Core.Dashboard;

/// <summary>Coalesces polling tabs without binding shared probes to any one browser connection.</summary>
public sealed class ManagementReadCache(ManagerControlService control)
{
    private sealed record Entry(DateTimeOffset Until, Task<ManagerResponseEnvelope> Task);
    private readonly ConcurrentDictionary<string, Entry> _entries = new();
    private readonly object _sync = new();
    public async Task<ManagerResponseEnvelope> ReadAsync(string method, object? payload, CancellationToken browserToken)
    {
        var key = method + JsonSerializer.Serialize(payload);
        Task<ManagerResponseEnvelope> task;
        lock (_sync) {
            if (!_entries.TryGetValue(key, out var entry) || entry.Until < DateTimeOffset.UtcNow && entry.Task.IsCompleted) {
                entry = new Entry(DateTimeOffset.UtcNow.AddSeconds(2), ProbeAsync(method, payload));
                _entries[key] = entry;
            }
            task = entry.Task;
        }
        return await task.WaitAsync(browserToken);
    }
    private async Task<ManagerResponseEnvelope> ProbeAsync(string method, object? payload)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(12));
        return await control.HandleAsync(new ManagerRequestEnvelope(ManagerProtocol.Version, Guid.NewGuid().ToString("N"), method,
            payload is null ? null : ManagerJson.ToElement(payload)), timeout.Token);
    }
}

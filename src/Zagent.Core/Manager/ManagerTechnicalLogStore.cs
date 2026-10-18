using System.Collections.Concurrent;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed class ManagerTechnicalLogStore
{
    private readonly ConcurrentQueue<ManagerTechnicalLogRow> _rows = new();
    private readonly int _capacity;

    public ManagerTechnicalLogStore(int capacity = 1000)
    {
        if (capacity < 100)
        {
            throw new ArgumentOutOfRangeException(nameof(capacity));
        }

        _capacity = capacity;
    }

    public void Write(
        string level,
        string source,
        string eventName,
        string message)
    {
        _rows.Enqueue(
            new ManagerTechnicalLogRow(
                DateTimeOffset.UtcNow,
                level,
                source,
                eventName,
                message));

        while (_rows.Count > _capacity &&
               _rows.TryDequeue(out _))
        {
        }
    }

    public IReadOnlyList<ManagerTechnicalLogRow> Snapshot(
        int limit = 300) =>
        _rows
            .Reverse()
            .Take(Math.Clamp(limit, 1, _capacity))
            .ToArray();
}

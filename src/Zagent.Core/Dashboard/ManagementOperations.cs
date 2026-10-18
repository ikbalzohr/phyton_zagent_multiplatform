using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using Zagent.Core.Manager;
using Zagent.Shared.Manager;

namespace Zagent.Core.Dashboard;

public sealed record ManagementOperation(string OperationId, string ActorId, string Method, string PayloadHash,
    string IdempotencyKey, string State, DateTimeOffset UpdatedAtUtc, string? ExpectedRevision = null);

/// <summary>Bounded command queue; disconnect never cancels domain work. Restart marks unresolved outcomes unknown.</summary>
public sealed class ManagementOperations : BackgroundService
{
    private sealed record Command(ManagementOperation Operation, object? Payload);
    private readonly Channel<Command> _queue = Channel.CreateBounded<Command>(new BoundedChannelOptions(32) { SingleReader = true, FullMode = BoundedChannelFullMode.Wait });
    private readonly ConcurrentDictionary<string, ManagementOperation> _operations = new();
    private readonly SemaphoreSlim _accept = new(1, 1);
    private readonly ManagerControlService _service;
    private readonly string _root;
    public ManagementOperations(ManagerControlService service, string dataRoot)
    {
        _service = service; _root = Path.Combine(dataRoot, "management-operations");
        Directory.CreateDirectory(_root);
        foreach (var file in Directory.EnumerateFiles(_root, "*.json"))
        {
            var op = JsonSerializer.Deserialize<ManagementOperation>(File.ReadAllText(file))
                ?? throw new InvalidDataException("Invalid management journal; reconcile before restart.");
            if (!Guid.TryParseExact(op.OperationId, "N", out _) || Path.GetFileNameWithoutExtension(file) != op.OperationId)
                throw new InvalidDataException("Invalid operation journal identifier.");
            if (op.State is "accepted" or "running") op = op with { State = "unknown", UpdatedAtUtc = DateTimeOffset.UtcNow };
            _operations[op.OperationId] = op;
            Persist(op);
        }
    }
    public ManagementOperation? Get(string id, string actor) =>
        _operations.TryGetValue(id, out var op) && op.ActorId == actor ? op : null;
    public async Task<ManagementOperation> EnqueueAsync(string actor, string key, string method, object? payload, string? revision = null)
    {
        if (string.IsNullOrWhiteSpace(key) || key.Length > 128) throw new ArgumentException("Idempotency-Key is required.");
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(method + "\n" + revision + "\n" + JsonSerializer.Serialize(payload))));
        await _accept.WaitAsync();
        try {
            if (_service.Shutdown.IsRequested) throw new InvalidOperationException("Core is stopping.");
            var prior = _operations.Values.FirstOrDefault(x => x.ActorId == actor && x.IdempotencyKey == key);
            if (prior is not null) {
                if (prior.PayloadHash != hash) throw new InvalidOperationException("Idempotency conflict.");
                return prior;
            }
            // Fail closed rather than evicting idempotency history without an explicit retention policy.
            if (_operations.Count >= 10000) throw new InvalidOperationException("Journal capacity reached; offline archive required.");
            var operation = new ManagementOperation(Guid.NewGuid().ToString("N"), actor, method, hash, key, "accepted", DateTimeOffset.UtcNow, revision);
            Persist(operation); _operations[operation.OperationId] = operation;
            if (!_queue.Writer.TryWrite(new Command(operation, payload))) {
                Update(operation, "failed"); throw new InvalidOperationException("Command queue is full.");
            }
            return operation;
        } finally { _accept.Release(); }
    }
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        try {
            await foreach (var item in _queue.Reader.ReadAllAsync(stoppingToken)) {
                var op = item.Operation; Update(op, "running");
                try {
                    // This token is host lifetime, NEVER the browser request-aborted token.
                    var response = await _service.HandleAsync(new ManagerRequestEnvelope(
                        ManagerProtocol.Version, op.OperationId, op.Method,
                        item.Payload is null ? null : ManagerJson.ToElement(item.Payload)), stoppingToken, op.ExpectedRevision);
                    var ok = response.Success && !(response.Result is { } result &&
                        result.TryGetProperty("success", out var success) && success.ValueKind == JsonValueKind.False);
                    Update(op, ok ? "succeeded" : response.Error == "REVISION_CONFLICT" ? "conflict" : response.Success ? "failed" : "unknown");
                    _service.Logs.Write("INFO", "ManagementAudit", op.Method,
                        $"actor={op.ActorId} operation={op.OperationId} outcome={(ok ? "succeeded" : "failed")}");
                } catch (OperationCanceledException) { Update(op, "unknown"); }
                catch { Update(op, "unknown"); }
            }
        } catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
    }
    private void Update(ManagementOperation op, string state)
    {
        op = op with { State = state, UpdatedAtUtc = DateTimeOffset.UtcNow };
        Persist(op); _operations[op.OperationId] = op;
    }
    private void Persist(ManagementOperation op)
    {
        var path = Path.Combine(_root, op.OperationId + ".json");
        var temp = path + ".new";
        using (var stream = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None)) {
            JsonSerializer.Serialize(stream, op); stream.Flush(true);
        }
        File.Move(temp, path, overwrite: true);
    }
}

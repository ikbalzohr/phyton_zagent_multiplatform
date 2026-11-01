using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using Zagent.Shared.Manager;

/// <summary>
/// Minimal test-only client for the Core's named-pipe management protocol.
/// Not a desktop manager or a production UI component.
/// </summary>
internal sealed class ManagerPipeTestClient
{
    private readonly string _pipeName;

    public ManagerPipeTestClient(string pipeName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(pipeName);
        _pipeName = pipeName;
    }

    public async Task<T> SendAsync<T>(
        string method,
        object? parameters = null,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(method);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        linked.CancelAfter(timeout ?? TimeSpan.FromSeconds(8));

        await using var pipe = new NamedPipeClientStream(
            ".", _pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        await pipe.ConnectAsync(linked.Token);

        using var reader = new StreamReader(pipe, new UTF8Encoding(false),
            detectEncodingFromByteOrderMarks: false, bufferSize: 16 * 1024, leaveOpen: true);
        using var writer = new StreamWriter(pipe, new UTF8Encoding(false),
            bufferSize: 16 * 1024, leaveOpen: true) { AutoFlush = true };

        var request = new ManagerRequestEnvelope(
            ManagerProtocol.Version, Guid.NewGuid().ToString("N"),
            method, parameters is null ? null : ManagerJson.ToElement(parameters));
        await writer.WriteLineAsync(
            JsonSerializer.Serialize(request, ManagerJson.Options).AsMemory(), linked.Token);

        var responseLine = await reader.ReadLineAsync(linked.Token);
        if (string.IsNullOrWhiteSpace(responseLine))
            throw new IOException("Core closed the test management pipe without a response.");
        var response = JsonSerializer.Deserialize<ManagerResponseEnvelope>(
            responseLine, ManagerJson.Options) ??
            throw new InvalidDataException("Core test management response is JSON null.");
        if (!response.Success)
            throw new InvalidOperationException(response.Error ?? "Core management test call failed.");
        if (response.Result is null)
            throw new InvalidDataException("Core management test method returned no result.");
        return response.Result.Value.Deserialize<T>(ManagerJson.Options) ??
            throw new InvalidDataException("Core management test method returned JSON null.");
    }

    public async Task RequestShutdownAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            await SendAsync<ManagerOperationResult>("system.shutdown",
                timeout: TimeSpan.FromSeconds(2), cancellationToken: cancellationToken);
        }
        catch
        {
            // Shutdown can terminate the pipe before its result arrives.
        }
    }
}

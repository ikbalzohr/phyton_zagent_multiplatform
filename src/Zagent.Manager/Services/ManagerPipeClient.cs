using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using Zagent.Shared.Manager;

namespace Zagent.Manager.Services;

public sealed class ManagerPipeClient
{
    private readonly string _pipeName;

    public ManagerPipeClient(
        string pipeName = ManagerProtocol.DefaultPipeName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(pipeName);
        _pipeName = pipeName;
    }

    public string PipeName => _pipeName;

    public async Task<bool> IsAvailableAsync(
        CancellationToken cancellationToken = default)
    {
        try
        {
            await SendAsync<ManagerDashboardSnapshot>(
                "manager.dashboard",
                parameters: null,
                timeout: TimeSpan.FromMilliseconds(500),
                cancellationToken);
            return true;
        }
        catch
        {
            return false;
        }
    }

    public async Task<T> SendAsync<T>(
        string method,
        object? parameters = null,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(method);

        using var linked =
            CancellationTokenSource.CreateLinkedTokenSource(
                cancellationToken);

        linked.CancelAfter(
            timeout ?? TimeSpan.FromSeconds(8));

        await using var pipe = new NamedPipeClientStream(
            ".",
            _pipeName,
            PipeDirection.InOut,
            PipeOptions.Asynchronous);

        await pipe.ConnectAsync(linked.Token);

        using var reader = new StreamReader(
            pipe,
            new UTF8Encoding(false),
            detectEncodingFromByteOrderMarks: false,
            bufferSize: 16 * 1024,
            leaveOpen: true);

        using var writer = new StreamWriter(
            pipe,
            new UTF8Encoding(false),
            bufferSize: 16 * 1024,
            leaveOpen: true)
        {
            AutoFlush = true
        };

        var request = new ManagerRequestEnvelope(
            ManagerProtocol.Version,
            Guid.NewGuid().ToString("N"),
            method,
            parameters is null
                ? null
                : ManagerJson.ToElement(parameters));

        await writer.WriteLineAsync(
            JsonSerializer.Serialize(
                request,
                ManagerJson.Options)
                .AsMemory(),
            linked.Token);

        var line = await reader.ReadLineAsync(
            linked.Token);

        if (string.IsNullOrWhiteSpace(line))
        {
            throw new IOException(
                "Zagent Core closed the Manager pipe without a response.");
        }

        var response =
            JsonSerializer.Deserialize<
                ManagerResponseEnvelope>(
                line,
                ManagerJson.Options) ??
            throw new InvalidDataException(
                "Manager pipe response is JSON null.");

        if (!response.Success)
        {
            throw new InvalidOperationException(
                response.Error ??
                $"Manager method '{method}' failed.");
        }

        if (response.Result is null)
        {
            throw new InvalidDataException(
                $"Manager method '{method}' returned no result.");
        }

        return response.Result.Value.Deserialize<T>(
                   ManagerJson.Options) ??
               throw new InvalidDataException(
                   $"Manager method '{method}' returned JSON null.");
    }

    public async Task RequestShutdownAsync(
        CancellationToken cancellationToken = default)
    {
        try
        {
            await SendAsync<ManagerOperationResult>(
                "system.shutdown",
                timeout: TimeSpan.FromSeconds(2),
                cancellationToken: cancellationToken);
        }
        catch
        {
        }
    }
}
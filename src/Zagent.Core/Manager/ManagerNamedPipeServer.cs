using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed class ManagerNamedPipeServer : IAsyncDisposable
{
    private readonly string _pipeName;
    private readonly ManagerControlService _service;
    private readonly CancellationTokenSource _stop = new();
    private Task? _loop;
    private int _disposed;

    public ManagerNamedPipeServer(
        ManagerControlService service,
        string pipeName = ManagerProtocol.DefaultPipeName)
    {
        _service = service ??
            throw new ArgumentNullException(nameof(service));
        ArgumentException.ThrowIfNullOrWhiteSpace(pipeName);
        _pipeName = pipeName;
    }

    public event EventHandler? ShutdownRequested;

    public string PipeName => _pipeName;

    public void Start()
    {
        ObjectDisposedException.ThrowIf(
            Volatile.Read(ref _disposed) != 0,
            this);

        if (_loop is not null)
        {
            throw new InvalidOperationException(
                "Manager pipe server is already running.");
        }

        _loop = Task.Run(
            () => RunAsync(_stop.Token));
    }

    public async Task StopAsync()
    {
        if (_loop is null)
        {
            return;
        }

        _stop.Cancel();

        try
        {
            await _loop;
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            _loop = null;
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(
                ref _disposed,
                1) != 0)
        {
            return;
        }

        await StopAsync();
        _stop.Dispose();
    }

    private async Task RunAsync(
        CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var server = new NamedPipeServerStream(
                _pipeName,
                PipeDirection.InOut,
                NamedPipeServerStream.MaxAllowedServerInstances,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous |
                PipeOptions.CurrentUserOnly);

            try
            {
                await server.WaitForConnectionAsync(
                    cancellationToken);

                _ = HandleClientAsync(
                    server,
                    cancellationToken);
            }
            catch
            {
                await server.DisposeAsync();
                throw;
            }
        }
    }

    private async Task HandleClientAsync(
        NamedPipeServerStream stream,
        CancellationToken serverToken)
    {
        await using var ownedStream = stream;

        try
        {
            using var reader = new StreamReader(
                stream,
                new UTF8Encoding(false),
                detectEncodingFromByteOrderMarks: false,
                bufferSize: 16 * 1024,
                leaveOpen: true);

            using var writer = new StreamWriter(
                stream,
                new UTF8Encoding(false),
                bufferSize: 16 * 1024,
                leaveOpen: true)
            {
                AutoFlush = true
            };

            var line = await reader.ReadLineAsync(
                serverToken);

            if (string.IsNullOrWhiteSpace(line))
            {
                return;
            }

            ManagerResponseEnvelope response;
            ManagerRequestEnvelope? request = null;

            try
            {
                request = JsonSerializer.Deserialize<
                    ManagerRequestEnvelope>(
                    line,
                    ManagerJson.Options);

                if (request is null)
                {
                    throw new InvalidDataException(
                        "Manager request is JSON null.");
                }

                response = await _service.HandleAsync(
                    request,
                    serverToken);
            }
            catch (Exception ex)
            {
                response = new ManagerResponseEnvelope(
                    ManagerProtocol.Version,
                    request?.RequestId ?? "",
                    false,
                    null,
                    ex.Message);
            }

            await writer.WriteLineAsync(
                JsonSerializer.Serialize(
                    response,
                    ManagerJson.Options)
                    .AsMemory(),
                serverToken);

            if (request?.Method == "system.shutdown" &&
                response.Success)
            {
                _service.Shutdown.Request();
                ShutdownRequested?.Invoke(this, EventArgs.Empty);
            }
        }
        catch (OperationCanceledException)
            when (serverToken.IsCancellationRequested)
        {
        }
        catch (IOException)
        {
        }
    }
}

using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Zagent.Core.Configuration;

public sealed class AtomicJsonFileStore
{
    private static readonly JsonSerializerOptions SerializerOptions = CreateOptions();
    private static readonly ConcurrentDictionary<string, SemaphoreSlim> WriteLocks =
        new(StringComparer.OrdinalIgnoreCase);

    public async Task SaveAsync<T>(
        string path,
        T value,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArgumentNullException.ThrowIfNull(value);

        var fullPath = Path.GetFullPath(path);
        var directory = Path.GetDirectoryName(fullPath)
            ?? throw new ArgumentException(
                "Configuration path must have a parent directory.",
                nameof(path));

        Directory.CreateDirectory(directory);

        var writeLock = WriteLocks.GetOrAdd(
            fullPath,
            static _ => new SemaphoreSlim(1, 1));

        await writeLock.WaitAsync(cancellationToken);
        try
        {
            var fileName = Path.GetFileName(fullPath);
            var tempPath = Path.Combine(
                directory,
                $".{fileName}.{Guid.NewGuid():N}.tmp");

            try
            {
                await using (var stream = new FileStream(
                    tempPath,
                    FileMode.CreateNew,
                    FileAccess.Write,
                    FileShare.None,
                    bufferSize: 64 * 1024,
                    options: FileOptions.Asynchronous | FileOptions.WriteThrough))
                {
                    await JsonSerializer.SerializeAsync(
                        stream,
                        value,
                        SerializerOptions,
                        cancellationToken);

                    await stream.FlushAsync(cancellationToken);
                }

                if (File.Exists(fullPath))
                {
                    File.Copy(fullPath, fullPath + ".bak", overwrite: true);
                }

                File.Move(tempPath, fullPath, overwrite: true);
            }
            finally
            {
                if (File.Exists(tempPath))
                {
                    File.Delete(tempPath);
                }
            }
        }
        finally
        {
            writeLock.Release();
        }
    }

    public async Task<T> LoadAsync<T>(
        string path,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);

        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
        {
            throw new FileNotFoundException(
                "Configuration file was not found.",
                fullPath);
        }

        try
        {
            await using var stream = new FileStream(
                fullPath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                bufferSize: 64 * 1024,
                options: FileOptions.Asynchronous | FileOptions.SequentialScan);

            var value = await JsonSerializer.DeserializeAsync<T>(
                stream,
                SerializerOptions,
                cancellationToken);

            return value
                ?? throw new InvalidDataException(
                    $"Configuration '{fullPath}' contained JSON null.");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException(
                $"Configuration '{fullPath}' contains invalid JSON.",
                ex);
        }
    }

    public bool Exists(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return File.Exists(Path.GetFullPath(path));
    }

    private static JsonSerializerOptions CreateOptions()
    {
        var options = new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            PropertyNameCaseInsensitive = true
        };

        options.Converters.Add(new JsonStringEnumConverter());
        return options;
    }
}

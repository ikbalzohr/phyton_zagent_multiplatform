using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Zagent.Core.Abstractions;
using Zagent.Core.Configuration;
using Zagent.Core.Supervision;

namespace Zagent.Core.Agents.Files;

public sealed record FilesUpdateProcessResult(
    bool Success,
    string RequestId,
    string Action,
    string UpdateId,
    string? Error = null);

public sealed class FilesUpdateRequestProcessor
{
    private readonly IAgentSupervisor _supervisor;
    private readonly AtomicJsonFileStore _store;

    public FilesUpdateRequestProcessor(
        IAgentSupervisor supervisor,
        AtomicJsonFileStore? store = null)
    {
        _supervisor = supervisor
            ?? throw new ArgumentNullException(nameof(supervisor));
        _store = store ?? new AtomicJsonFileStore();
    }

    public async Task<IReadOnlyList<FilesUpdateProcessResult>> ProcessPendingAsync(
        FilesIntegrationOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        var requestRoot = Path.Combine(
            options.UpdateStateRoot,
            "requests");

        if (!Directory.Exists(requestRoot))
        {
            return Array.Empty<FilesUpdateProcessResult>();
        }

        var results = new List<FilesUpdateProcessResult>();

        foreach (var requestFile in Directory
            .EnumerateFiles(requestRoot, "*.json")
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            cancellationToken.ThrowIfCancellationRequested();

            JsonObject? request;
            try
            {
                request = JsonNode.Parse(
                    await File.ReadAllTextAsync(
                        requestFile,
                        cancellationToken)) as JsonObject;
            }
            catch
            {
                continue;
            }

            if (request is null ||
                !string.Equals(
                    request["status"]?.GetValue<string>(),
                    "pending_core",
                    StringComparison.Ordinal))
            {
                continue;
            }

            results.Add(
                await ProcessRequestAsync(
                    options,
                    requestFile,
                    cancellationToken));
        }

        return results;
    }

    public async Task<FilesUpdateProcessResult> ProcessRequestAsync(
        FilesIntegrationOptions options,
        string requestFile,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);
        ArgumentException.ThrowIfNullOrWhiteSpace(requestFile);

        var requestPath = Path.GetFullPath(requestFile);
        var request = JsonNode.Parse(
                await File.ReadAllTextAsync(
                    requestPath,
                    cancellationToken)) as JsonObject
            ?? throw new InvalidDataException(
                "Files update request must be a JSON object.");

        var requestId =
            request["request_id"]?.GetValue<string>()
            ?? throw new InvalidDataException(
                "Files update request_id is required.");
        var action =
            request["action"]?.GetValue<string>()
            ?? throw new InvalidDataException(
                "Files update action is required.");
        var updateId =
            request["update_id"]?.GetValue<string>()
            ?? throw new InvalidDataException(
                "Files update_id is required.");

        ValidateIdentity(
            options,
            request);

        var wasRunning =
            _supervisor.TryGetSnapshot(
                FilesProcessFactory.ProcessId,
                out var snapshot) &&
            snapshot is not null &&
            snapshot.DesiredState == DesiredProcessState.Running;

        try
        {
            request["status"] = "processing";
            request["processing_at"] =
                DateTimeOffset.UtcNow.ToString("O");
            await SaveJsonNodeAsync(
                requestPath,
                request,
                cancellationToken);

            if (wasRunning)
            {
                var stop = await _supervisor.StopAsync(
                    FilesProcessFactory.ProcessId,
                    cancellationToken);

                if (!stop.Success)
                {
                    throw new InvalidOperationException(
                        "Unable to stop Files service for update: " +
                        stop.Message);
                }
            }

            switch (action)
            {
                case "apply":
                    await ApplyAsync(
                        options,
                        updateId,
                        cancellationToken);
                    break;

                case "rollback":
                    await RollbackAsync(
                        options,
                        updateId,
                        cancellationToken);
                    break;

                default:
                    throw new InvalidDataException(
                        $"Unsupported Files update action '{action}'.");
            }

            request["status"] = "completed";
            request["completed_at"] =
                DateTimeOffset.UtcNow.ToString("O");
            request["error"] = null;

            await SaveJsonNodeAsync(
                requestPath,
                request,
                cancellationToken);

            await WriteResultAsync(
                options,
                new JsonObject
                {
                    ["ok"] = true,
                    ["request_id"] = requestId,
                    ["action"] = action,
                    ["update_id"] = updateId,
                    ["time"] =
                        DateTimeOffset.UtcNow.ToString("O")
                },
                cancellationToken);

            if (wasRunning)
            {
                var start = await _supervisor.StartAsync(
                    FilesProcessFactory.ProcessId,
                    cancellationToken);

                if (!start.Success)
                {
                    throw new InvalidOperationException(
                        "Files update applied but restart failed: " +
                        start.Message);
                }
            }

            return new FilesUpdateProcessResult(
                true,
                requestId,
                action,
                updateId);
        }
        catch (Exception ex)
        {
            request["status"] = "failed";
            request["failed_at"] =
                DateTimeOffset.UtcNow.ToString("O");
            request["error"] = ex.Message;

            await SaveJsonNodeAsync(
                requestPath,
                request,
                cancellationToken);

            await WriteResultAsync(
                options,
                new JsonObject
                {
                    ["ok"] = false,
                    ["request_id"] = requestId,
                    ["action"] = action,
                    ["update_id"] = updateId,
                    ["time"] =
                        DateTimeOffset.UtcNow.ToString("O"),
                    ["error"] = ex.Message
                },
                cancellationToken);

            if (wasRunning &&
                _supervisor.TryGetSnapshot(
                    FilesProcessFactory.ProcessId,
                    out var current) &&
                current is not null &&
                current.State == AgentProcessState.Stopped)
            {
                _ = await _supervisor.StartAsync(
                    FilesProcessFactory.ProcessId,
                    CancellationToken.None);
            }

            return new FilesUpdateProcessResult(
                false,
                requestId,
                action,
                updateId,
                ex.Message);
        }
    }

    private async Task ApplyAsync(
        FilesIntegrationOptions options,
        string updateId,
        CancellationToken cancellationToken)
    {
        ValidateUpdateId(updateId);

        var stageRoot = Path.Combine(
            options.UpdateStateRoot,
            "staging",
            updateId);
        var metadataPath = Path.Combine(
            stageRoot,
            "metadata.json");

        var metadata = JsonNode.Parse(
                await File.ReadAllTextAsync(
                    metadataPath,
                    cancellationToken)) as JsonObject
            ?? throw new InvalidDataException(
                "Files update metadata must be an object.");

        if (metadata["validated"]?.GetValue<bool>() != true)
        {
            throw new InvalidDataException(
                "Files update has not been validated.");
        }

        var files =
            metadata["files"] as JsonObject
            ?? new JsonObject();
        var deletes =
            metadata["deletes"] as JsonArray
            ?? new JsonArray();

        var relativePaths = files
            .Select(pair => pair.Key)
            .Concat(
                deletes
                    .Select(node => node?.GetValue<string>())
                    .Where(value => !string.IsNullOrWhiteSpace(value))
                    .Select(value => value!))
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        await CreateBackupAsync(
            options,
            updateId,
            relativePaths,
            cancellationToken);

        foreach (var pair in files)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var relativePath = ValidateRelativePath(pair.Key);
            var spec = pair.Value as JsonObject
                ?? throw new InvalidDataException(
                    $"Update spec is invalid for '{pair.Key}'.");

            var stagedPath = Path.Combine(
                stageRoot,
                "files",
                relativePath);
            var targetPath = Path.Combine(
                options.EngineRoot,
                relativePath);

            if (!File.Exists(stagedPath))
            {
                throw new FileNotFoundException(
                    "Staged update file was not found.",
                    stagedPath);
            }

            var expectedSha =
                spec["sha256"]?.GetValue<string>() ?? "";
            var actualSha =
                await ComputeSha256Async(
                    stagedPath,
                    cancellationToken);

            if (!string.Equals(
                    expectedSha,
                    actualSha,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    $"SHA-256 mismatch for '{pair.Key}'.");
            }

            Directory.CreateDirectory(
                Path.GetDirectoryName(targetPath)
                ?? options.EngineRoot);

            var tempTarget =
                targetPath + ".zagent_update_tmp";

            File.Copy(
                stagedPath,
                tempTarget,
                overwrite: true);

            File.Move(
                tempTarget,
                targetPath,
                overwrite: true);
        }

        foreach (var node in deletes)
        {
            var raw = node?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(raw))
            {
                continue;
            }

            var relativePath = ValidateRelativePath(raw);
            var target = Path.Combine(
                options.EngineRoot,
                relativePath);

            DeletePath(target);
        }

        metadata["status"] = "applied";
        metadata["applied_at"] =
            DateTimeOffset.UtcNow.ToString("O");

        await SaveJsonNodeAsync(
            metadataPath,
            metadata,
            cancellationToken);
    }

    private async Task RollbackAsync(
        FilesIntegrationOptions options,
        string updateId,
        CancellationToken cancellationToken)
    {
        ValidateUpdateId(updateId);

        var backupRoot = Path.Combine(
            options.UpdateStateRoot,
            "backups",
            updateId);
        var manifestPath = Path.Combine(
            backupRoot,
            "manifest.json");

        var manifest = JsonNode.Parse(
                await File.ReadAllTextAsync(
                    manifestPath,
                    cancellationToken)) as JsonObject
            ?? throw new InvalidDataException(
                "Files update backup manifest must be an object.");

        var entries =
            manifest["entries"] as JsonObject
            ?? throw new InvalidDataException(
                "Files update backup entries are missing.");

        foreach (var pair in entries)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var relativePath = ValidateRelativePath(pair.Key);
            var entry = pair.Value as JsonObject
                ?? throw new InvalidDataException(
                    $"Backup entry is invalid for '{pair.Key}'.");

            var target = Path.Combine(
                options.EngineRoot,
                relativePath);

            DeletePath(target);

            var existed =
                entry["existed"]?.GetValue<bool>() == true;

            if (!existed)
            {
                continue;
            }

            var type =
                entry["type"]?.GetValue<string>();
            var source = Path.Combine(
                backupRoot,
                "payload",
                relativePath);

            Directory.CreateDirectory(
                Path.GetDirectoryName(target)
                ?? options.EngineRoot);

            if (string.Equals(
                    type,
                    "directory",
                    StringComparison.Ordinal))
            {
                CopyDirectory(source, target);
            }
            else
            {
                File.Copy(
                    source,
                    target,
                    overwrite: true);
            }
        }

        var stageMetadata = Path.Combine(
            options.UpdateStateRoot,
            "staging",
            updateId,
            "metadata.json");

        if (File.Exists(stageMetadata))
        {
            var metadata = JsonNode.Parse(
                    await File.ReadAllTextAsync(
                        stageMetadata,
                        cancellationToken)) as JsonObject;

            if (metadata is not null)
            {
                metadata["status"] = "rolled_back";
                metadata["rolled_back_at"] =
                    DateTimeOffset.UtcNow.ToString("O");

                await SaveJsonNodeAsync(
                    stageMetadata,
                    metadata,
                    cancellationToken);
            }
        }
    }

    private async Task CreateBackupAsync(
        FilesIntegrationOptions options,
        string updateId,
        IReadOnlyList<string> relativePaths,
        CancellationToken cancellationToken)
    {
        var root = Path.Combine(
            options.UpdateStateRoot,
            "backups",
            updateId);

        if (Directory.Exists(root))
        {
            Directory.Delete(root, recursive: true);
        }

        var payloadRoot = Path.Combine(
            root,
            "payload");
        Directory.CreateDirectory(payloadRoot);

        var entries = new JsonObject();

        foreach (var raw in relativePaths)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var relativePath = ValidateRelativePath(raw);
            var source = Path.Combine(
                options.EngineRoot,
                relativePath);

            var entry = new JsonObject
            {
                ["existed"] =
                    File.Exists(source) ||
                    Directory.Exists(source),
                ["type"] = null
            };

            if (File.Exists(source))
            {
                entry["type"] = "file";

                var destination = Path.Combine(
                    payloadRoot,
                    relativePath);

                Directory.CreateDirectory(
                    Path.GetDirectoryName(destination)
                    ?? payloadRoot);

                File.Copy(
                    source,
                    destination,
                    overwrite: true);
            }
            else if (Directory.Exists(source))
            {
                entry["type"] = "directory";

                var destination = Path.Combine(
                    payloadRoot,
                    relativePath);

                CopyDirectory(source, destination);
            }

            entries[relativePath.Replace(
                Path.DirectorySeparatorChar,
                '/')] = entry;
        }

        var manifest = new JsonObject
        {
            ["update_id"] = updateId,
            ["created_at"] =
                DateTimeOffset.UtcNow.ToString("O"),
            ["entries"] = entries
        };

        await SaveJsonNodeAsync(
            Path.Combine(root, "manifest.json"),
            manifest,
            cancellationToken);
    }

    private async Task WriteResultAsync(
        FilesIntegrationOptions options,
        JsonObject result,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(
            options.UpdateStateRoot);

        var lastResult = Path.Combine(
            options.UpdateStateRoot,
            "last_result.json");

        await SaveJsonNodeAsync(
            lastResult,
            result,
            cancellationToken);

        var history = Path.Combine(
            options.UpdateStateRoot,
            "history.jsonl");

        await File.AppendAllTextAsync(
            history,
            result.ToJsonString() +
            Environment.NewLine,
            cancellationToken);
    }

    private static void ValidateIdentity(
        FilesIntegrationOptions options,
        JsonObject request)
    {
        var component =
            request["component"]?.GetValue<string>();

        if (!string.Equals(
                component,
                "files",
                StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                "Update request is not for Files.");
        }

        var engineRoot = Path.GetFullPath(
            request["engine_root"]?.GetValue<string>()
            ?? "");

        var stateRoot = Path.GetFullPath(
            request["state_root"]?.GetValue<string>()
            ?? "");

        if (!string.Equals(
                engineRoot,
                Path.GetFullPath(options.EngineRoot),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                "Update request engine root does not match Files configuration.");
        }

        if (!string.Equals(
                stateRoot,
                Path.GetFullPath(options.UpdateStateRoot),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                "Update request state root does not match Files configuration.");
        }
    }

    private static string ValidateRelativePath(
        string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new InvalidDataException(
                "Update path cannot be empty.");
        }

        var normalized = path
            .Replace('/', Path.DirectorySeparatorChar)
            .Replace('\\', Path.DirectorySeparatorChar);

        if (Path.IsPathRooted(normalized))
        {
            throw new InvalidDataException(
                $"Update path must be relative: {path}");
        }

        var parts = normalized.Split(
            Path.DirectorySeparatorChar,
            StringSplitOptions.RemoveEmptyEntries);

        if (parts.Any(
                part =>
                    string.Equals(
                        part,
                        "..",
                        StringComparison.Ordinal)))
        {
            throw new InvalidDataException(
                $"Update path traversal is not allowed: {path}");
        }

        return Path.Combine(parts);
    }

    private static void ValidateUpdateId(
        string updateId)
    {
        if (string.IsNullOrWhiteSpace(updateId) ||
            updateId.Any(
                c =>
                    !(char.IsLetterOrDigit(c) ||
                      c is '-' or '_' or '.')))
        {
            throw new InvalidDataException(
                "Files update_id is invalid.");
        }
    }

    private static async Task<string> ComputeSha256Async(
        string path,
        CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            64 * 1024,
            FileOptions.Asynchronous |
            FileOptions.SequentialScan);

        var hash = await SHA256.HashDataAsync(
            stream,
            cancellationToken);

        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static void DeletePath(string path)
    {
        if (File.Exists(path))
        {
            File.Delete(path);
            return;
        }

        if (Directory.Exists(path))
        {
            Directory.Delete(
                path,
                recursive: true);
        }
    }

    private static void CopyDirectory(
        string source,
        string destination)
    {
        Directory.CreateDirectory(destination);

        foreach (var directory in Directory
            .EnumerateDirectories(
                source,
                "*",
                SearchOption.AllDirectories))
        {
            var relative =
                Path.GetRelativePath(
                    source,
                    directory);

            Directory.CreateDirectory(
                Path.Combine(
                    destination,
                    relative));
        }

        foreach (var file in Directory
            .EnumerateFiles(
                source,
                "*",
                SearchOption.AllDirectories))
        {
            var relative =
                Path.GetRelativePath(
                    source,
                    file);
            var target =
                Path.Combine(
                    destination,
                    relative);

            Directory.CreateDirectory(
                Path.GetDirectoryName(target)
                ?? destination);

            File.Copy(
                file,
                target,
                overwrite: true);
        }
    }

    private async Task SaveJsonNodeAsync(
        string path,
        JsonNode node,
        CancellationToken cancellationToken)
    {
        await _store.SaveAsync(
            path,
            node,
            cancellationToken);
    }
}
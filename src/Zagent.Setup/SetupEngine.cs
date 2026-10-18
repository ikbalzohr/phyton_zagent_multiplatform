using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;

namespace Zagent.Setup;

public sealed class SetupEngine
{
    private readonly IInstallInitializer _initializer;
    private readonly IWindowsInstallationIntegration _windowsIntegration;
    private readonly JsonSerializerOptions _json;

    public SetupEngine(
        IInstallInitializer? initializer = null,
        IWindowsInstallationIntegration? windowsIntegration = null)
    {
        _initializer =
            initializer ?? new CoreInstallInitializer();
        _windowsIntegration =
            windowsIntegration ?? new WindowsInstallationIntegration();

        _json = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
            WriteIndented = true
        };
    }

    public event EventHandler<SetupProgress>? Progress;

    public async Task<SetupResult> ExecuteAsync(
        SetupRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        return request.Mode switch
        {
            SetupMode.Verify =>
                await VerifyAsync(
                    RequireSource(request),
                    request.TargetRoot,
                    cancellationToken),
            SetupMode.Install =>
                await InstallOrRepairAsync(
                    request,
                    repairOnly: false,
                    cancellationToken),
            SetupMode.Repair =>
                await InstallOrRepairAsync(
                    request,
                    repairOnly: true,
                    cancellationToken),
            SetupMode.Uninstall =>
                await UninstallAsync(
                    request,
                    cancellationToken),
            _ => throw new ArgumentOutOfRangeException(
                nameof(request))
        };
    }

    public async Task<PayloadManifest> LoadPayloadManifestAsync(
        string sourceRoot,
        CancellationToken cancellationToken = default)
    {
        var manifestPath = Path.Combine(
            Path.GetFullPath(sourceRoot),
            "payload-manifest.json");

        await using var stream =
            File.OpenRead(manifestPath);

        var manifest =
            await JsonSerializer.DeserializeAsync<
                PayloadManifest>(
                stream,
                _json,
                cancellationToken) ??
            throw new InvalidDataException(
                "Payload manifest is JSON null.");

        ValidateManifest(manifest);
        return manifest;
    }

    private async Task<SetupResult> InstallOrRepairAsync(
        SetupRequest request,
        bool repairOnly,
        CancellationToken cancellationToken)
    {
        var source =
            Path.GetFullPath(
                RequireSource(request));
        var target =
            Path.GetFullPath(
                request.TargetRoot);

        if (PathsEqual(source, target))
        {
            throw new InvalidOperationException(
                "Payload source and target root must be different.");
        }

        var manifest =
            await LoadPayloadManifestAsync(
                source,
                cancellationToken);

        await VerifySourcePayloadAsync(
            source,
            manifest,
            cancellationToken);

        if (repairOnly &&
            !File.Exists(
                Path.Combine(
                    target,
                    "payload-manifest.json")))
        {
            throw new InvalidOperationException(
                "Repair requires an existing Zagent installation.");
        }

        if (!repairOnly)
        {
            ValidateInstallTarget(target);
        }

        Directory.CreateDirectory(target);

        var previousManifest =
            await TryLoadInstalledManifestAsync(
                target,
                cancellationToken);

        // Product-line reset is not a SemVer downgrade. Never carry old per-chat
        // grants/identity into the neutral v1 product through an in-place repair.
        if (manifest.ProductLine != "zagent-mcp-v1" || manifest.SuiteVersion != "1.0.0")
            throw new InvalidOperationException("Only the Zagent MCP v1 payload may be installed; offline migration is required.");
        if (LooksLikeExistingZagentInstallation(target) && previousManifest?.ProductLine != "zagent-mcp-v1")
            throw new InvalidOperationException("Legacy or damaged installation requires offline backup and migration to a fresh target; no identity/grants are imported automatically.");
        if (request.ProductVersion is not null && request.ProductVersion != manifest.CoreVersion)
            throw new InvalidOperationException("Product version override must match the payload manifest.");

        var dataRoot = Path.GetFullPath(
            request.DataRoot ??
            Path.Combine(target, "data"));

        var filesProfile = Path.GetFullPath(
            request.FilesProfile ??
            Path.Combine(target, "workspace"));

        var backupRoot = Path.Combine(
            dataRoot,
            "backups",
            "setup",
            DateTimeOffset.UtcNow.ToString(
                "yyyyMMdd_HHmmss_fff"));

        var changed = new List<string>();
        var backedUp = new List<string>();
        var verified = 0;

        try
        {
            if (LooksLikeExistingZagentInstallation(target))
            {
                Report(
                    8,
                    "prepare-update",
                    "Stopping running Zagent processes before in-place update.");

                await QuiesceTargetProcessesAsync(
                    target,
                    cancellationToken);
            }

            var installedManifestPath =
                Path.Combine(
                    target,
                    "payload-manifest.json");

            if (File.Exists(installedManifestPath))
            {
                var manifestBackup =
                    ResolveRelative(
                        backupRoot,
                        "payload-manifest.json");

                Directory.CreateDirectory(
                    Path.GetDirectoryName(
                        manifestBackup)!);

                File.Copy(
                    installedManifestPath,
                    manifestBackup,
                    overwrite: true);

                backedUp.Add("payload-manifest.json");
            }

            changed.Add("payload-manifest.json");

            var total =
                Math.Max(
                    manifest.Files.Count,
                    1);

            for (var index = 0;
                index < manifest.Files.Count;
                index++)
            {
                cancellationToken.ThrowIfCancellationRequested();

                var entry = manifest.Files[index];
                var sourceFile =
                    ResolveRelative(
                        source,
                        entry.Path);
                var targetFile =
                    ResolveRelative(
                        target,
                        entry.Path);

                var percent =
                    10 +
                    (int)Math.Floor(
                        70d *
                        (index + 1) /
                        total);

                Report(
                    percent,
                    repairOnly ? "repair" : "install",
                    entry.Path);

                if (File.Exists(targetFile) &&
                    await MatchesAsync(
                        targetFile,
                        entry,
                        cancellationToken))
                {
                    verified++;
                    continue;
                }

                if (File.Exists(targetFile))
                {
                    var backupFile =
                        ResolveRelative(
                            backupRoot,
                            entry.Path);

                    Directory.CreateDirectory(
                        Path.GetDirectoryName(
                            backupFile)!);

                    File.Copy(
                        targetFile,
                        backupFile,
                        overwrite: true);

                    backedUp.Add(entry.Path);
                }

                Directory.CreateDirectory(
                    Path.GetDirectoryName(
                        targetFile)!);

                var temporary =
                    targetFile +
                    ".zagent-new-" +
                    Guid.NewGuid().ToString("N");

                File.Copy(
                    sourceFile,
                    temporary,
                    overwrite: false);

                if (!await MatchesAsync(
                        temporary,
                        entry,
                        cancellationToken))
                {
                    File.Delete(temporary);
                    throw new InvalidDataException(
                        $"Copied file failed integrity verification: {entry.Path}");
                }

                File.Move(
                    temporary,
                    targetFile,
                    overwrite: true);

                changed.Add(entry.Path);
                verified++;
            }

            if (previousManifest is not null)
            {
                var nextPaths =
                    new HashSet<string>(
                        manifest.Files.Select(
                            entry => entry.Path),
                        StringComparer.OrdinalIgnoreCase);

                foreach (var previousEntry in
                         previousManifest.Files)
                {
                    cancellationToken.ThrowIfCancellationRequested();

                    if (nextPaths.Contains(previousEntry.Path))
                    {
                        continue;
                    }

                    var staleFile =
                        ResolveRelative(
                            target,
                            previousEntry.Path);

                    if (!File.Exists(staleFile))
                    {
                        continue;
                    }

                    Report(
                        82,
                        "remove-stale",
                        previousEntry.Path);

                    var staleBackup =
                        ResolveRelative(
                            backupRoot,
                            previousEntry.Path);

                    Directory.CreateDirectory(
                        Path.GetDirectoryName(
                            staleBackup)!);

                    File.Copy(
                        staleFile,
                        staleBackup,
                        overwrite: true);

                    backedUp.Add(previousEntry.Path);
                    changed.Add(previousEntry.Path);
                    File.Delete(staleFile);
                }
            }

            File.Copy(
                Path.Combine(
                    source,
                    "payload-manifest.json"),
                Path.Combine(
                    target,
                    "payload-manifest.json"),
                overwrite: true);

            Report(
                85,
                "initialize",
                "Writing machine configuration and installed manifest.");

            await _initializer.InitializeAsync(
                target,
                dataRoot,
                filesProfile,
                request.ProductVersion ??
                manifest.CoreVersion,
                cancellationToken);

            _windowsIntegration.Register(
                target,
                request.ProductVersion ??
                manifest.CoreVersion);

            RemoveEmptyProgramDirectories(
                target,
                preserveData: true);

            Report(
                100,
                "complete",
                repairOnly
                    ? "Repair completed."
                    : "Installation/upgrade completed.");

            return new SetupResult(
                true,
                repairOnly
                    ? SetupMode.Repair
                    : SetupMode.Install,
                target,
                changed.Count(
                    path => !path.Equals(
                        "payload-manifest.json",
                        StringComparison.OrdinalIgnoreCase)),
                verified,
                repairOnly
                    ? "Repair completed."
                    : "Installation/upgrade completed.",
                Directory.Exists(backupRoot)
                    ? backupRoot
                    : null);
        }
        catch
        {
            Report(
                90,
                "rollback",
                "Restoring previous program files.");

            Rollback(
                target,
                backupRoot,
                changed,
                backedUp);

            throw;
        }
    }

    private async Task<SetupResult> VerifyAsync(
        string sourceRoot,
        string targetRoot,
        CancellationToken cancellationToken)
    {
        var source = Path.GetFullPath(sourceRoot);
        var target = Path.GetFullPath(targetRoot);
        var manifest =
            await LoadPayloadManifestAsync(
                source,
                cancellationToken);

        await VerifySourcePayloadAsync(
            source,
            manifest,
            cancellationToken);

        var verified = 0;

        foreach (var entry in manifest.Files)
        {
            var installed =
                ResolveRelative(
                    target,
                    entry.Path);

            if (!File.Exists(installed) ||
                !await MatchesAsync(
                    installed,
                    entry,
                    cancellationToken))
            {
                throw new InvalidDataException(
                    $"Installed payload mismatch: {entry.Path}");
            }

            verified++;
        }

        return new SetupResult(
            true,
            SetupMode.Verify,
            target,
            0,
            verified,
            "Installed payload integrity verified.");
    }


    private async Task<SetupResult> UninstallAsync(
        SetupRequest request,
        CancellationToken cancellationToken)
    {
        var target =
            Path.GetFullPath(
                request.TargetRoot);

        var manifestPath =
            Path.Combine(
                target,
                "payload-manifest.json");

        if (!File.Exists(manifestPath))
        {
            throw new InvalidOperationException(
                "Uninstall requires payload-manifest.json from an existing Zagent installation.");
        }

        PayloadManifest manifest;

        await using (var stream =
            File.OpenRead(manifestPath))
        {
            manifest =
                await JsonSerializer.DeserializeAsync<
                    PayloadManifest>(
                    stream,
                    _json,
                    cancellationToken) ??
                throw new InvalidDataException(
                    "Installed payload manifest is JSON null.");
        }

        ValidateManifest(manifest);

        _windowsIntegration.Unregister(target);

        var removed = 0;
        var total =
            Math.Max(
                manifest.Files.Count,
                1);

        for (var index = 0;
            index < manifest.Files.Count;
            index++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var entry = manifest.Files[index];
            var path =
                ResolveRelative(
                    target,
                    entry.Path);

            Report(
                10 +
                (int)Math.Floor(
                    70d *
                    (index + 1) /
                    total),
                "uninstall",
                entry.Path);

            if (File.Exists(path))
            {
                File.Delete(path);
                removed++;
            }
        }

        if (File.Exists(manifestPath))
        {
            File.Delete(manifestPath);
        }

        RemoveEmptyProgramDirectories(
            target,
            preserveData: request.KeepData);

        if (!request.KeepData)
        {
            var dataRoot =
                Path.GetFullPath(
                    request.DataRoot ??
                    Path.Combine(
                        target,
                        "data"));

            var filesProfile =
                Path.GetFullPath(
                    request.FilesProfile ??
                    Path.Combine(
                        target,
                        "workspace"));

            DeletePersistentRoot(
                target,
                dataRoot);

            if (!PathsEqual(
                    dataRoot,
                    filesProfile))
            {
                DeletePersistentRoot(
                    target,
                    filesProfile);
            }

            RemoveEmptyProgramDirectories(
                target,
                preserveData: false);
        }

        Report(
            100,
            "complete",
            request.KeepData
                ? "Uninstall completed; user data preserved."
                : "Uninstall completed; user data removed.");

        return new SetupResult(
            true,
            SetupMode.Uninstall,
            target,
            removed,
            0,
            request.KeepData
                ? "Uninstall completed; user data preserved."
                : "Uninstall completed; user data removed.");
    }

    private async Task VerifySourcePayloadAsync(
        string source,
        PayloadManifest manifest,
        CancellationToken cancellationToken)
    {
        var total =
            Math.Max(
                manifest.Files.Count,
                1);

        for (var index = 0;
            index < manifest.Files.Count;
            index++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var entry =
                manifest.Files[index];
            var file =
                ResolveRelative(
                    source,
                    entry.Path);

            Report(
                (int)Math.Floor(
                    10d *
                    (index + 1) /
                    total),
                "verify-source",
                entry.Path);

            if (!File.Exists(file) ||
                !await MatchesAsync(
                    file,
                    entry,
                    cancellationToken))
            {
                throw new InvalidDataException(
                    $"Source payload integrity mismatch: {entry.Path}");
            }
        }
    }

    private static async Task<bool> MatchesAsync(
        string path,
        PayloadFileEntry entry,
        CancellationToken cancellationToken)
    {
        var info =
            new FileInfo(path);

        if (!info.Exists ||
            info.Length != entry.Size)
        {
            return false;
        }

        await using var stream =
            File.Open(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read);

        var hash =
            await SHA256.HashDataAsync(
                stream,
                cancellationToken);

        var actual =
            Convert.ToHexString(hash)
                .ToLowerInvariant();

        return string.Equals(
            actual,
            entry.Sha256,
            StringComparison.OrdinalIgnoreCase);
    }

    private static void ValidateManifest(
        PayloadManifest manifest)
    {
        if (manifest.SchemaVersion != "1.0" ||
            manifest.Product != "Zagent" ||
            !manifest.Platform.Equals(
                "win-x64",
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                "Unsupported Zagent payload manifest.");
        }

        if (manifest.FileCount !=
            manifest.Files.Count)
        {
            throw new InvalidDataException(
                "Payload manifest file count is inconsistent.");
        }

        var seen =
            new HashSet<string>(
                StringComparer.OrdinalIgnoreCase);

        foreach (var entry in manifest.Files)
        {
            if (string.IsNullOrWhiteSpace(
                    entry.Path) ||
                entry.Size < 0 ||
                entry.Sha256.Length != 64 ||
                !seen.Add(entry.Path))
            {
                throw new InvalidDataException(
                    $"Invalid payload entry '{entry.Path}'.");
            }

            if (Path.IsPathRooted(entry.Path))
            {
                throw new InvalidDataException(
                    $"Payload entry must be relative: {entry.Path}");
            }
        }
    }

    private async Task<PayloadManifest?> TryLoadInstalledManifestAsync(
        string target,
        CancellationToken cancellationToken)
    {
        var manifestPath =
            Path.Combine(
                target,
                "payload-manifest.json");

        if (!File.Exists(manifestPath))
        {
            return null;
        }

        try
        {
            await using var stream =
                File.Open(
                    manifestPath,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.ReadWrite);

            var manifest =
                await JsonSerializer.DeserializeAsync<PayloadManifest>(
                    stream,
                    _json,
                    cancellationToken);

            if (manifest is null)
            {
                return null;
            }

            ValidateManifest(manifest);
            return manifest;
        }
        catch (Exception ex)
            when (ex is JsonException or
                InvalidDataException or
                IOException)
        {
            // A damaged/legacy installed manifest must not prevent a valid
            // in-place update. We simply skip stale-file reconciliation.
            return null;
        }
    }

    private static bool LooksLikeExistingZagentInstallation(
        string target)
    {
        if (!Directory.Exists(target))
        {
            return false;
        }

        if (File.Exists(
                Path.Combine(
                    target,
                    "payload-manifest.json")))
        {
            return true;
        }

        var manager =
            File.Exists(
                Path.Combine(
                    target,
                    "Zagent.Manager.exe"));
        var core =
            File.Exists(
                Path.Combine(
                    target,
                    "Zagent.Core.exe"));
        var setup =
            File.Exists(
                Path.Combine(
                    target,
                    "Zagent.Setup.exe"));
        var agents =
            Directory.Exists(
                Path.Combine(
                    target,
                    "agents"));
        var machineConfig =
            File.Exists(
                Path.Combine(
                    target,
                    "data",
                    "config",
                    "zagent.machine.json"));

        return (manager || core || setup) &&
            (agents || machineConfig);
    }

    private static async Task QuiesceTargetProcessesAsync(
        string target,
        CancellationToken cancellationToken)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var targetRoot =
            Path.GetFullPath(target)
                .TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar);

        for (var pass = 0; pass < 3; pass++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var candidates =
                FindTargetProcesses(targetRoot);

            if (candidates.Count == 0)
            {
                return;
            }

            foreach (var process in candidates)
            {
                cancellationToken.ThrowIfCancellationRequested();

                try
                {
                    if (process.HasExited)
                    {
                        continue;
                    }

                    try
                    {
                        if (process.CloseMainWindow())
                        {
                            process.WaitForExit(1200);
                        }
                    }
                    catch
                    {
                    }

                    if (!process.HasExited)
                    {
                        process.Kill(
                            entireProcessTree: true);

                        if (!process.WaitForExit(5000))
                        {
                            throw new InvalidOperationException(
                                $"Could not stop running Zagent process {process.Id} before update.");
                        }
                    }
                }
                finally
                {
                    process.Dispose();
                }
            }

            await Task.Delay(
                150,
                cancellationToken);
        }

        var remaining =
            FindTargetProcesses(targetRoot);

        try
        {
            if (remaining.Count > 0)
            {
                throw new InvalidOperationException(
                    "One or more running Zagent processes still hold files in the installation directory.");
            }
        }
        finally
        {
            foreach (var process in remaining)
            {
                process.Dispose();
            }
        }
    }

    private static List<Process> FindTargetProcesses(
        string targetRoot)
    {
        var currentPid =
            Environment.ProcessId;
        var result =
            new List<Process>();

        foreach (var process in Process.GetProcesses())
        {
            if (process.Id == currentPid)
            {
                process.Dispose();
                continue;
            }

            try
            {
                var executable =
                    process.MainModule?.FileName;

                if (string.IsNullOrWhiteSpace(executable))
                {
                    process.Dispose();
                    continue;
                }

                var fullExecutable =
                    Path.GetFullPath(executable);

                if (fullExecutable.StartsWith(
                        targetRoot +
                        Path.DirectorySeparatorChar,
                        StringComparison.OrdinalIgnoreCase))
                {
                    result.Add(process);
                    continue;
                }
            }
            catch
            {
            }

            process.Dispose();
        }

        return result;
    }

    private static void ValidateInstallTarget(
        string target)
    {
        if (!Directory.Exists(target))
        {
            return;
        }

        var entries =
            Directory.EnumerateFileSystemEntries(
                target)
                .Take(2)
                .ToArray();

        if (entries.Length == 0)
        {
            return;
        }

        if (LooksLikeExistingZagentInstallation(target))
        {
            return;
        }

        var allowed =
            new HashSet<string>(
                StringComparer.OrdinalIgnoreCase)
            {
                "data",
                "workspace"
            };

        if (entries.All(
                path =>
                    Directory.Exists(path) &&
                    allowed.Contains(
                        Path.GetFileName(path))))
        {
            return;
        }

        throw new InvalidOperationException(
            "Target folder is not empty and is not an existing Zagent installation.");
    }

    private static string ResolveRelative(
        string root,
        string relative)
    {
        var normalized =
            relative.Replace(
                '/',
                Path.DirectorySeparatorChar);

        var combined =
            Path.GetFullPath(
                Path.Combine(
                    root,
                    normalized));

        var rootFull =
            Path.GetFullPath(root)
                .TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar);

        if (!combined.Equals(
                rootFull,
                StringComparison.OrdinalIgnoreCase) &&
            !combined.StartsWith(
                rootFull +
                Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                $"Path escapes root: {relative}");
        }

        return combined;
    }

    private static void Rollback(
        string target,
        string backupRoot,
        IReadOnlyList<string> changed,
        IReadOnlyCollection<string> backedUp)
    {
        var backupSet =
            new HashSet<string>(
                backedUp,
                StringComparer.OrdinalIgnoreCase);

        foreach (var relative in changed.Reverse())
        {
            var targetFile =
                ResolveRelative(
                    target,
                    relative);

            if (backupSet.Contains(relative))
            {
                var backup =
                    ResolveRelative(
                        backupRoot,
                        relative);

                if (File.Exists(backup))
                {
                    Directory.CreateDirectory(
                        Path.GetDirectoryName(
                            targetFile)!);

                    File.Copy(
                        backup,
                        targetFile,
                        overwrite: true);
                }
            }
            else if (File.Exists(targetFile))
            {
                File.Delete(targetFile);
            }
        }
    }

    private static void RemoveEmptyProgramDirectories(
        string target,
        bool preserveData)
    {
        if (!Directory.Exists(target))
        {
            return;
        }

        var preserved =
            new HashSet<string>(
                StringComparer.OrdinalIgnoreCase);

        if (preserveData)
        {
            preserved.Add(
                Path.GetFullPath(
                    Path.Combine(
                        target,
                        "data")));
            preserved.Add(
                Path.GetFullPath(
                    Path.Combine(
                        target,
                        "workspace")));
        }

        foreach (var directory in
                 Directory.EnumerateDirectories(
                     target,
                     "*",
                     SearchOption.AllDirectories)
                     .OrderByDescending(
                         path => path.Length))
        {
            var full =
                Path.GetFullPath(directory);

            if (preserved.Any(
                    root =>
                        full.Equals(
                            root,
                            StringComparison.OrdinalIgnoreCase) ||
                        full.StartsWith(
                            root +
                            Path.DirectorySeparatorChar,
                            StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            try
            {
                if (!Directory.EnumerateFileSystemEntries(
                        full)
                        .Any())
                {
                    Directory.Delete(full);
                }
            }
            catch
            {
            }
        }

        try
        {
            if (!Directory.EnumerateFileSystemEntries(
                    target)
                    .Any())
            {
                Directory.Delete(target);
            }
        }
        catch
        {
        }
    }

    private static void DeletePersistentRoot(
        string installRoot,
        string persistentRoot)
    {
        var install =
            Path.GetFullPath(installRoot);
        var persistent =
            Path.GetFullPath(persistentRoot);

        if (!persistent.Equals(
                install,
                StringComparison.OrdinalIgnoreCase) &&
            !persistent.StartsWith(
                install +
                Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                "Delete-data may only remove persistent roots inside InstallRoot.");
        }

        if (Directory.Exists(persistent))
        {
            Directory.Delete(
                persistent,
                recursive: true);
        }
    }

    private static bool PathsEqual(
        string left,
        string right) =>
        string.Equals(
            Path.GetFullPath(left)
                .TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar),
            Path.GetFullPath(right)
                .TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar),
            StringComparison.OrdinalIgnoreCase);

    private static string RequireSource(
        SetupRequest request) =>
        !string.IsNullOrWhiteSpace(
            request.SourceRoot)
            ? request.SourceRoot
            : throw new ArgumentException(
                "SourceRoot is required for this setup mode.");

    private void Report(
        int percent,
        string stage,
        string message) =>
        Progress?.Invoke(
            this,
            new SetupProgress(
                Math.Clamp(percent, 0, 100),
                stage,
                message));
}
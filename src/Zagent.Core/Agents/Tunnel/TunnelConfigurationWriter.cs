using Zagent.Core.Configuration;
using Zagent.Core.Manager;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Zagent.Core.Agents.Tunnel;

public sealed class TunnelConfigurationWriter
{
    private readonly AtomicJsonFileStore _store;

    public TunnelConfigurationWriter(
        AtomicJsonFileStore? store = null)
    {
        _store = store ?? new AtomicJsonFileStore();
    }

    public async Task WriteAsync(
        TunnelIntegrationOptions options,
        IReadOnlyList<TunnelServiceDefinition> services,
        bool pluginConfigured = false,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);
        ArgumentNullException.ThrowIfNull(services);

        Directory.CreateDirectory(options.ConfigRoot);
        Directory.CreateDirectory(options.RuntimeRoot);

        ValidateServices(services);

        var tunnelConfig = new
        {
            schema_version = 1,
            grant_writer_lock_version = 1,
            router = new
            {
                host = options.BindHost,
                port = options.RouterPort,
                mcp_path = options.McpPath,
                log_level = options.LogLevel
            },
            security = new
            {
                allow_local_upstreams_only = true,
                allowed_hosts = new[]
                {
                    "127.0.0.1",
                    "::1",
                    "127.0.0.3",
                    options.BindHost,
                    "localhost"
                }
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray(),
                allow_http = true
            },
            orchestration = new
            {
                workers = 8,
                fast_lane_workers = 2
            }
        };

        var serviceRows = services
            .Select(
                service => new
                {
                    id = service.Id,
                    name = service.Name,
                    @namespace = service.Namespace,
                    url = service.Url,
                    permanent = service.Permanent,
                    enabled = service.Enabled,
                    timeout_seconds = service.TimeoutSeconds
                })
            .ToArray();

        var tunnelPath = Path.GetFullPath(Path.Combine(options.ConfigRoot, "tunnel.json"));
        // Lock before reading, not just before SaveAsync: otherwise a Router grant
        // published after our read could be silently replaced by this stale merge.
        using (await AcquireAccessLockAsync(tunnelPath, cancellationToken))
        {
            var merged = File.Exists(tunnelPath)
                ? JsonNode.Parse(await File.ReadAllTextAsync(tunnelPath, cancellationToken))!.AsObject()
                : new JsonObject();
            var generated = JsonSerializer.SerializeToNode(tunnelConfig)!.AsObject();
            foreach (var entry in generated) merged[entry.Key] = entry.Value?.DeepClone();
            merged.Remove("plugin"); // no legacy per-chat/plugin enrollment mode
            await _store.SaveAsync(tunnelPath, merged, cancellationToken);
            var observed = JsonNode.Parse(await File.ReadAllTextAsync(tunnelPath, cancellationToken));
            if (!JsonNode.DeepEquals(merged, observed))
                throw new IOException("Tunnel configuration publication could not be verified.");
        }

        await _store.SaveAsync(
            Path.Combine(
                options.ConfigRoot,
                "core_services.json"),
            new
            {
                schema_version = 1,
                services = serviceRows
            },
            cancellationToken);

        var additionalServicesPath = Path.Combine(
            options.ConfigRoot,
            "additional_services.json");

        if (!File.Exists(additionalServicesPath))
        {
            await _store.SaveAsync(
                additionalServicesPath,
                new
                {
                    schema_version = 1,
                    services = Array.Empty<object>()
                },
                cancellationToken);
        }
    }

    // POSIX record locks are process-scoped; serialize Core instances too.
    private static readonly ConcurrentDictionary<string, SemaphoreSlim> AccessLocks =
        new(OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
    private static readonly TimeSpan AccessLockTimeout = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan AccessLockRetry = TimeSpan.FromMilliseconds(50);

    private static async Task<IDisposable> AcquireAccessLockAsync(string path, CancellationToken cancellationToken)
    {
        var gate = AccessLocks.GetOrAdd(path, static _ => new SemaphoreSlim(1, 1));
        var elapsed = Stopwatch.StartNew();
        if (!await gate.WaitAsync(AccessLockTimeout, cancellationToken))
            throw new TimeoutException("Tunnel configuration writer is busy.");
        FileStream? stream = null;
        try
        {
            var lockPath = path + ".access.lock";
            ValidateAccessPath(path);
            ValidateAccessPath(lockPath);
            if (OperatingSystem.IsWindows())
                InternalSecretStore.ValidatePrivatePath(Path.GetDirectoryName(path)!, directory: true);
            var settings = new FileStreamOptions
            {
                Mode = FileMode.OpenOrCreate, Access = FileAccess.ReadWrite,
                Share = FileShare.ReadWrite, BufferSize = 1
            };
            if (!OperatingSystem.IsWindows())
                settings.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
            stream = new FileStream(lockPath, settings);
            ValidateAccessPath(lockPath);
            if (OperatingSystem.IsWindows())
            {
                var owner = WindowsIdentity.GetCurrent().User!;
                var acl = new FileInfo(lockPath).GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access);
                if (!owner.Equals(acl.GetOwner(typeof(SecurityIdentifier))))
                    throw new InvalidDataException("Tunnel access lock requires owner-only access.");
                foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
                    if (rule.AccessControlType == AccessControlType.Allow && !owner.Equals(rule.IdentityReference))
                        throw new InvalidDataException("Tunnel access lock requires owner-only access.");
            }
            else if ((File.GetUnixFileMode(lockPath) & (UnixFileMode.GroupRead | UnixFileMode.GroupWrite |
                UnixFileMode.OtherRead | UnixFileMode.OtherWrite)) != 0)
                throw new InvalidDataException("Tunnel access lock requires owner-only access.");
            while (true)
            {
                cancellationToken.ThrowIfCancellationRequested();
                try
                {
                    // Shared contract with Router: fixed file, byte [0,1), never
                    // unlink it. Windows msvcrt.locking; Unix fcntl.lockf, NOT flock.
                    if (OperatingSystem.IsMacOS())
                        throw new PlatformNotSupportedException("Tunnel writer byte-range locks require Windows or Linux.");
                    stream.Lock(0, 1);
                    break;
                }
                catch (IOException) when (elapsed.Elapsed < AccessLockTimeout)
                {
                    await Task.Delay(AccessLockRetry, cancellationToken);
                }
                catch (IOException ex)
                {
                    throw new TimeoutException("Tunnel configuration writer is busy.", ex);
                }
            }
            ValidateAccessPath(path);
            return new AccessLease(stream, gate);
        }
        catch
        {
            stream?.Dispose();
            gate.Release();
            throw;
        }
    }

    private static void ValidateAccessPath(string path)
    {
        for (var current = Path.GetFullPath(path); current is not null; current = Path.GetDirectoryName(current))
        {
            var info = (FileSystemInfo)new FileInfo(current);
            if (info.LinkTarget is not null || (info.Exists && (info.Attributes & FileAttributes.ReparsePoint) != 0))
                throw new InvalidDataException("Tunnel configuration paths cannot traverse reparse points.");
        }
    }

    private sealed class AccessLease(FileStream stream, SemaphoreSlim gate) : IDisposable
    {
        public void Dispose()
        {
            // Closing the only local descriptor releases the byte-range lock.
            try { stream.Dispose(); }
            finally { gate.Release(); }
        }
    }

    private static void ValidateServices(
        IReadOnlyList<TunnelServiceDefinition> services)
    {
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var namespaces = new HashSet<string>(StringComparer.Ordinal);

        foreach (var service in services)
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(service.Id);
            ArgumentException.ThrowIfNullOrWhiteSpace(service.Name);
            ArgumentException.ThrowIfNullOrWhiteSpace(service.Namespace);

            if (!ids.Add(service.Id))
            {
                throw new InvalidDataException(
                    $"Duplicate Tunnel service id '{service.Id}'.");
            }

            if (!namespaces.Add(service.Namespace))
            {
                throw new InvalidDataException(
                    $"Duplicate Tunnel namespace '{service.Namespace}'.");
            }

            if (!Uri.TryCreate(
                    service.Url,
                    UriKind.Absolute,
                    out var uri) ||
                !uri.IsLoopback)
            {
                throw new InvalidDataException(
                    $"Tunnel upstream '{service.Id}' must use a loopback URL.");
            }

            if (service.TimeoutSeconds is < 3 or > 120)
            {
                throw new InvalidDataException(
                    $"Tunnel upstream '{service.Id}' timeout is invalid.");
            }
        }
    }
}
using Zagent.Core.Configuration;
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
                    "127.0.0.2",
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

        var tunnelPath = Path.Combine(options.ConfigRoot, "tunnel.json");
        var merged = File.Exists(tunnelPath)
            ? JsonNode.Parse(await File.ReadAllTextAsync(tunnelPath, cancellationToken))!.AsObject()
            : new JsonObject();
        var generated = JsonSerializer.SerializeToNode(tunnelConfig)!.AsObject();
        foreach (var entry in generated) merged[entry.Key] = entry.Value?.DeepClone();
        merged.Remove("plugin"); // no legacy per-chat/plugin enrollment mode
        await _store.SaveAsync(tunnelPath, merged, cancellationToken);

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
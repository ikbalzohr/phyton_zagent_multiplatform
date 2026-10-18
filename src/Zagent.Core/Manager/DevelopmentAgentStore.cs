using System.Text.Json;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed class DevelopmentAgentStore
{
    private readonly string _path;
    private readonly int _portStart;
    private readonly int _portEnd;

    public DevelopmentAgentStore(string path, int portStart = 18900, int portEnd = 18999)
    {
        _path = Path.GetFullPath(path ?? throw new ArgumentNullException(nameof(path)));
        if (portStart < 1 || portEnd > 65535 || portStart > portEnd)
            throw new ArgumentOutOfRangeException(nameof(portStart));
        _portStart = portStart;
        _portEnd = portEnd;
    }

    public async Task<IReadOnlyList<ManagerDevelopmentAgentRow>> SnapshotAsync(
        CancellationToken cancellationToken = default)
    {
        var rows = await LoadAsync(
            cancellationToken);

        return rows
            .OrderBy(
                item => item.Name,
                StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public async Task<ManagerDevelopmentAgentRow> AddAsync(
        ManagerDevelopmentAgentRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var name = request.Name.Trim();
        var ns = request.Namespace.Trim().ToLowerInvariant();
        var url = request.Url.Trim();

        if (string.IsNullOrWhiteSpace(name))
        {
            throw new ArgumentException(
                "Development agent name is required.");
        }

        if (ns.Length < 2 ||
            ns.Length > 32 ||
            !char.IsLetter(ns[0]) ||
            ns.Any(
                ch => !char.IsLower(ch) &&
                    !char.IsDigit(ch) &&
                    ch != '_'))
        {
            throw new ArgumentException(
                "Namespace must start with a lowercase letter and contain only lowercase letters, digits, or underscore.");
        }

        if (!Uri.TryCreate(
                url,
                UriKind.Absolute,
                out var uri) ||
            !uri.IsLoopback ||
            uri.Scheme is not ("http" or "https"))
        {
            throw new ArgumentException(
                "Development agent MCP URL must be an absolute loopback HTTP/HTTPS URL.");
        }

        if (uri.Port < _portStart || uri.Port > _portEnd)
        {
            throw new ArgumentException(
                $"Development agent MCP port must be in the installation range {_portStart}-{_portEnd}.");
        }

        var timeout = Math.Clamp(
            request.TimeoutSeconds,
            3,
            120);

        var rows = (
            await LoadAsync(
                cancellationToken))
            .ToList();

        if (rows.Any(
                item =>
                    item.Namespace.Equals(
                        ns,
                        StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidOperationException(
                $"Development namespace '{ns}' already exists.");
        }

        var id = "dev_" + ns;
        if (rows.Any(
                item =>
                    item.Id.Equals(
                        id,
                        StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidOperationException(
                $"Development agent id '{id}' already exists.");
        }

        var row = new ManagerDevelopmentAgentRow(
            id,
            name,
            ns,
            url,
            true,
            timeout);

        rows.Add(row);
        await SaveAsync(
            rows,
            cancellationToken);

        return row;
    }

    public async Task<bool> RemoveAsync(
        string id,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(id);

        var rows = (
            await LoadAsync(
                cancellationToken))
            .ToList();

        var removed = rows.RemoveAll(
            item => item.Id.Equals(
                id,
                StringComparison.OrdinalIgnoreCase)) > 0;

        if (removed)
        {
            await SaveAsync(
                rows,
                cancellationToken);
        }

        return removed;
    }

    private async Task<IReadOnlyList<ManagerDevelopmentAgentRow>> LoadAsync(
        CancellationToken cancellationToken)
    {
        if (!File.Exists(_path))
        {
            return [];
        }

        var json = await File.ReadAllTextAsync(
            _path,
            cancellationToken);

        using var document = JsonDocument.Parse(json);

        if (!document.RootElement.TryGetProperty(
                "services",
                out var services) ||
            services.ValueKind != JsonValueKind.Array)
        {
            return [];
        }

        var rows = new List<ManagerDevelopmentAgentRow>();

        foreach (var service in services.EnumerateArray())
        {
            var id = service.GetProperty("id").GetString() ?? "";
            if (!id.StartsWith(
                    "dev_",
                    StringComparison.Ordinal))
            {
                continue;
            }

            rows.Add(
                new ManagerDevelopmentAgentRow(
                    id,
                    service.GetProperty("name").GetString() ?? id,
                    service.GetProperty("namespace").GetString() ?? "",
                    service.GetProperty("url").GetString() ?? "",
                    !service.TryGetProperty("enabled", out var enabled) ||
                        enabled.ValueKind != JsonValueKind.False,
                    service.TryGetProperty(
                        "timeout_seconds",
                        out var timeout)
                        ? timeout.GetInt32()
                        : 25));
        }

        return rows;
    }

    private async Task SaveAsync(
        IReadOnlyList<ManagerDevelopmentAgentRow> rows,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(
            Path.GetDirectoryName(_path)!);

        var payload = new
        {
            schema_version = 1,
            services = rows.Select(
                row => new
                {
                    id = row.Id,
                    name = row.Name,
                    @namespace = row.Namespace,
                    url = row.Url,
                    permanent = false,
                    enabled = row.Enabled,
                    timeout_seconds = row.TimeoutSeconds
                }).ToArray()
        };

        var temporary = _path + ".tmp";

        await File.WriteAllTextAsync(
            temporary,
            JsonSerializer.Serialize(
                payload,
                new JsonSerializerOptions
                {
                    WriteIndented = true
                }) + Environment.NewLine,
            cancellationToken);

        File.Move(
            temporary,
            _path,
            overwrite: true);
    }
}

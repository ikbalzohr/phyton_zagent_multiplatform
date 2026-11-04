using System.Net.Http.Json;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.Json.Nodes;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed class RouterManagerService
{
    private readonly HttpClient _httpClient;
    private readonly Uri _baseUri;
    private readonly string _configRoot;
    private readonly SemaphoreSlim _configGate = new(1, 1);

    public RouterManagerService(
        Uri baseUri,
        string configRoot,
        HttpClient? httpClient = null)
    {
        ArgumentNullException.ThrowIfNull(baseUri);
        ArgumentException.ThrowIfNullOrWhiteSpace(configRoot);

        if (!baseUri.IsLoopback)
        {
            throw new ArgumentException(
                "Router Manager endpoint must be loopback.",
                nameof(baseUri));
        }

        _baseUri = new Uri(
            baseUri.GetLeftPart(UriPartial.Authority) + "/");
        _configRoot = Path.GetFullPath(configRoot);
        _httpClient = httpClient ?? Zagent.Core.Manager.InternalManagementChannel.CreateClient(TimeSpan.FromSeconds(5));
    }

    public async Task RenameIdentityAliasAsync(
        string deviceAlias,
        CancellationToken cancellationToken = default)
    {
        using var response =
            await _httpClient.PostAsJsonAsync(
                new Uri(
                    _baseUri,
                    "router/identity/alias"),
                new
                {
                    device_alias = deviceAlias
                },
                cancellationToken);

        response.EnsureSuccessStatusCode();
    }


    public async Task<ManagerOperationResult> ExecuteAsync(
        ManagerRouterActionRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var action = (request.Action ?? "")
            .Trim()
            .ToLowerInvariant();

        if (action == "reload")
        {
            return await ReloadAsync(
                cancellationToken);
        }

        var serviceId =
            (request.ServiceId ?? "").Trim();

        if (string.IsNullOrWhiteSpace(serviceId))
        {
            return new ManagerOperationResult(
                false,
                "router." + action,
                "",
                "Select a Tunnel/MCP service first.");
        }

        return action switch
        {
            "test" => await TestAsync(serviceId, cancellationToken),
            "tools" => await ToolsAsync(serviceId, cancellationToken),
            _ => new ManagerOperationResult(false, "router." + action, serviceId,
                "Only local service diagnostics/tools are exposed; enable/disable/reconnect require the authoritative router admin interface.")
        };
    }

    private async Task<ManagerOperationResult> SetRoutingAsync(
        string serviceId,
        bool enabled,
        CancellationToken cancellationToken)
    {
        await _configGate.WaitAsync(
            cancellationToken);

        try
        {
            var changed = false;

            foreach (var fileName in new[]
                     {
                         "core_services.json",
                         "additional_services.json"
                     })
            {
                var path = Path.Combine(
                    _configRoot,
                    fileName);

                if (!File.Exists(path))
                {
                    continue;
                }

                var raw = await File.ReadAllTextAsync(
                    path,
                    cancellationToken);
                var root = JsonNode.Parse(raw)?.AsObject();
                var services =
                    root?["services"]?.AsArray();

                if (root is null ||
                    services is null)
                {
                    continue;
                }

                foreach (var node in services)
                {
                    if (node is not JsonObject service)
                    {
                        continue;
                    }

                    var id =
                        service["id"]?.GetValue<string>() ?? "";

                    if (!string.Equals(
                            id,
                            serviceId,
                            StringComparison.Ordinal))
                    {
                        continue;
                    }

                    service["enabled"] = enabled;

                    var temporary =
                        path + ".manager.tmp";

                    await File.WriteAllTextAsync(
                        temporary,
                        root.ToJsonString(
                            new JsonSerializerOptions
                            {
                                WriteIndented = true
                            }) + Environment.NewLine,
                        cancellationToken);

                    File.Move(
                        temporary,
                        path,
                        overwrite: true);

                    changed = true;
                    break;
                }

                if (changed)
                {
                    break;
                }
            }

            if (!changed)
            {
                return new ManagerOperationResult(
                    false,
                    enabled
                        ? "router.enable"
                        : "router.disable",
                    serviceId,
                    "Service was not found in Tunnel configuration.");
            }
        }
        finally
        {
            _configGate.Release();
        }

        using var refresh =
            await PostJsonAsync(
                "router/refresh",
                cancellationToken);

        return new ManagerOperationResult(
            true,
            enabled
                ? "router.enable"
                : "router.disable",
            serviceId,
            enabled
                ? "Routing enabled and service list reloaded."
                : "Routing disabled and service list reloaded.");
    }

    private async Task<ManagerOperationResult> ReconnectAsync(
        string serviceId,
        CancellationToken cancellationToken)
    {
        using var document =
            await PostJsonAsync(
                "router/service/" +
                Uri.EscapeDataString(serviceId) +
                "/refresh",
                cancellationToken);

        var root = document.RootElement;
        var ok = GetBool(
            root,
            "ok",
            true);

        return new ManagerOperationResult(
            ok,
            "router.reconnect",
            serviceId,
            ok
                ? "MCP service reconnected."
                : GetString(root, "error") ??
                    "Reconnect failed.");
    }

    private async Task<ManagerOperationResult> TestAsync(
        string serviceId,
        CancellationToken cancellationToken)
    {
        using var document = await GetJsonAsync(
            "router/status",
            cancellationToken);

        if (!TryFindService(
                document.RootElement,
                serviceId,
                out var service))
        {
            return new ManagerOperationResult(
                false,
                "router.test",
                serviceId,
                "Service was not found.");
        }

        var rawUrl =
            GetString(service, "url") ?? "";

        if (!Uri.TryCreate(
                rawUrl,
                UriKind.Absolute,
                out var uri))
        {
            return new ManagerOperationResult(
                false,
                "router.test",
                serviceId,
                "Service URL is invalid.");
        }

        try
        {
            using var tcp = new TcpClient();
            using var timeout =
                CancellationTokenSource.CreateLinkedTokenSource(
                    cancellationToken);

            timeout.CancelAfter(
                TimeSpan.FromMilliseconds(1200));

            await tcp.ConnectAsync(
                uri.Host,
                uri.Port,
                timeout.Token);

            return new ManagerOperationResult(
                true,
                "router.test",
                serviceId,
                "Connection PASS (" +
                uri.Host +
                ":" +
                uri.Port +
                ").");
        }
        catch (Exception ex)
        {
            return new ManagerOperationResult(
                false,
                "router.test",
                serviceId,
                "Connection FAILED: " +
                ex.Message);
        }
    }

    private async Task<ManagerOperationResult> ToolsAsync(
        string serviceId,
        CancellationToken cancellationToken)
    {
        using var document = await GetJsonAsync(
            "router/service/" +
            Uri.EscapeDataString(serviceId) +
            "/tools",
            cancellationToken);

        var names = new List<string>();

        if (document.RootElement.TryGetProperty(
                "tools",
                out var tools) &&
            tools.ValueKind == JsonValueKind.Array)
        {
            foreach (var tool in tools.EnumerateArray())
            {
                var name =
                    GetString(tool, "name");

                if (!string.IsNullOrWhiteSpace(name))
                {
                    names.Add(name);
                }
            }
        }

        return new ManagerOperationResult(
            true,
            "router.tools",
            serviceId,
            names.Count == 0
                ? "No routed tools are currently exposed."
                : string.Join(
                    Environment.NewLine,
                    names.OrderBy(
                        item => item,
                        StringComparer.OrdinalIgnoreCase)));
    }

    private async Task<ManagerOperationResult> ReloadAsync(
        CancellationToken cancellationToken)
    {
        using var document =
            await PostJsonAsync(
                "router/refresh",
                cancellationToken);

        return new ManagerOperationResult(
            true,
            "router.reload",
            "tunnel",
            "Tunnel service list reloaded.");
    }

    private async Task<JsonDocument> GetJsonAsync(
        string relative,
        CancellationToken cancellationToken)
    {
        using var response =
            await _httpClient.GetAsync(
                new Uri(
                    _baseUri,
                    relative),
                cancellationToken);

        var body =
            await response.Content.ReadAsStringAsync(
                cancellationToken);

        response.EnsureSuccessStatusCode();

        return JsonDocument.Parse(body);
    }

    private async Task<JsonDocument> PostJsonAsync(
        string relative,
        CancellationToken cancellationToken)
    {
        using var response =
            await _httpClient.PostAsync(
                new Uri(
                    _baseUri,
                    relative),
                content: null,
                cancellationToken);

        var body =
            await response.Content.ReadAsStringAsync(
                cancellationToken);

        response.EnsureSuccessStatusCode();

        return JsonDocument.Parse(body);
    }

    private static ManagerAgentRow? FindAgent(
        string serviceNamespace,
        IReadOnlyList<ManagerAgentRow> agents)
    {
        var agentId =
            serviceNamespace.ToLowerInvariant() switch
            {
                "files" => "files.service",
                "web" => "web.service",
                "arcmap" => "arcmap.service",
                "qgis" => "qgis.service",
                _ => ""
            };

        return string.IsNullOrWhiteSpace(agentId)
            ? null
            : agents.FirstOrDefault(
                item =>
                    item.AgentId == agentId);
    }

    private static bool TryFindService(
        JsonElement root,
        string serviceId,
        out JsonElement service)
    {
        service = default;

        if (!root.TryGetProperty(
                "services",
                out var services) ||
            services.ValueKind != JsonValueKind.Array)
        {
            return false;
        }

        foreach (var item in services.EnumerateArray())
        {
            if (string.Equals(
                    GetString(item, "id"),
                    serviceId,
                    StringComparison.Ordinal))
            {
                service = item;
                return true;
            }
        }

        return false;
    }

    private static string? GetString(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(
                name,
                out var value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : value.ToString();
    }

    private static double? GetDouble(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(
                name,
                out var value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.Number &&
               value.TryGetDouble(out var number)
            ? number
            : null;
    }

    private static bool GetBool(
        JsonElement element,
        string name,
        bool fallback)
    {
        if (!element.TryGetProperty(
                name,
                out var value))
        {
            return fallback;
        }

        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => fallback
        };
    }

    private static int? GetInt(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(
                name,
                out var value))
        {
            return null;
        }

        return value.TryGetInt32(
            out var number)
            ? number
            : null;
    }

    private static DateTimeOffset? FromUnixSeconds(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(
                name,
                out var value) ||
            !value.TryGetDouble(
                out var seconds) ||
            seconds <= 0)
        {
            return null;
        }

        try
        {
            return DateTimeOffset
                .FromUnixTimeMilliseconds(
                    checked((long)(seconds * 1000)));
        }
        catch
        {
            return null;
        }
    }
}

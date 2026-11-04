using System.Globalization;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.Json.Nodes;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed class TunnelManagerReadModel
{
    private readonly HttpClient _httpClient;
    private readonly Uri _baseUri;
    private readonly string? _configRoot;
    private readonly SemaphoreSlim _configGate = new(1, 1);

    public TunnelManagerReadModel(
        Uri baseUri,
        HttpClient? httpClient = null,
        string? configRoot = null)
    {
        ArgumentNullException.ThrowIfNull(baseUri);

        if (!baseUri.IsLoopback)
        {
            throw new ArgumentException(
                "Tunnel Manager endpoint must be loopback.",
                nameof(baseUri));
        }

        _baseUri = new Uri(
            baseUri.GetLeftPart(UriPartial.Authority) + "/");
        _configRoot = string.IsNullOrWhiteSpace(configRoot)
            ? null
            : Path.GetFullPath(configRoot);
        _httpClient = httpClient ?? Zagent.Core.Manager.InternalManagementChannel.CreateClient(TimeSpan.FromSeconds(4));
    }

    public async Task<JsonElement> GetManagementWorkflowsAsync(string principalId, string workspaceId, string? runId,
        CancellationToken cancellationToken = default)
    {
        var path = "router/workflows" + (runId is null ? "" : "/" + Uri.EscapeDataString(runId)) +
            "?principal_id=" + Uri.EscapeDataString(principalId) + "&workspace_id=" + Uri.EscapeDataString(workspaceId) + "&limit=100";
        using var doc = await GetJsonAsync(path, cancellationToken);
        var safe = System.Text.Json.Nodes.JsonNode.Parse(doc.RootElement.GetRawText());
        RedactEvidence(safe);
        return JsonSerializer.SerializeToElement(safe);
    }
    private static void RedactEvidence(System.Text.Json.Nodes.JsonNode? node)
    {
        if (node is System.Text.Json.Nodes.JsonObject obj) {
            foreach (var key in obj.Select(x => x.Key).ToArray()) {
                if (key.Contains("token", StringComparison.OrdinalIgnoreCase) || key.Contains("secret", StringComparison.OrdinalIgnoreCase) ||
                    key.Contains("password", StringComparison.OrdinalIgnoreCase) || key is "arguments" or "execution_context" or "session_id" or "_meta" or "authorization")
                    obj.Remove(key);
                else RedactEvidence(obj[key]);
            }
        } else if (node is System.Text.Json.Nodes.JsonArray array) foreach (var child in array) RedactEvidence(child);
    }

    public async Task<ManagerMonitoringSnapshot> GetMonitoringAsync(
        int limit,
        CancellationToken cancellationToken = default)
    {
        using var tasks = await GetJsonAsync(
            "router/tasks?limit=" + Math.Clamp(limit, 1, 200),
            cancellationToken);

        var taskRows = ParseTasks(tasks.RootElement);

        var queueDepth = TryInt(tasks.RootElement, "queue_depth") ?? 0;
        var depths = new Dictionary<string, int>(StringComparer.Ordinal);
        if (tasks.RootElement.TryGetProperty("queue_depths", out var queueDepths) && queueDepths.ValueKind == JsonValueKind.Object)
            foreach (var property in queueDepths.EnumerateObject())
                if (property.Value.TryGetInt32(out var value)) depths[property.Name] = value;

        return new ManagerMonitoringSnapshot(taskRows, queueDepth, depths, DateTimeOffset.UtcNow);
    }

    public async Task<ManagerOperationResult> CancelTaskAsync(
        string taskId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(taskId);

        using var response = await _httpClient.PostAsync(
            new Uri(
                _baseUri,
                "router/tasks/" + Uri.EscapeDataString(taskId) + "/cancel"),
            content: null,
            cancellationToken);

        var body = await response.Content.ReadAsStringAsync(
            cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            return new ManagerOperationResult(
                false,
                "task.cancel",
                taskId,
                "HTTP " + (int)response.StatusCode + ": " + body);
        }

        try
        {
            using var document = JsonDocument.Parse(body);
            var ok =
                !document.RootElement.TryGetProperty(
                    "ok",
                    out var okElement) ||
                okElement.ValueKind != JsonValueKind.False;

            var state = TryString(
                document.RootElement,
                "state");

            var error = TryString(
                document.RootElement,
                "error");

            return new ManagerOperationResult(
                ok,
                "task.cancel",
                taskId,
                ok
                    ? "Cancel requested (" + (state ?? "accepted") + ")."
                    : error ?? "Cancel request rejected.");
        }
        catch (JsonException)
        {
            return new ManagerOperationResult(
                true,
                "task.cancel",
                taskId,
                body);
        }
    }

    public async Task<JsonDocument> GetRouterStatusAsync(
        CancellationToken cancellationToken = default) =>
        await GetJsonAsync(
            "router/status",
            cancellationToken);

    public async Task<ManagerRouterSnapshot> GetRouterSnapshotAsync(
        IReadOnlyList<ManagerAgentRow>? agents = null,
        CancellationToken cancellationToken = default)
    {
        using var document = await GetRouterStatusAsync(
            cancellationToken);

        var root = document.RootElement;
        var rows = new List<ManagerRouterServiceRow>();

        if (root.TryGetProperty(
                "services",
                out var services) &&
            services.ValueKind == JsonValueKind.Array)
        {
            foreach (var service in services.EnumerateArray())
            {
                var id = TryString(service, "id") ?? "";
                var ns = TryString(service, "namespace") ?? "";
                var enabled =
                    service.TryGetProperty(
                        "enabled",
                        out var enabledElement) &&
                    enabledElement.ValueKind != JsonValueKind.False;
                var initialized =
                    service.TryGetProperty(
                        "initialized",
                        out var initializedElement) &&
                    initializedElement.ValueKind == JsonValueKind.True;
                var permanent =
                    service.TryGetProperty(
                        "permanent",
                        out var permanentElement) &&
                    permanentElement.ValueKind == JsonValueKind.True;
                var lastError =
                    TryString(service, "last_error") ?? "";

                var agent = FindAgentForService(
                    ns,
                    agents);

                var agentStatus = agent is null
                    ? initialized
                        ? "Reachable"
                        : enabled
                            ? "Unknown"
                            : "Disabled"
                    : agent.ProcessState;

                var mcpStatus = !enabled
                    ? "Disabled"
                    : initialized
                        ? "Connected"
                        : string.IsNullOrWhiteSpace(lastError)
                            ? "Disconnected"
                            : "Error";

                rows.Add(
                    new ManagerRouterServiceRow(
                        id,
                        permanent ? "Core" : "Additional",
                        TryString(service, "name") ?? id,
                        ns,
                        TryString(service, "url") ?? "",
                        agentStatus,
                        mcpStatus,
                        enabled ? "Enabled" : "Disabled",
                        TryInt(service, "tools") ?? 0,
                        permanent,
                        enabled,
                        lastError));
            }
        }

        var toolCount =
            TryInt(root, "tool_count") ??
            TryInt(root, "upstream_tool_count") ??
            rows.Sum(item => item.Tools);

        var ready =
            !root.TryGetProperty("ok", out var ok) ||
            ok.ValueKind != JsonValueKind.False;

        return new ManagerRouterSnapshot(
            rows
                .OrderByDescending(item => item.Permanent)
                .ThenBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
                .ToArray(),
            toolCount,
            ready ? "Ready" : "Offline",
            DateTimeOffset.UtcNow);
    }

    public async Task<ManagerOperationResult> SetRoutingAsync(
        string serviceId,
        bool enabled,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serviceId);

        if (_configRoot is null)
        {
            return new ManagerOperationResult(
                false,
                enabled ? "router.enable" : "router.disable",
                serviceId,
                "Tunnel configuration root is unavailable.");
        }

        await _configGate.WaitAsync(cancellationToken);
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
                var services = root?["services"]?.AsArray();

                if (root is null || services is null)
                {
                    continue;
                }

                foreach (var node in services)
                {
                    if (node is not JsonObject service ||
                        !string.Equals(
                            service["id"]?.GetValue<string>(),
                            serviceId,
                            StringComparison.Ordinal))
                    {
                        continue;
                    }

                    service["enabled"] = enabled;

                    var temporary = path + ".manager.tmp";
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
                    enabled ? "router.enable" : "router.disable",
                    serviceId,
                    "Service was not found in Tunnel configuration.");
            }
        }
        finally
        {
            _configGate.Release();
        }

        using var refresh = await PostJsonAsync(
            "router/refresh",
            cancellationToken);

        return new ManagerOperationResult(
            true,
            enabled ? "router.enable" : "router.disable",
            serviceId,
            enabled
                ? "Routing enabled and service list reloaded."
                : "Routing disabled and service list reloaded.");
    }

    public async Task<ManagerOperationResult> ReconnectServiceAsync(
        string serviceId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serviceId);

        using var document = await PostJsonAsync(
            "router/service/" + Uri.EscapeDataString(serviceId) + "/refresh",
            cancellationToken);

        var root = document.RootElement;
        var ok =
            !root.TryGetProperty("ok", out var okElement) ||
            okElement.ValueKind != JsonValueKind.False;

        return new ManagerOperationResult(
            ok,
            "router.reconnect",
            serviceId,
            ok
                ? "MCP service reconnected."
                : TryString(root, "error") ?? "Reconnect failed.");
    }

    public async Task<ManagerOperationResult> TestServiceAsync(
        string serviceId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serviceId);

        using var status = await GetRouterStatusAsync(
            cancellationToken);

        if (!status.RootElement.TryGetProperty(
                "services",
                out var services) ||
            services.ValueKind != JsonValueKind.Array)
        {
            return new ManagerOperationResult(
                false,
                "router.test",
                serviceId,
                "Router service list is unavailable.");
        }

        JsonElement? selected = null;
        foreach (var item in services.EnumerateArray())
        {
            if (string.Equals(
                    TryString(item, "id"),
                    serviceId,
                    StringComparison.Ordinal))
            {
                selected = item;
                break;
            }
        }

        if (selected is null)
        {
            return new ManagerOperationResult(
                false,
                "router.test",
                serviceId,
                "Service was not found.");
        }

        var url = TryString(selected.Value, "url");
        if (!Uri.TryCreate(
                url,
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
                "Connection PASS (" + uri.Host + ":" + uri.Port + ").");
        }
        catch (Exception ex)
        {
            return new ManagerOperationResult(
                false,
                "router.test",
                serviceId,
                "Connection FAILED: " + ex.Message);
        }
    }

    public async Task<ManagerOperationResult> GetServiceToolsAsync(
        string serviceId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serviceId);

        using var document = await GetJsonAsync(
            "router/service/" + Uri.EscapeDataString(serviceId) + "/tools",
            cancellationToken);

        var root = document.RootElement;
        var names = new List<string>();

        if (root.TryGetProperty(
                "tools",
                out var tools) &&
            tools.ValueKind == JsonValueKind.Array)
        {
            foreach (var tool in tools.EnumerateArray())
            {
                var name = TryString(tool, "name");
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

    public async Task<ManagerOperationResult> ReloadRouterAsync(
        CancellationToken cancellationToken = default)
    {
        using var document = await PostJsonAsync(
            "router/refresh",
            cancellationToken);

        return new ManagerOperationResult(
            true,
            "router.reload",
            "tunnel",
            "Tunnel service list reloaded.");
    }

    private static ManagerAgentRow? FindAgentForService(
        string serviceNamespace,
        IReadOnlyList<ManagerAgentRow>? agents)
    {
        if (agents is null)
        {
            return null;
        }

        var agentId = serviceNamespace.ToLowerInvariant() switch
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
                item => item.AgentId == agentId);
    }

    private async Task<JsonDocument> GetJsonAsync(
        string relative,
        CancellationToken cancellationToken)
    {
        using var response = await _httpClient.GetAsync(
            new Uri(_baseUri, relative),
            cancellationToken);

        var body = await response.Content.ReadAsStringAsync(
            cancellationToken);

        response.EnsureSuccessStatusCode();
        return JsonDocument.Parse(body);
    }

    private async Task<JsonDocument> PostJsonAsync(
        string relative,
        CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsync(
            new Uri(_baseUri, relative),
            content: null,
            cancellationToken);

        var body = await response.Content.ReadAsStringAsync(
            cancellationToken);

        response.EnsureSuccessStatusCode();
        return JsonDocument.Parse(body);
    }


    private static IReadOnlyList<ManagerTaskRow> ParseTasks(JsonElement root)
    {
        var result = new List<ManagerTaskRow>();

        if (!root.TryGetProperty(
                "tasks",
                out var tasks) ||
            tasks.ValueKind != JsonValueKind.Array)
        {
            return result;
        }

        foreach (var item in tasks.EnumerateArray())
        {
            var taskId = TryString(item, "task_id") ?? "";
            var state = TryString(item, "state") ?? "";

            var accessMode =
                TryString(item, "access_mode") ?? "read";
            var tool =
                TryString(item, "tool_name") ?? "";
            var service =
                TryString(item, "service_id") ?? "";
            var resource =
                TryString(item, "resource_key") ?? "";
            var progress =
                TryDouble(item, "progress") ?? 0;
            var priority =
                TryInt(item, "priority") ?? 0;

            var terminal =
                state is "succeeded" or
                    "failed" or
                    "cancelled";

            var running =
                state is "running" or
                    "waiting_capacity" or
                    "waiting_lock" or
                    "queued" or
                    "recovering" or
                    "cancelling";

            var cancellable =
                !terminal &&
                !string.IsNullOrWhiteSpace(taskId);

            var isWrite =
                accessMode.Equals(
                    "write",
                    StringComparison.OrdinalIgnoreCase) ||
                accessMode.Equals(
                    "admin",
                    StringComparison.OrdinalIgnoreCase);

            var destructive =
                tool.Contains(
                    "delete",
                    StringComparison.OrdinalIgnoreCase) ||
                tool.Contains(
                    "remove",
                    StringComparison.OrdinalIgnoreCase) ||
                tool.Contains(
                    "stop",
                    StringComparison.OrdinalIgnoreCase) ||
                tool.Contains(
                    "rollback",
                    StringComparison.OrdinalIgnoreCase);

            var risk = destructive
                ? "HIGH"
                : isWrite
                    ? "WRITE"
                    : "READ";

            var stopMode = !cancellable
                ? "TERMINAL"
                : running
                    ? "COOPERATIVE/BEST-EFFORT"
                    : "PRE-DISPATCH";

            var details = "";
            if (item.TryGetProperty(
                    "arguments",
                    out var arguments))
            {
                details = arguments.ToString();
            }


            result.Add(
                new ManagerTaskRow(
                    taskId,
                    TryString(item, "principal_id") ?? "",
                    TryString(item, "workspace_id") ?? "",
                    TryString(item, "request_id") ?? "",
                    service,
                    tool,
                    state,
                    progress,
                    accessMode,
                    priority,
                    resource,
                    TryDouble(item, "created_at"),
                    TryDouble(item, "started_at"),
                    TryDouble(item, "finished_at"),
                    stopMode,
                    cancellable,
                    isWrite,
                    destructive,
                    risk,
                    details));
        }

        return result
            .OrderByDescending(
                item =>
                    item.StartedAt ??
                    item.CreatedAt ??
                    0)
            .ToArray();
    }

    private static string? TryString(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : value.ToString();
    }

    private static double? TryDouble(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return null;
        }

        if (value.ValueKind == JsonValueKind.Number &&
            value.TryGetDouble(out var number))
        {
            return number;
        }

        if (value.ValueKind == JsonValueKind.Null ||
            value.ValueKind == JsonValueKind.Undefined)
        {
            return null;
        }

        if (value.ValueKind == JsonValueKind.String &&
            double.TryParse(
                value.GetString(),
                NumberStyles.Float,
                CultureInfo.InvariantCulture,
                out number))
        {
            return number;
        }

        return null;
    }

    private static int? TryInt(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return null;
        }

        if (value.TryGetInt32(out var number))
        {
            return number;
        }

        return null;
    }
}

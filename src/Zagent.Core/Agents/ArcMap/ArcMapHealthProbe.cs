using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace Zagent.Core.Agents.ArcMap;

public sealed class ArcMapHealthProbe
{
    private readonly HttpClient _httpClient;

    public ArcMapHealthProbe(
        HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? Zagent.Core.Manager.InternalManagementChannel.CreateClient(TimeSpan.FromSeconds(5));
    }

    public async Task<ArcMapHealthSnapshot> ProbeAsync(
        Uri mcpUri,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(mcpUri);

        if (!mcpUri.IsLoopback)
        {
            throw new ArgumentException(
                "ArcMap MCP endpoint must be loopback.",
                nameof(mcpUri));
        }

        try
        {
            using var initialized = await RpcAsync(
                mcpUri,
                new
                {
                    jsonrpc = "2.0",
                    id = "arcmap-health-init",
                    method = "initialize",
                    @params = new
                    {
                        protocolVersion = "2025-06-18",
                        capabilities = new { },
                        clientInfo = new
                        {
                            name = "Zagent Core ArcMap Health",
                            version = "1.0"
                        }
                    }
                },
                cancellationToken);

            if (!initialized.RootElement.TryGetProperty(
                    "result",
                    out var initResult))
            {
                return Failed(
                    initialized.RootElement.ToString());
            }

            string? serverName = null;
            string? protocol = null;

            if (initResult.TryGetProperty(
                    "protocolVersion",
                    out var protocolElement))
            {
                protocol = protocolElement.GetString();
            }

            if (initResult.TryGetProperty(
                    "serverInfo",
                    out var serverInfo) &&
                serverInfo.TryGetProperty(
                    "name",
                    out var nameElement))
            {
                serverName = nameElement.GetString();
            }

            using var toolsResult = await RpcAsync(
                mcpUri,
                new
                {
                    jsonrpc = "2.0",
                    id = "arcmap-health-tools",
                    method = "tools/list",
                    @params = new { }
                },
                cancellationToken);

            var toolNames = toolsResult.RootElement
                .GetProperty("result")
                .GetProperty("tools")
                .EnumerateArray()
                .Select(
                    item =>
                        item.GetProperty("name").GetString() ?? "")
                .Where(
                    name =>
                        !string.IsNullOrWhiteSpace(name))
                .ToArray();

            var toolCount = toolNames.Length;
            var stage2Loaded =
                toolNames.Count(
                    name =>
                        name.StartsWith(
                            "arcmap_stage2_",
                            StringComparison.Ordinal)) == 8;
            var stage3Loaded =
                toolNames.Count(
                    name =>
                        name.StartsWith(
                            "arcmap_stage3_",
                            StringComparison.Ordinal)) == 20;

            var bridgeReady = false;
            string? arcGisVersion = null;
            string? currentMxd = null;
            string? bridgeError = null;

            try
            {
                using var ping = await RpcAsync(
                    mcpUri,
                    new
                    {
                        jsonrpc = "2.0",
                        id = "arcmap-health-ping",
                        method = "tools/call",
                        @params = new
                        {
                            name = "arcmap_ping",
                            arguments = new { }
                        }
                    },
                    cancellationToken);

                if (ping.RootElement.TryGetProperty(
                        "result",
                        out var result))
                {
                    var isError =
                        result.TryGetProperty(
                            "isError",
                            out var isErrorElement) &&
                        isErrorElement.ValueKind ==
                            JsonValueKind.True;

                    var text = ExtractToolText(result);
                    bridgeReady =
                        !isError &&
                        text.Contains(
                            "ARCMAP_AGENT_OK",
                            StringComparison.Ordinal);

                    arcGisVersion =
                        FindStringProperty(
                            text,
                            "arcgis_version");
                    currentMxd =
                        FindStringProperty(
                            text,
                            "mxd");

                    if (!bridgeReady)
                    {
                        bridgeError = text;
                    }
                }
            }
            catch (Exception ex)
                when (ex is HttpRequestException or
                    TaskCanceledException or
                    JsonException or
                    InvalidDataException)
            {
                bridgeError = ex.Message;
            }

            return new ArcMapHealthSnapshot(
                McpReady: true,
                BridgeReady: bridgeReady,
                ToolCount: toolCount,
                Stage2Loaded: stage2Loaded,
                Stage3Loaded: stage3Loaded,
                ArcGisVersion: arcGisVersion,
                CurrentMxd: currentMxd,
                ServerName: serverName,
                ProtocolVersion: protocol,
                Error: bridgeReady
                    ? null
                    : bridgeError);
        }
        catch (Exception ex)
            when (ex is HttpRequestException or
                TaskCanceledException or
                JsonException or
                InvalidDataException or
                KeyNotFoundException)
        {
            return Failed(ex.Message);
        }
    }

    private ArcMapHealthSnapshot Failed(
        string? error) =>
        new(
            McpReady: false,
            BridgeReady: false,
            ToolCount: 0,
            Stage2Loaded: false,
            Stage3Loaded: false,
            ArcGisVersion: null,
            CurrentMxd: null,
            ServerName: null,
            ProtocolVersion: null,
            Error: error);

    private async Task<JsonDocument> RpcAsync(
        Uri uri,
        object payload,
        CancellationToken cancellationToken)
    {
        var json = JsonSerializer.Serialize(payload);

        using var request = new HttpRequestMessage(
            HttpMethod.Post,
            uri);

        request.Content = new StringContent(
            json,
            Encoding.UTF8,
            "application/json");

        request.Headers.Accept.Add(
            new MediaTypeWithQualityHeaderValue(
                "application/json"));
        request.Headers.Accept.Add(
            new MediaTypeWithQualityHeaderValue(
                "text/event-stream"));
        request.Headers.TryAddWithoutValidation(
            "MCP-Protocol-Version",
            "2025-06-18");

        using var response = await _httpClient.SendAsync(
            request,
            cancellationToken);

        var body = await response.Content.ReadAsStringAsync(
            cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException(
                $"HTTP {(int)response.StatusCode}: {body}");
        }

        return ParsePayload(
            body,
            response.Content.Headers.ContentType?.MediaType);
    }

    private static JsonDocument ParsePayload(
        string body,
        string? mediaType)
    {
        if ((!string.IsNullOrWhiteSpace(mediaType) &&
                mediaType.Contains(
                    "text/event-stream",
                    StringComparison.OrdinalIgnoreCase)) ||
            body.TrimStart().StartsWith(
                "event:",
                StringComparison.Ordinal))
        {
            var payloads = body
                .Split(
                    new[] { "\r\n", "\n" },
                    StringSplitOptions.None)
                .Where(
                    line =>
                        line.StartsWith(
                            "data:",
                            StringComparison.Ordinal))
                .Select(line => line[5..].Trim())
                .Where(
                    line =>
                        !string.IsNullOrWhiteSpace(line) &&
                        line != "[DONE]")
                .ToArray();

            if (payloads.Length == 0)
            {
                throw new InvalidDataException(
                    "ArcMap MCP SSE response contained no JSON payload.");
            }

            return JsonDocument.Parse(payloads[^1]);
        }

        return JsonDocument.Parse(body);
    }

    private static string ExtractToolText(
        JsonElement result)
    {
        if (result.TryGetProperty(
                "structuredContent",
                out var structured) &&
            structured.ValueKind is not
                JsonValueKind.Null and not
                JsonValueKind.Undefined)
        {
            return structured.ToString();
        }

        if (result.TryGetProperty(
                "content",
                out var content) &&
            content.ValueKind == JsonValueKind.Array)
        {
            var texts = content
                .EnumerateArray()
                .Where(
                    item =>
                        item.TryGetProperty(
                            "text",
                            out _))
                .Select(
                    item =>
                        item.GetProperty("text").GetString() ?? "")
                .Where(
                    text =>
                        !string.IsNullOrWhiteSpace(text))
                .ToArray();

            if (texts.Length > 0)
            {
                return string.Join("\n", texts);
            }
        }

        return result.ToString();
    }

    private static string? FindStringProperty(
        string jsonText,
        string propertyName)
    {
        try
        {
            using var document = JsonDocument.Parse(jsonText);
            return FindStringPropertyInElement(
                document.RootElement,
                propertyName);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static string? FindStringPropertyInElement(
        JsonElement element,
        string propertyName)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in element.EnumerateObject())
            {
                if (string.Equals(
                        property.Name,
                        propertyName,
                        StringComparison.Ordinal))
                {
                    return property.Value.ValueKind ==
                        JsonValueKind.String
                        ? property.Value.GetString()
                        : property.Value.ToString();
                }

                var nested = FindStringPropertyInElement(
                    property.Value,
                    propertyName);

                if (nested is not null)
                {
                    return nested;
                }
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in element.EnumerateArray())
            {
                var nested = FindStringPropertyInElement(
                    item,
                    propertyName);

                if (nested is not null)
                {
                    return nested;
                }
            }
        }
        else if (element.ValueKind == JsonValueKind.String)
        {
            var raw = element.GetString();

            if (!string.IsNullOrWhiteSpace(raw))
            {
                try
                {
                    using var nestedDocument =
                        JsonDocument.Parse(raw);

                    return FindStringPropertyInElement(
                        nestedDocument.RootElement,
                        propertyName);
                }
                catch (JsonException)
                {
                }
            }
        }

        return null;
    }
}

using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace Zagent.Core.Agents.Files;

public sealed class FilesHealthProbe
{
    private readonly HttpClient _httpClient;

    public FilesHealthProbe(HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? Zagent.Core.Manager.InternalManagementChannel.CreateClient(TimeSpan.FromSeconds(4));
    }

    public async Task<FilesHealthSnapshot> ProbeAsync(
        Uri mcpUri,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(mcpUri);

        if (!mcpUri.IsLoopback)
        {
            throw new ArgumentException(
                "Files MCP endpoint must be loopback.",
                nameof(mcpUri));
        }

        try
        {
            var payload = JsonSerializer.Serialize(
                new
                {
                    jsonrpc = "2.0",
                    id = "health",
                    method = "initialize",
                    @params = new
                    {
                        protocolVersion = "2025-06-18",
                        capabilities = new { },
                        clientInfo = new
                        {
                            name = "Zagent Core Health",
                            version = "1.0"
                        }
                    }
                });

            using var request = new HttpRequestMessage(
                HttpMethod.Post,
                mcpUri);

            request.Content = new StringContent(
                payload,
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
                return new FilesHealthSnapshot(
                    false,
                    null,
                    null,
                    null,
                    $"HTTP {(int)response.StatusCode}: {body}");
            }

            using var document = ParsePayload(
                body,
                response.Content.Headers.ContentType?.MediaType);

            var root = document.RootElement;

            if (!root.TryGetProperty("result", out var result))
            {
                return new FilesHealthSnapshot(
                    false,
                    null,
                    null,
                    null,
                    root.ToString());
            }

            var protocol = result.TryGetProperty(
                    "protocolVersion",
                    out var protocolElement)
                ? protocolElement.GetString()
                : null;

            string? name = null;
            string? version = null;

            if (result.TryGetProperty(
                    "serverInfo",
                    out var serverInfo))
            {
                if (serverInfo.TryGetProperty(
                        "name",
                        out var nameElement))
                {
                    name = nameElement.GetString();
                }

                if (serverInfo.TryGetProperty(
                        "version",
                        out var versionElement))
                {
                    version = versionElement.GetString();
                }
            }

            return new FilesHealthSnapshot(
                true,
                name,
                version,
                protocol,
                null);
        }
        catch (Exception ex)
            when (ex is HttpRequestException or
                TaskCanceledException or
                JsonException or
                InvalidDataException)
        {
            return new FilesHealthSnapshot(
                false,
                null,
                null,
                null,
                ex.Message);
        }
    }

    private static JsonDocument ParsePayload(
        string body,
        string? mediaType)
    {
        if (!string.IsNullOrWhiteSpace(mediaType) &&
                mediaType.Contains(
                    "text/event-stream",
                    StringComparison.OrdinalIgnoreCase) ||
            body.TrimStart().StartsWith(
                "event:",
                StringComparison.Ordinal))
        {
            var payloads = body
                .Split(
                    new[] { "\r\n", "\n" },
                    StringSplitOptions.None)
                .Where(
                    line => line.StartsWith(
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
                    "MCP SSE response had no JSON data payload.");
            }

            return JsonDocument.Parse(payloads[^1]);
        }

        return JsonDocument.Parse(body);
    }
}

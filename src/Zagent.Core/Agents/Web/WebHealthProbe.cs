using System.Text.Json;

namespace Zagent.Core.Agents.Web;

public sealed class WebHealthProbe
{
    private readonly HttpClient _httpClient;

    public WebHealthProbe(
        HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? Zagent.Core.Manager.InternalManagementChannel.CreateClient(TimeSpan.FromSeconds(4));
    }

    public async Task<WebHealthSnapshot> ProbeAsync(
        Uri healthUri,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(healthUri);

        if (!healthUri.IsLoopback)
        {
            throw new ArgumentException(
                "Web health endpoint must be loopback.",
                nameof(healthUri));
        }

        try
        {
            using var response = await _httpClient.GetAsync(
                healthUri,
                cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                return new WebHealthSnapshot(
                    false,
                    null,
                    null,
                    false,
                    false,
                    false,
                    false,
                    $"HTTP {(int)response.StatusCode}");
            }

            using var document =
                await JsonDocument.ParseAsync(
                    await response.Content.ReadAsStreamAsync(
                        cancellationToken),
                    cancellationToken: cancellationToken);

            var root = document.RootElement;

            var service = TryString(root, "service");
            var version = TryString(root, "version");

            var nativeAttached =
                TryBoolean(root, "nativeAttached") ||
                TryBoolean(root, "native_attached");

            var bridgeRequired =
                TryBoolean(root, "bridgeRequired") ||
                TryBoolean(root, "bridge_required");

            var bridgeConnected = false;
            var bridgeAuthorized = false;

            if (root.TryGetProperty(
                    "bridge",
                    out var bridge) &&
                bridge.ValueKind == JsonValueKind.Object)
            {
                bridgeRequired =
                    bridgeRequired ||
                    TryBoolean(bridge, "required");
                bridgeConnected =
                    TryBoolean(bridge, "connected");
                bridgeAuthorized =
                    TryBoolean(bridge, "authorized");
            }

            var ready =
                !root.TryGetProperty("ok", out var ok) ||
                ok.ValueKind != JsonValueKind.False;

            return new WebHealthSnapshot(
                ready,
                service,
                version,
                nativeAttached,
                bridgeRequired,
                bridgeConnected,
                bridgeAuthorized,
                null);
        }
        catch (Exception ex)
            when (ex is HttpRequestException or
                TaskCanceledException or
                JsonException)
        {
            return new WebHealthSnapshot(
                false,
                null,
                null,
                false,
                false,
                false,
                false,
                ex.Message);
        }
    }

    private static string? TryString(
        JsonElement element,
        string property) =>
        element.TryGetProperty(
            property,
            out var value) &&
        value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static bool TryBoolean(
        JsonElement element,
        string property) =>
        element.TryGetProperty(
            property,
            out var value) &&
        value.ValueKind == JsonValueKind.True;
}

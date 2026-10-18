using System.Net.Http.Json;
using System.Text.Json;

namespace Zagent.Core.Agents.Tunnel;

public sealed class TunnelRouterHealthProbe
{
    private readonly HttpClient _httpClient;

    public TunnelRouterHealthProbe(
        HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? Zagent.Core.Manager.InternalManagementChannel.CreateClient(TimeSpan.FromSeconds(3));
    }

    public async Task<TunnelRouterHealthSnapshot> ProbeAsync(
        Uri healthUri,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(healthUri);

        if (!healthUri.IsLoopback)
        {
            throw new ArgumentException(
                "Tunnel health endpoint must be loopback.",
                nameof(healthUri));
        }

        try
        {
            using var response = await _httpClient.GetAsync(
                healthUri,
                cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                return new TunnelRouterHealthSnapshot(
                    Ready: false,
                    Version: null,
                    ToolCount: 0,
                    PluginConfigured: false,
                    PluginConnected: false,
                    Error: $"HTTP {(int)response.StatusCode}");
            }

            using var document =
                await JsonDocument.ParseAsync(
                    await response.Content.ReadAsStreamAsync(
                        cancellationToken),
                    cancellationToken: cancellationToken);

            var root = document.RootElement;
            var toolCount = root.TryGetProperty(
                    "tool_count",
                    out var toolCountElement)
                ? toolCountElement.GetInt32()
                : 0;

            var pluginConfigured = false;
            var pluginConnected = false;

            if (root.TryGetProperty(
                    "plugin",
                    out var plugin))
            {
                pluginConfigured =
                    plugin.TryGetProperty(
                        "configured",
                        out var configured) &&
                    configured.GetBoolean();

                pluginConnected =
                    plugin.TryGetProperty(
                        "connected",
                        out var connected) &&
                    connected.GetBoolean();
            }

            return new TunnelRouterHealthSnapshot(
                Ready: true,
                Version: "4.1.0-zagent.1",
                ToolCount: toolCount,
                PluginConfigured: pluginConfigured,
                PluginConnected: pluginConnected,
                Error: null);
        }
        catch (Exception ex)
            when (ex is HttpRequestException or
                TaskCanceledException or
                JsonException)
        {
            return new TunnelRouterHealthSnapshot(
                Ready: false,
                Version: null,
                ToolCount: 0,
                PluginConfigured: false,
                PluginConnected: false,
                Error: ex.Message);
        }
    }
}

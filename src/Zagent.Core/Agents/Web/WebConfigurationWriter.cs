using System.Text.Json.Nodes;
using Zagent.Core.Configuration;

namespace Zagent.Core.Agents.Web;

public sealed class WebConfigurationWriter
{
    private readonly AtomicJsonFileStore _store;

    public WebConfigurationWriter(
        AtomicJsonFileStore? store = null)
    {
        _store = store ?? new AtomicJsonFileStore();
    }

    public async Task WriteAsync(
        WebIntegrationOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);
        Validate(options);

        Directory.CreateDirectory(options.DataRoot);
        Directory.CreateDirectory(options.ConfigRoot);
        Directory.CreateDirectory(options.RuntimeRoot);
        Directory.CreateDirectory(options.ArtifactsRoot);
        Directory.CreateDirectory(options.LogRoot);

        var settings = new JsonObject
        {
            ["host"] = options.BindHost,
            ["port"] = options.Port,
            ["browser"] = options.Browser,
            ["headless"] = false,
            ["autoStartBrowser"] = false,
            ["autoRestartBrowser"] = false,
            ["runtimeMode"] = options.RuntimeMode,
            ["nativeAutoAttach"] = options.NativeAutoAttach,
            ["nativeAttachOnDemand"] = options.NativeAttachOnDemand,
            ["bridgeEnvironment"] = options.BridgeEnvironment,
            ["bridgeEndpoint"] = $"http://{options.BindHost}:{options.Port}/bridge/",
            ["chromeExecutablePath"] =
                string.IsNullOrWhiteSpace(options.ChromeExecutablePath)
                    ? null
                    : Path.GetFullPath(options.ChromeExecutablePath),
            ["sessionIsolationMode"] = options.SessionIsolationMode,
            ["sessionInheritProfileState"] = false,
            ["cdpEndpoint"] = "",
            ["defaultViewport"] = new JsonObject
            {
                ["width"] = 1440,
                ["height"] = 900
            },
            ["allowedHosts"] = new JsonArray(
                "localhost",
                "127.0.0.1",
                options.BindHost,
                "::1",
                "supabase.com",
                "web.whatsapp.com",
                "google.com",
                "accounts.google.com",
                "mail.google.com",
                "drive.google.com",
                "vercel.com"),
            ["allowExternalHosts"] = false,
            ["navigationTimeoutMs"] = 30000,
            ["actionTimeoutMs"] = 10000,
            ["screenshotsDir"] = "artifacts/screenshots",
            ["downloadsDir"] = "artifacts/downloads",
            ["tracesDir"] = "artifacts/traces",
            ["harDir"] = "artifacts/har",
            ["recordingsDir"] = "artifacts/recordings",
            ["videosDir"] = "artifacts/videos",
            ["logsDir"] = "logs",
            ["enableJavascriptEvaluation"] = true,
            ["enableNetworkInterception"] = true,
            ["maxNetworkEvents"] = 2000,
            ["maxConsoleEvents"] = 2000,
            ["redactHeaders"] = new JsonArray(
                "authorization",
                "proxy-authorization",
                "cookie",
                "set-cookie",
                "x-api-key")
        };

        var targets = new JsonObject
        {
            ["targets"] = new JsonArray()
        };

        var bridgePath = Path.Combine(
            options.ConfigRoot,
            "bridge.json");

        JsonObject bridge;

        if (File.Exists(bridgePath))
        {
            try
            {
                var raw = await File.ReadAllTextAsync(
                    bridgePath,
                    cancellationToken);

                bridge =
                    JsonNode.Parse(raw) as JsonObject ??
                    new JsonObject();
            }
            catch
            {
                bridge = new JsonObject();
            }
        }
        else
        {
            bridge = new JsonObject();
        }

        bridge["required"] =
            options.BridgeRequired;
        bridge["environment"] =
            options.BridgeEnvironment;
        bridge["endpoint"] =
            $"http://{options.BindHost}:{options.Port}/bridge/";

        await _store.SaveAsync(
            Path.Combine(options.ConfigRoot, "settings.json"),
            settings,
            cancellationToken);

        await _store.SaveAsync(
            Path.Combine(options.ConfigRoot, "targets.json"),
            targets,
            cancellationToken);

        await _store.SaveAsync(
            Path.Combine(options.ConfigRoot, "bridge.json"),
            bridge,
            cancellationToken);
    }

    private static void Validate(
        WebIntegrationOptions options)
    {
        if (!File.Exists(options.NodeExecutable))
        {
            throw new FileNotFoundException(
                "Web Node.js runtime was not found.",
                options.NodeExecutable);
        }

        if (!Directory.Exists(options.EngineRoot))
        {
            throw new DirectoryNotFoundException(
                $"Web engine root was not found: {options.EngineRoot}");
        }

        if (!File.Exists(
                Path.Combine(
                    options.EngineRoot,
                    "dist",
                    "index.js")))
        {
            throw new FileNotFoundException(
                "Compiled Zagent Web entrypoint was not found.",
                Path.Combine(
                    options.EngineRoot,
                    "dist",
                    "index.js"));
        }

        if (options.Port is < 1 or > 65535)
        {
            throw new ArgumentOutOfRangeException(
                nameof(options),
                "Web port is invalid.");
        }

        if (!IsLoopback(options.BindHost))
        {
            throw new ArgumentException(
                "Web bind host must be loopback.",
                nameof(options));
        }

        if (options.BridgeEnvironment is not ("DEVELOPMENT" or "PRODUCTION"))
        {
            throw new ArgumentException(
                "Chrome Bridge environment must be DEVELOPMENT or PRODUCTION.",
                nameof(options));
        }

        if (options.RuntimeMode is not ("native_attach" or "managed"))
        {
            throw new ArgumentException(
                "Web runtime mode is invalid.",
                nameof(options));
        }

        if (options.SessionIsolationMode is not ("auto" or "context" or "tabs"))
        {
            throw new ArgumentException(
                "Web session isolation mode is invalid.",
                nameof(options));
        }

        if (!string.IsNullOrWhiteSpace(options.ChromeExecutablePath) &&
            !File.Exists(options.ChromeExecutablePath))
        {
            throw new FileNotFoundException(
                "Configured Chrome executable was not found.",
                options.ChromeExecutablePath);
        }
    }

    private static bool IsLoopback(string host) =>
        string.Equals(
            host,
            "localhost",
            StringComparison.OrdinalIgnoreCase) ||
        (System.Net.IPAddress.TryParse(host, out var ip) &&
            System.Net.IPAddress.IsLoopback(ip));
}

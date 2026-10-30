using Zagent.Core.Supervision;

namespace Zagent.Core.Agents.Tunnel;

public static class TunnelProcessFactory
{
    public const string RouterProcessId = "system.tunnel.router";
    public const string TransportProcessId = "system.tunnel.transport";

    public static AgentProcessDefinition CreateRouter(
        TunnelIntegrationOptions options)
    {
        ValidateRouterOptions(options);

        return new AgentProcessDefinition(
            AgentId: RouterProcessId,
            ExecutablePath: Path.GetFullPath(options.PythonExecutable),
            Arguments:
            [
                "-m",
                "router.server"
            ],
            WorkingDirectory: Path.GetFullPath(options.EngineRoot),
            EnvironmentVariables: new Dictionary<string, string>(
                StringComparer.Ordinal)
            {
                ["ZAGENT_CORE_DATA_ROOT"] = string.IsNullOrWhiteSpace(options.CoreDataRoot)
                    ? "" : Path.GetFullPath(options.CoreDataRoot),
                ["ZAGENT_TUNNEL_CONFIG_DIR"] =
                    Path.GetFullPath(options.ConfigRoot),
                ["ZAGENT_TUNNEL_RUNTIME_DIR"] =
                    Path.GetFullPath(options.RuntimeRoot),
                ["ZAGENT_CHAT_LOG_PATH"] =
                    Path.GetFullPath(options.ChatLogPath),
                // Managed resource_server is read after preparation; never use ambient secrets.
                [Zagent.Core.Manager.OAuthIntrospectionCredentialStore.EnvironmentName] =
                    options.OAuthCredentialDataRoot is null ? "" :
                    Zagent.Core.Manager.OAuthIntrospectionCredentialStore.LoadOptional(
                        options.OAuthCredentialDataRoot, options.ConfigRoot) ?? "",
                ["ZAGENT_DEVICE_ID"] = options.DeviceId,
                ["ZAGENT_DEVICE_NAME"] = options.DeviceName,
                ["ZAGENT_DEVICE_ALIAS"] = options.DeviceAlias,
                ["ZAGENT_INTERNAL_TOKEN"] =
                    Zagent.Core.Manager.InternalManagementChannel.GetChildSecret("ZAGENT_INTERNAL_TOKEN"),
                ["ZAGENT_INTERNAL_CONTEXT_KEY"] =
                    Zagent.Core.Manager.InternalManagementChannel.GetChildSecret("ZAGENT_INTERNAL_CONTEXT_KEY"),
                ["ZAGENT_DEVICE_FINGERPRINT"] = options.DeviceFingerprint,
                ["ZAGENT_INSTALLATION_ID"] = options.InstallationId,
                ["ZAGENT_DEVICE_BINDING"] = options.DeviceBinding,
                ["ZAGENT_IDENTITY_ENFORCEMENT"] = options.IdentityEnforcement,
                ["CONTROL_PLANE_TUNNEL_ID"] = options.ControlPlaneTunnelId,
                ["CONTROL_PLANE_API_KEY"] = options.ControlPlaneApiKey,
                ["ZAGENT_PLUGIN_AUDIENCE"] = options.PluginAudience,
                ["ZAGENT_PLUGIN_DISPLAY_NAME"] = options.PluginDisplayName,
                ["ZAGENT_PRODUCTION_ARCMAP_MCP_URL"] = options.ArcMapMcpUrl,
                ["ZAGENT_PLUGIN_ACCESS_MODE"] = options.PluginAccessMode,
                ["ZAGENT_PLUGIN_ACCESS_ROOT"] =
                    string.IsNullOrWhiteSpace(options.PluginAccessRoot)
                        ? Path.Combine(
                            Path.GetFullPath(options.RuntimeRoot),
                            "plugin-access")
                        : Path.GetFullPath(options.PluginAccessRoot),
                ["ZAGENT_PLUGIN_ACCESS_ENFORCEMENT"] = options.PluginAccessEnforcement,
                ["ZAGENT_PLUGIN_FALLBACK"] = options.PluginFallback,
                ["ZAGENT_PLUGIN_PARENT_AUDIENCE"] = options.PluginParentAudience,
                ["PYTHONUNBUFFERED"] = "1"
            },
            GracefulShutdownSeconds: 3,
            AutoRestart: true,
            MaxRestartAttempts: 3,
            RestartBackoffMilliseconds: 250,
            RestartBackoffMaxMilliseconds: 2000,
            HealthRestartGraceMilliseconds: 10000);
    }

    public static AgentProcessDefinition CreateTransport(
        TunnelTransportOptions options)
    {
        ValidateTransportOptions(options);

        return new AgentProcessDefinition(
            AgentId: TransportProcessId,
            ExecutablePath: Path.GetFullPath(options.ClientExecutable),
            Arguments:
            [
                "run",
                "--log.level=info",
                "--log.format=struct-text"
            ],
            WorkingDirectory: Path.GetFullPath(options.WorkingDirectory),
            EnvironmentVariables: new Dictionary<string, string>(
                StringComparer.Ordinal)
            {
                ["CONTROL_PLANE_TUNNEL_ID"] = options.TunnelId,
                ["CONTROL_PLANE_API_KEY"] = options.ApiKey,
                ["MCP_SERVER_URL"] = options.RouterMcpUrl,
                ["HEALTH_LISTEN_ADDR"] =
                    options.HealthListenAddress,
                ["HEALTH_SHOW_DETAILS"] = "true",
                ["ZAGENT_DEVICE_ID"] = options.DeviceId,
                ["ZAGENT_DEVICE_NAME"] = options.DeviceName,
                ["ZAGENT_DEVICE_BINDING"] = options.DeviceBinding,
                // Public transport is not an internal management client. Clear inherited values.
                [Zagent.Core.Manager.OAuthIntrospectionCredentialStore.EnvironmentName] = "",
                ["ZAGENT_INTERNAL_TOKEN"] = "",
                ["ZAGENT_INTERNAL_CONTEXT_KEY"] = ""
            },
            GracefulShutdownSeconds: 3,
            AutoRestart: true,
            MaxRestartAttempts: 3,
            RestartBackoffMilliseconds: 500,
            RestartBackoffMaxMilliseconds: 5000);
    }

    private static void ValidateRouterOptions(
        TunnelIntegrationOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        if (!File.Exists(options.PythonExecutable))
        {
            throw new FileNotFoundException(
                "Tunnel Python runtime was not found.",
                options.PythonExecutable);
        }

        if (!Directory.Exists(options.EngineRoot))
        {
            throw new DirectoryNotFoundException(
                $"Tunnel engine root was not found: {options.EngineRoot}");
        }

        if (options.RouterPort is < 1 or > 65535)
        {
            throw new ArgumentOutOfRangeException(
                nameof(options),
                "Router port is invalid.");
        }
    }

    private static void ValidateTransportOptions(
        TunnelTransportOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        if (!File.Exists(options.ClientExecutable))
        {
            throw new FileNotFoundException(
                "Tunnel transport client was not found.",
                options.ClientExecutable);
        }

        if (string.IsNullOrWhiteSpace(options.TunnelId))
        {
            throw new ArgumentException(
                "Tunnel ID is required.",
                nameof(options));
        }

        if (string.IsNullOrWhiteSpace(options.ApiKey))
        {
            throw new ArgumentException(
                "Tunnel API key is required.",
                nameof(options));
        }

        if (!Uri.TryCreate(
                options.RouterMcpUrl,
                UriKind.Absolute,
                out var routerUri) ||
            !routerUri.IsLoopback)
        {
            throw new ArgumentException(
                "Router MCP URL must be an absolute loopback URL.",
                nameof(options));
        }
    }
}
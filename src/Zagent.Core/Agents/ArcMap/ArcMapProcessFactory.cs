using Zagent.Core.Supervision;

namespace Zagent.Core.Agents.ArcMap;

public static class ArcMapProcessFactory
{
    public const string ProcessId = "arcmap.mcp";

    public static AgentProcessDefinition Create(
        ArcMapIntegrationOptions options)
    {
        Validate(options);

        return new AgentProcessDefinition(
            AgentId: ProcessId,
            ExecutablePath: Path.GetFullPath(options.PythonExecutable),
            Arguments:
            [
                "-m",
                "mcp_server.server_http"
            ],
            WorkingDirectory: Path.GetFullPath(options.EngineRoot),
            EnvironmentVariables: new Dictionary<string, string>(
                StringComparer.Ordinal)
            {
                ["ZAGENT_ARCMAP_ENGINE_ROOT"] =
                    Path.GetFullPath(options.EngineRoot),
                ["ZAGENT_ARCMAP_DATA_ROOT"] =
                    Path.GetFullPath(options.DataRoot),
                ["ZAGENT_ARCMAP_CONFIG_DIR"] =
                    Path.GetFullPath(options.ConfigRoot),
                ["ZAGENT_ARCMAP_IPC_ROOT"] =
                    Path.GetFullPath(options.IpcRoot),
                ["ZAGENT_ARCMAP_HOST"] = options.BindHost,
                ["ZAGENT_ARCMAP_PORT"] = options.Port.ToString(),
                ["ZAGENT_BIND_HOST"] = options.BindHost,
                ["ZAGENT_TUNNEL_PORT"] = options.TunnelPort.ToString(),
                ["ZAGENT_ARCMAP_MCP_PATH"] = options.McpPath,
                ["ZAGENT_VISUAL_ROOT"] =
                    Path.Combine(
                        Path.GetDirectoryName(
                            Path.GetFullPath(options.DataRoot))!,
                        "visual"),
                ["ZAGENT_DEVICE_ID"] = options.DeviceId,
                ["ZAGENT_DEVICE_NAME"] = options.DeviceName,
                ["ZAGENT_INTERNAL_TOKEN"] =
                    Environment.GetEnvironmentVariable("ZAGENT_INTERNAL_TOKEN") ?? "",
                ["ZAGENT_INTERNAL_CONTEXT_KEY"] =
                    Environment.GetEnvironmentVariable("ZAGENT_INTERNAL_CONTEXT_KEY") ?? "",
                ["PYTHONUNBUFFERED"] = "1"
            },
            GracefulShutdownSeconds: 3,
            AutoRestart: true,
            MaxRestartAttempts: 3,
            RestartBackoffMilliseconds: 250,
            RestartBackoffMaxMilliseconds: 2500,
            HealthRestartGraceMilliseconds: 10000);
    }

    private static void Validate(
        ArcMapIntegrationOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        if (!File.Exists(options.PythonExecutable))
        {
            throw new FileNotFoundException(
                "ArcMap MCP Python runtime was not found.",
                options.PythonExecutable);
        }

        if (!Directory.Exists(options.EngineRoot))
        {
            throw new DirectoryNotFoundException(
                $"ArcMap engine root was not found: {options.EngineRoot}");
        }

        if (!File.Exists(
                Path.Combine(
                    options.EngineRoot,
                    "mcp_server",
                    "server_http.py")))
        {
            throw new FileNotFoundException(
                "ArcMap MCP HTTP entrypoint was not found.");
        }

        if (options.Port is < 1 or > 65535)
        {
            throw new ArgumentOutOfRangeException(
                nameof(options),
                "ArcMap MCP port is invalid.");
        }

        if (!System.Net.IPAddress.TryParse(
                options.BindHost,
                out var ip) ||
            !System.Net.IPAddress.IsLoopback(ip))
        {
            throw new ArgumentException(
                "ArcMap MCP bind host must be a loopback IP.",
                nameof(options));
        }
    }
}
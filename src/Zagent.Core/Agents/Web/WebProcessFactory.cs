using Zagent.Core.Supervision;

namespace Zagent.Core.Agents.Web;

public static class WebProcessFactory
{
    public const string ProcessId = "web.service";

    public static AgentProcessDefinition Create(
        WebIntegrationOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        return new AgentProcessDefinition(
            AgentId: ProcessId,
            ExecutablePath:
                Path.GetFullPath(options.NodeExecutable),
            Arguments:
            [
                Path.Combine(
                    Path.GetFullPath(options.EngineRoot),
                    "dist",
                    "index.js")
            ],
            WorkingDirectory:
                Path.GetFullPath(options.EngineRoot),
            EnvironmentVariables:
                new Dictionary<string, string>(
                    StringComparer.Ordinal)
                {
                    ["ZAGENT_WEB_ENGINE_ROOT"] =
                        Path.GetFullPath(options.EngineRoot),
                    ["ZAGENT_WEB_DATA_ROOT"] =
                        Path.GetFullPath(options.DataRoot),
                    ["ZAGENT_WEB_CONFIG_DIR"] =
                        Path.GetFullPath(options.ConfigRoot),
                    ["ZAGENT_WEB_RUNTIME_DIR"] =
                        Path.GetFullPath(options.RuntimeRoot),
                    ["ZAGENT_WEB_ARTIFACTS_DIR"] =
                        Path.GetFullPath(options.ArtifactsRoot),
                    ["ZAGENT_WEB_LOG_DIR"] =
                        Path.GetFullPath(options.LogRoot),
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
                    ["PLAYWRIGHT_BROWSERS_PATH"] =
                        Path.GetFullPath(
                            Path.Combine(
                                Path.GetDirectoryName(
                                    Path.GetFullPath(options.NodeExecutable))!,
                                "..",
                                "browsers")),
                    ["NODE_ENV"] = "production"
                },
            GracefulShutdownSeconds: 5,
            AutoRestart: true,
            MaxRestartAttempts: 3,
            RestartBackoffMilliseconds: 250,
            RestartBackoffMaxMilliseconds: 2500,
            HealthRestartGraceMilliseconds: 10000);
    }
}
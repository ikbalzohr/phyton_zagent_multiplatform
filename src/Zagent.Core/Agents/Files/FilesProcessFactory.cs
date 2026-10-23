using Zagent.Core.Supervision;

namespace Zagent.Core.Agents.Files;

public static class FilesProcessFactory
{
    public const string ProcessId = "files.service";

    public static AgentProcessDefinition Create(
        FilesIntegrationOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);

        return new AgentProcessDefinition(
            AgentId: ProcessId,
            ExecutablePath: Path.GetFullPath(options.PythonExecutable),
            Arguments:
            [
                "-m",
                "app.core.run_mcp"
            ],
            WorkingDirectory: Path.GetFullPath(options.EngineRoot),
            EnvironmentVariables: new Dictionary<string, string>(
                StringComparer.Ordinal)
            {
                ["ZAGENT_FILES_ENGINE_ROOT"] =
                    Path.GetFullPath(options.EngineRoot),
                ["ZAGENT_FILES_DATA_ROOT"] =
                    Path.GetFullPath(options.DataRoot),
                ["ZAGENT_FILES_CONFIG_DIR"] =
                    Path.GetFullPath(options.ConfigRoot),
                ["ZAGENT_FILES_RUNTIME_DIR"] =
                    Path.GetFullPath(options.RuntimeRoot),
                ["ZAGENT_FILES_LOG_DIR"] =
                    Path.GetFullPath(options.LogRoot),
                ["ZAGENT_FILES_BACKUP_ROOT"] =
                    Path.GetFullPath(options.BackupRoot),
                ["ZAGENT_FILES_UPDATE_STATE_ROOT"] =
                    Path.GetFullPath(options.UpdateStateRoot),
                ["ZAGENT_DEVICE_ID"] = options.DeviceId,
                ["ZAGENT_DEVICE_NAME"] = options.DeviceName,
                ["ZAGENT_INTERNAL_TOKEN"] =
                    Zagent.Core.Manager.InternalManagementChannel.GetChildSecret("ZAGENT_INTERNAL_TOKEN"),
                ["ZAGENT_INTERNAL_CONTEXT_KEY"] =
                    Zagent.Core.Manager.InternalManagementChannel.GetChildSecret("ZAGENT_INTERNAL_CONTEXT_KEY"),
                ["PYTHONPATH"] = Path.GetFullPath(options.EngineRoot),
                ["PYTHONUNBUFFERED"] = "1"
            },
            GracefulShutdownSeconds: 3,
            AutoRestart: true,
            MaxRestartAttempts: 3,
            RestartBackoffMilliseconds: 250,
            RestartBackoffMaxMilliseconds: 2000,
            HealthRestartGraceMilliseconds: 10000);
    }
}
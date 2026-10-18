using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Zagent.Core.Agents.Files;
using Zagent.Core.Registry;
using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;

var passed = 0;
var failed = 0;

var devRoot = Environment.GetEnvironmentVariable("ZAGENT_DEV_ROOT")
    ?? throw new InvalidOperationException("ZAGENT_DEV_ROOT is not set.");
var python = Environment.GetEnvironmentVariable("ZAGENT_FILES_TEST_PYTHON")
    ?? throw new InvalidOperationException("ZAGENT_FILES_TEST_PYTHON is not set.");

var engineRoot = Path.Combine(
    devRoot,
    "agents",
    "files",
    "engine");

var validationRoot = Path.Combine(
    devRoot,
    "_validation",
    "phase5-files-live");

if (Directory.Exists(validationRoot))
{
    Directory.Delete(validationRoot, recursive: true);
}

Directory.CreateDirectory(validationRoot);

var workspace = Path.Combine(validationRoot, "workspace");
var otherRoot = Path.Combine(validationRoot, "other-profile");
Directory.CreateDirectory(workspace);
Directory.CreateDirectory(otherRoot);

var port = FindFreeDevelopmentPort("127.0.0.3");
var options = new FilesIntegrationOptions(
    PythonExecutable: python,
    EngineRoot: engineRoot,
    DataRoot: Path.Combine(validationRoot, "data"),
    ConfigRoot: Path.Combine(validationRoot, "data", "config"),
    RuntimeRoot: Path.Combine(validationRoot, "data", "runtime"),
    LogRoot: Path.Combine(validationRoot, "data", "logs"),
    BackupRoot: Path.Combine(validationRoot, "data", "runtime", "backups"),
    UpdateStateRoot: Path.Combine(validationRoot, "data", "updates"),
    BindHost: "127.0.0.3",
    Port: port,
    DefaultProfileName: "test_profile",
    DefaultProfileRoot: workspace,
    DefaultProfileMode: "read-write");

using var http = new HttpClient(
    new SocketsHttpHandler
    {
        UseProxy = false
    })
{
    Timeout = TimeSpan.FromSeconds(30)
};

var registry = new CapabilityRegistry();
await using var supervisor = new NativeAgentSupervisor(
    acquireInstanceLease: false);
var healthProbe = new FilesHealthProbe(http);
var coordinator = new FilesAgentCoordinator(
    registry,
    supervisor,
    healthProbe: healthProbe);

try
{
    await RunAsync("manifest contains runtime-verified 71 capabilities", async () =>
    {
        var manifest = FilesAgentManifestFactory.Create(
            "3.3.0-v3",
            "127.0.0.3",
            18820);

        Equal(71, manifest.Capabilities.Count);
        Equal(
            71,
            manifest.Capabilities
                .Select(item => item.Name)
                .Distinct(StringComparer.Ordinal)
                .Count());

        var result = registry.Register(
            manifest,
            productionApproved: true);

        True(result.Success, string.Join("; ", result.Errors));

        foreach (var toolName in FilesAgentManifestFactory.KnownToolNames)
        {
            var capability =
                FilesAgentManifestFactory.ToCapabilityName(toolName);
            Equal(1, registry.FindOwners(capability).Count);
        }

        await Task.CompletedTask;
    });

    // Recreate a clean registry for the real coordinator path.
    registry = new CapabilityRegistry();
    coordinator = new FilesAgentCoordinator(
        registry,
        supervisor,
        healthProbe: healthProbe);

    await RunAsync("configuration is isolated and profile is pre-authorized", async () =>
    {
        await coordinator.PrepareAsync(
            options,
            version: "3.3.0-v3",
            productionApproved: true);

        var settingsPath = Path.Combine(
            options.ConfigRoot,
            "settings.json");
        var profilesPath = Path.Combine(
            options.ConfigRoot,
            "profiles.json");
        var policyPath = Path.Combine(
            options.ConfigRoot,
            "command_policy.json");

        True(File.Exists(settingsPath), "settings.json missing.");
        True(File.Exists(profilesPath), "profiles.json missing.");
        True(File.Exists(policyPath), "command_policy.json missing.");

        using var profiles = JsonDocument.Parse(
            await File.ReadAllTextAsync(profilesPath));

        var profile = profiles.RootElement
            .GetProperty("profiles")[0];

        Equal(
            "test_profile",
            profile.GetProperty("name").GetString());
        Equal(
            Path.GetFullPath(workspace),
            profile.GetProperty("root").GetString());
        True(
            profile.GetProperty("authorized_by_user").GetBoolean(),
            "Default profile is not pre-authorized.");
        Equal(
            "read-write",
            profile.GetProperty("mode").GetString());

        True(
            !settingsPath.StartsWith(
                engineRoot,
                StringComparison.OrdinalIgnoreCase),
            "Mutable settings leaked into engine root.");
    });

    await RunAsync("configuration writer preserves approved profiles across upgrade", async () =>
    {
        var preserveRoot = Path.Combine(
            validationRoot,
            "profile-preservation");
        var preserveWorkspace = Path.Combine(
            preserveRoot,
            "workspace");
        var customRoot = Path.Combine(
            preserveRoot,
            "custom");
        var rogueRoot = Path.Combine(
            preserveRoot,
            "rogue");

        Directory.CreateDirectory(preserveWorkspace);
        Directory.CreateDirectory(customRoot);
        Directory.CreateDirectory(rogueRoot);

        var preserveOptions = new FilesIntegrationOptions(
            PythonExecutable: python,
            EngineRoot: engineRoot,
            DataRoot: Path.Combine(preserveRoot, "data"),
            ConfigRoot: Path.Combine(preserveRoot, "data", "config"),
            RuntimeRoot: Path.Combine(preserveRoot, "data", "runtime"),
            LogRoot: Path.Combine(preserveRoot, "data", "logs"),
            BackupRoot: Path.Combine(
                preserveRoot,
                "data",
                "runtime",
                "backups"),
            UpdateStateRoot: Path.Combine(
                preserveRoot,
                "data",
                "updates"),
            BindHost: "127.0.0.3",
            Port: FindFreeDevelopmentPort("127.0.0.3"),
            DefaultProfileName: "install_default",
            DefaultProfileRoot: preserveWorkspace,
            DefaultProfileMode: "read-write");

        var writer = new FilesConfigurationWriter();
        await writer.WriteAsync(preserveOptions);

        var preserveProfilesPath = Path.Combine(
            preserveOptions.ConfigRoot,
            "profiles.json");

        var existing = new
        {
            schema_version = "2.0",
            active_profile = "custom",
            profiles = new object[]
            {
                new
                {
                    name = "install_default",
                    root = preserveWorkspace,
                    mode = "read-write",
                    description = "Installer default",
                    enabled = true,
                    authorized_by_user = true,
                    authorized_at = DateTimeOffset.UtcNow.AddDays(-2),
                    authorization_source = "zagent_install"
                },
                new
                {
                    name = "custom",
                    root = customRoot,
                    mode = "read-write",
                    description = "User approved custom profile",
                    enabled = true,
                    authorized_by_user = true,
                    authorized_at = DateTimeOffset.UtcNow.AddDays(-1),
                    authorization_source = "local_ui"
                },
                new
                {
                    name = "rogue",
                    root = rogueRoot,
                    mode = "read-write",
                    description = "Not approved",
                    enabled = true,
                    authorized_by_user = false,
                    authorized_at = (DateTimeOffset?)null,
                    authorization_source = "pending"
                }
            }
        };

        await File.WriteAllTextAsync(
            preserveProfilesPath,
            JsonSerializer.Serialize(
                existing,
                new JsonSerializerOptions
                {
                    WriteIndented = true
                }));

        await writer.WriteAsync(preserveOptions);

        using var profilesAfterUpgrade = JsonDocument.Parse(
            await File.ReadAllTextAsync(preserveProfilesPath));

        Equal(
            "custom",
            profilesAfterUpgrade.RootElement
                .GetProperty("active_profile")
                .GetString());

        var names = profilesAfterUpgrade.RootElement
            .GetProperty("profiles")
            .EnumerateArray()
            .Select(item =>
                item.GetProperty("name").GetString() ?? string.Empty)
            .ToArray();

        Equal(2, names.Length);
        True(
            names.Contains(
                "install_default",
                StringComparer.OrdinalIgnoreCase),
            "Installer default profile disappeared during upgrade.");
        True(
            names.Contains(
                "custom",
                StringComparer.OrdinalIgnoreCase),
            "Approved custom profile disappeared during upgrade.");
        True(
            !names.Contains(
                "rogue",
                StringComparer.OrdinalIgnoreCase),
            "Unapproved profile was incorrectly preserved.");

        var custom = profilesAfterUpgrade.RootElement
            .GetProperty("profiles")
            .EnumerateArray()
            .Single(item =>
                string.Equals(
                    item.GetProperty("name").GetString(),
                    "custom",
                    StringComparison.OrdinalIgnoreCase));

        Equal(
            Path.GetFullPath(customRoot),
            custom.GetProperty("root").GetString());
        Equal(
            "local_ui",
            custom.GetProperty("authorization_source").GetString());
    });

    await RunAsync("coordinator starts Files and publishes Ready health", async () =>
    {
        var start = await coordinator.StartAsync(
            options,
            TimeSpan.FromSeconds(15));

        True(start.Success, start.Message ?? "Files start failed.");

        True(
            registry.TryGet(
                FilesAgentManifestFactory.AgentId,
                out var registered) &&
            registered is not null,
            "Files registry entry missing.");

        Equal(
            AgentHealthState.Ready,
            registered!.Health);

        True(
            supervisor.TryGetSnapshot(
                FilesProcessFactory.ProcessId,
                out var process) &&
            process is not null,
            "Files process snapshot missing.");

        Equal(AgentProcessState.Running, process!.State);
        True(
            process.ProcessTreeOwned,
            "Files service is not owned by Windows Job Object.");
    });

    var mcpUri = FilesAgentCoordinator.BuildMcpUri(options);

    await RunAsync("runtime exposes exactly the frozen 71-tool surface", async () =>
    {
        var runtimeTools = await ListToolsAsync(http, mcpUri);
        var expected = FilesAgentManifestFactory.KnownToolNames
            .OrderBy(item => item, StringComparer.Ordinal)
            .ToArray();

        Equal(71, runtimeTools.Length);
        Equal(
            string.Join("\n", expected),
            string.Join("\n", runtimeTools));

        var snapshotPath = Path.Combine(
            devRoot,
            "agents",
            "files",
            "runtime-tools.snapshot.json");

        await File.WriteAllTextAsync(
            snapshotPath,
            JsonSerializer.Serialize(
                new
                {
                    version = "3.3.0-v3",
                    count = runtimeTools.Length,
                    tools = runtimeTools
                },
                new JsonSerializerOptions
                {
                    WriteIndented = true
                }));
    });

    await RunAsync("ping and runtime info report Zagent Files 3.3.0-v3", async () =>
    {
        using var ping = await CallToolAsync(
            http,
            mcpUri,
            "files_ping",
            new { });

        var pingText = ping.Text;
        True(
            pingText.Contains(
                "Zagent Files",
                StringComparison.Ordinal),
            "files_ping did not report Zagent Files.");
        True(
            pingText.Contains(
                "3.3.0-v3",
                StringComparison.Ordinal),
            "files_ping did not report 3.3.0-v3.");
        Equal(
            Path.GetFullPath(workspace),
            FindStringProperty(pingText, "root"));

        using var runtime = await CallToolAsync(
            http,
            mcpUri,
            "files_runtime_info",
            new { });

        True(
            runtime.Text.Contains(
                $"http://{options.BindHost}:{options.Port}/mcp",
                StringComparison.Ordinal),
            "runtime_info MCP URL is wrong.");
    });

    await RunAsync("filesystem write read patch and search stay inside sandbox", async () =>
    {
        using var write = await CallToolAsync(
            http,
            mcpUri,
            "files_write",
            new
            {
                path = "docs/alpha.txt",
                content = "alpha\nbeta\n",
                create_parents = true
            });
        True(write.Success, write.Text);

        using var read = await CallToolAsync(
            http,
            mcpUri,
            "files_read",
            new
            {
                path = "docs/alpha.txt"
            });
        True(
            read.Text.Contains("alpha", StringComparison.Ordinal) &&
            read.Text.Contains("beta", StringComparison.Ordinal),
            "files_read content mismatch.");

        using var patch = await CallToolAsync(
            http,
            mcpUri,
            "files_patch",
            new
            {
                path = "docs/alpha.txt",
                old_text = "beta",
                new_text = "gamma"
            });
        True(patch.Success, patch.Text);

        using var search = await CallToolAsync(
            http,
            mcpUri,
            "files_search",
            new
            {
                query = "gamma",
                path = "docs",
                glob = "*.txt"
            });
        True(
            search.Text.Contains("gamma", StringComparison.Ordinal),
            "files_search did not find patched text.");

        True(
            File.Exists(
                Path.Combine(workspace, "docs", "alpha.txt")),
            "File was not written to the authorized workspace.");
    });

    await RunAsync("batch copy supports flatten and preserve_relative_path false", async () =>
    {
        var sourceA = Path.Combine(
            workspace,
            "batch-source",
            "a");
        var sourceB = Path.Combine(
            workspace,
            "batch-source",
            "b");
        Directory.CreateDirectory(sourceA);
        Directory.CreateDirectory(sourceB);
        await File.WriteAllTextAsync(
            Path.Combine(sourceA, "one.txt"),
            "one");
        await File.WriteAllTextAsync(
            Path.Combine(sourceB, "two.txt"),
            "two");

        using var flatten = await CallToolAsync(
            http,
            mcpUri,
            "files_copy_batch_between_profiles",
            new
            {
                source_profile = "test_profile",
                paths = new[]
                {
                    "batch-source/a/one.txt",
                    "batch-source/b/two.txt"
                },
                destination_profile = "test_profile",
                destination_dir = "batch-flat",
                overwrite = false,
                flatten = true
            });

        True(flatten.Success, flatten.Text);
        True(
            File.Exists(
                Path.Combine(
                    workspace,
                    "batch-flat",
                    "one.txt")),
            "Flatten copy did not place one.txt directly in destination.");
        True(
            File.Exists(
                Path.Combine(
                    workspace,
                    "batch-flat",
                    "two.txt")),
            "Flatten copy did not place two.txt directly in destination.");
        False(
            Directory.Exists(
                Path.Combine(
                    workspace,
                    "batch-flat",
                    "batch-source")),
            "Flatten copy unexpectedly preserved the source tree.");
        True(
            flatten.Text.Contains(
                "\"flatten\": true",
                StringComparison.OrdinalIgnoreCase),
            "Flatten checkpoint metadata missing.");

        using var noPreserve = await CallToolAsync(
            http,
            mcpUri,
            "files_copy_batch_between_profiles",
            new
            {
                source_profile = "test_profile",
                paths = new[]
                {
                    "batch-source/a/one.txt",
                    "batch-source/b/two.txt"
                },
                destination_profile = "test_profile",
                destination_dir = "batch-no-preserve",
                overwrite = false,
                preserve_relative_path = false
            });

        True(noPreserve.Success, noPreserve.Text);
        True(
            File.Exists(
                Path.Combine(
                    workspace,
                    "batch-no-preserve",
                    "one.txt")) &&
            File.Exists(
                Path.Combine(
                    workspace,
                    "batch-no-preserve",
                    "two.txt")),
            "preserve_relative_path=false did not flatten output.");
        True(
            noPreserve.Text.Contains(
                "\"preserve_relative_path\": false",
                StringComparison.OrdinalIgnoreCase),
            "preserve_relative_path checkpoint metadata missing.");
    });

    await RunAsync("sandbox blocks traversal and protected secret names", async () =>
    {
        using var escape = await CallToolAsync(
            http,
            mcpUri,
            "files_write",
            new
            {
                path = "../escape.txt",
                content = "blocked"
            },
            expectError: true);

        True(
            escape.IsError,
            "Path traversal unexpectedly succeeded.");
        False(
            File.Exists(
                Path.Combine(validationRoot, "escape.txt")),
            "Traversal wrote outside the sandbox.");

        using var secret = await CallToolAsync(
            http,
            mcpUri,
            "files_write",
            new
            {
                path = ".env",
                content = "SECRET=blocked"
            },
            expectError: true);

        True(
            secret.IsError,
            "Protected secret name unexpectedly succeeded.");
        False(
            File.Exists(Path.Combine(workspace, ".env")),
            "Protected .env was created.");
    });

    await RunAsync("profile request is pending and grants no permission", async () =>
    {
        using var request = await CallToolAsync(
            http,
            mcpUri,
            "files_profile_request_add",
            new
            {
                name = "other_profile",
                root = otherRoot,
                mode = "read-only",
                description = "Phase 5 permission test"
            });

        True(
            request.Text.Contains(
                "pending_user_approval",
                StringComparison.Ordinal),
            "Profile request was not pending approval.");

        using var list = await CallToolAsync(
            http,
            mcpUri,
            "files_profile_list",
            new { });

        False(
            list.Text.Contains(
                "other_profile",
                StringComparison.Ordinal),
            "Pending profile was granted without local approval.");
    });

    await RunAsync("PowerShell command layer runs inside approved profile", async () =>
    {
        using var command = await CallToolAsync(
            http,
            mcpUri,
            "files_powershell_run",
            new
            {
                script = "Write-Output 'zagent-command-pass'",
                profile = "test_profile",
                cwd = ".",
                timeout_seconds = 30,
                metadata = new
                {
                    session_id = "phase5-command",
                    request_id = "req-phase5-command",
                    task_id = "tsk-phase5-command",
                    trace_id = "trc-phase5-command"
                }
            });

        True(command.Success, command.Text);
        True(
            command.Text.Contains(
                "zagent-command-pass",
                StringComparison.Ordinal),
            "PowerShell output missing.");
        True(
            command.Text.Contains(
                "zagent.command_layer",
                StringComparison.Ordinal),
            "Command metadata did not use zagent.* namespace.");
    });

    await RunAsync("PowerShell deny policy still blocks dangerous patterns", async () =>
    {
        using var denied = await CallToolAsync(
            http,
            mcpUri,
            "files_powershell_run",
            new
            {
                script = "Set-ExecutionPolicy Unrestricted",
                profile = "test_profile",
                cwd = ".",
                timeout_seconds = 30
            },
            expectError: true);

        True(denied.IsError, "Denied PowerShell pattern was accepted.");
        True(
            denied.Text.Contains(
                "policy denied",
                StringComparison.OrdinalIgnoreCase),
            "PowerShell policy denial reason missing.");
    });

    await RunAsync("managed process can be started and stopped", async () =>
    {
        using var started = await CallToolAsync(
            http,
            mcpUri,
            "files_process_start",
            new
            {
                executable = "powershell.exe",
                args = new[]
                {
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Start-Sleep -Seconds 30"
                },
                profile = "test_profile",
                cwd = "."
            });

        var pid = FindIntProperty(started.Text, "pid");
        True(pid > 0, "Managed process PID missing.");

        using var stopped = await CallToolAsync(
            http,
            mcpUri,
            "files_process_stop",
            new
            {
                pid,
                force = true
            });

        True(stopped.Success, stopped.Text);
        True(
            FindBoolProperty(stopped.Text, "managed"),
            "Process was not recognized as managed. Payload=" + stopped.Text);
    });

    await RunAsync("command cancellation terminates running process tree", async () =>
    {
        var longCall = CallToolAsync(
            http,
            mcpUri,
            "files_powershell_run",
            new
            {
                script = "Start-Sleep -Seconds 20; Write-Output 'should-not-complete'",
                profile = "test_profile",
                cwd = ".",
                timeout_seconds = 30,
                metadata = new
                {
                    session_id = "phase5-cancel-session",
                    task_id = "phase5-cancel-task",
                    request_id = "phase5-cancel-request",
                    trace_id = "phase5-cancel-trace"
                }
            });

        await Task.Delay(800);

        using var cancel = await CallToolAsync(
            http,
            mcpUri,
            "files_command_cancel",
            new
            {
                task_id = "phase5-cancel-task",
                session_id = "phase5-cancel-session"
            });

        True(cancel.Success, cancel.Text);
        True(
            cancel.Text.Contains(
                "cancelled",
                StringComparison.OrdinalIgnoreCase),
            "Command cancellation did not report cancelled.");

        using var completed = await longCall;
        True(
            FindIntProperty(completed.Text, "exit_code") != 0,
            "Cancelled command returned exit code 0.");
        False(
            completed.Text.Contains(
                "should-not-complete",
                StringComparison.Ordinal),
            "Cancelled command completed normally.");
    });

    string? persistedOperationId = null;

    await RunAsync("session idempotency rejects key reuse with changed payload", async () =>
    {
        var metadata = new
        {
            session_id = "phase5-idem-session",
            profile_id = "test_profile",
            request_id = "phase5-idem-request",
            task_id = "phase5-idem-task",
            trace_id = "phase5-idem-trace",
            idempotency_key = "phase5-idem-key"
        };

        using var first = await CallToolAsync(
            http,
            mcpUri,
            "files_execute",
            new
            {
                operation = "write",
                arguments = new
                {
                    path = "idem.txt",
                    content = "stable-value",
                    create_parents = true
                },
                metadata
            });

        True(first.Success, first.Text);
        persistedOperationId = FindStringProperty(
            first.Text,
            "zagent.operation_id");
        True(
            !string.IsNullOrWhiteSpace(persistedOperationId),
            "Operation ID missing from idempotent result.");

        using var duplicate = await CallToolAsync(
            http,
            mcpUri,
            "files_execute",
            new
            {
                operation = "write",
                arguments = new
                {
                    path = "idem.txt",
                    content = "stable-value",
                    create_parents = true
                },
                metadata
            });

        True(duplicate.Success, duplicate.Text);
        Equal(
            persistedOperationId,
            FindStringProperty(
                duplicate.Text,
                "zagent.operation_id"));

        using var mismatch = await CallToolAsync(
            http,
            mcpUri,
            "files_execute",
            new
            {
                operation = "write",
                arguments = new
                {
                    path = "idem.txt",
                    content = "different-value",
                    create_parents = true
                },
                metadata
            },
            expectError: true);

        True(
            mismatch.IsError,
            "Idempotency key reuse with changed payload succeeded.");
        True(
            mismatch.Text.Contains(
                "Idempotency key reused",
                StringComparison.OrdinalIgnoreCase),
            "Idempotency mismatch reason missing.");
    });

    await RunAsync("operation journal survives service restart", async () =>
    {
        True(
            !string.IsNullOrWhiteSpace(persistedOperationId),
            "Previous operation ID unavailable.");

        var restart = await supervisor.RestartAsync(
            FilesProcessFactory.ProcessId);
        True(restart.Success, restart.Message ?? "Files restart failed.");

        await WaitUntilAsync(
            async () =>
                (await healthProbe.ProbeAsync(mcpUri)).Ready,
            TimeSpan.FromSeconds(15));

        using var status = await CallToolAsync(
            http,
            mcpUri,
            "files_operation_status",
            new
            {
                operation_id = persistedOperationId,
                session_id = "phase5-idem-session"
            });

        True(status.Success, status.Text);
        True(
            status.Text.Contains(
                "succeeded",
                StringComparison.OrdinalIgnoreCase),
            "Persisted operation did not survive restart.");

        var runtimeTools = await ListToolsAsync(http, mcpUri);
        Equal(71, runtimeTools.Length);
    });

    await RunAsync("update staging validates and delegates apply to Core", async () =>
    {
        const string updateId = "phase5-probe-update";

        using var prepare = await CallToolAsync(
            http,
            mcpUri,
            "files_update_prepare",
            new
            {
                update_id = updateId,
                description = "Phase 5 update delegation test",
                target_version = "3.2.1-test"
            });
        True(prepare.Success, prepare.Text);

        using var stage = await CallToolAsync(
            http,
            mcpUri,
            "files_update_stage_text",
            new
            {
                update_id = updateId,
                path = "app/phase5_update_probe.py",
                content = "VALUE = 1\n",
                encoding = "utf-8"
            });
        True(stage.Success, stage.Text);

        using var validate = await CallToolAsync(
            http,
            mcpUri,
            "files_update_validate",
            new
            {
                update_id = updateId
            });
        True(validate.Success, validate.Text);
        True(
            validate.Text.Contains(
                "\"ok\":true",
                StringComparison.OrdinalIgnoreCase) ||
            validate.Text.Contains(
                "\"ok\": true",
                StringComparison.OrdinalIgnoreCase),
            "Update validation failed.");

        using var apply = await CallToolAsync(
            http,
            mcpUri,
            "files_update_apply",
            new
            {
                update_id = updateId
            });
        True(apply.Success, apply.Text);
        True(
            apply.Text.Contains(
                "requires_core",
                StringComparison.Ordinal),
            "Update apply did not delegate to Core.");

        var requestDir = Path.Combine(
            options.UpdateStateRoot,
            "requests");
        True(
            Directory.Exists(requestDir) &&
            Directory.EnumerateFiles(
                requestDir,
                "*.json").Any(),
            "Core update request file was not created.");

        False(
            File.Exists(
                Path.Combine(
                    engineRoot,
                    "app",
                    "phase5_update_probe.py")),
            "Files service mutated its own engine before Core approval.");

        using var abort = await CallToolAsync(
            http,
            mcpUri,
            "files_update_abort",
            new
            {
                update_id = updateId
            });
        True(abort.Success, abort.Text);
    });

    await RunAsync("Core Update Broker applies and rolls back on isolated engine", async () =>
    {
        var brokerRoot = Path.Combine(
            validationRoot,
            "broker-isolated");
        var fakeEngine = Path.Combine(
            brokerRoot,
            "engine");
        var fakeData = Path.Combine(
            brokerRoot,
            "data");
        var fakeUpdateRoot = Path.Combine(
            fakeData,
            "updates");
        var fakeConfig = Path.Combine(
            fakeData,
            "config");
        var fakeRuntime = Path.Combine(
            fakeData,
            "runtime");
        var fakeLogs = Path.Combine(
            fakeData,
            "logs");
        var fakeBackups = Path.Combine(
            fakeRuntime,
            "backups");
        var fakeWorkspace = Path.Combine(
            brokerRoot,
            "workspace");

        Directory.CreateDirectory(
            Path.Combine(fakeEngine, "app"));
        Directory.CreateDirectory(fakeWorkspace);

        var target = Path.Combine(
            fakeEngine,
            "app",
            "probe.txt");
        await File.WriteAllTextAsync(
            target,
            "old-value\n");

        const string updateId = "broker-probe";
        var stageRoot = Path.Combine(
            fakeUpdateRoot,
            "staging",
            updateId);
        var staged = Path.Combine(
            stageRoot,
            "files",
            "app",
            "probe.txt");

        Directory.CreateDirectory(
            Path.GetDirectoryName(staged)!);

        await File.WriteAllTextAsync(
            staged,
            "new-value\n");

        var stagedHash = Convert.ToHexString(
                SHA256.HashData(
                    await File.ReadAllBytesAsync(staged)))
            .ToLowerInvariant();

        Directory.CreateDirectory(stageRoot);
        await File.WriteAllTextAsync(
            Path.Combine(stageRoot, "metadata.json"),
            JsonSerializer.Serialize(
                new
                {
                    update_id = updateId,
                    status = "validated",
                    validated = true,
                    files = new Dictionary<string, object>
                    {
                        ["app/probe.txt"] = new
                        {
                            bytes = new FileInfo(staged).Length,
                            sha256 = stagedHash,
                            encoding = "utf-8"
                        }
                    },
                    deletes = Array.Empty<string>()
                },
                new JsonSerializerOptions
                {
                    WriteIndented = true
                }));

        var fakeOptions = new FilesIntegrationOptions(
            PythonExecutable: python,
            EngineRoot: fakeEngine,
            DataRoot: fakeData,
            ConfigRoot: fakeConfig,
            RuntimeRoot: fakeRuntime,
            LogRoot: fakeLogs,
            BackupRoot: fakeBackups,
            UpdateStateRoot: fakeUpdateRoot,
            BindHost: "127.0.0.3",
            Port: FindFreeDevelopmentPort("127.0.0.3"),
            DefaultProfileName: "fake",
            DefaultProfileRoot: fakeWorkspace);

        var requestRoot = Path.Combine(
            fakeUpdateRoot,
            "requests");
        Directory.CreateDirectory(requestRoot);

        var applyRequest = Path.Combine(
            requestRoot,
            "apply.json");
        await File.WriteAllTextAsync(
            applyRequest,
            JsonSerializer.Serialize(
                new
                {
                    schema_version = 1,
                    request_id = "broker-apply",
                    component = "files",
                    action = "apply",
                    update_id = updateId,
                    requested_at = DateTimeOffset.UtcNow,
                    status = "pending_core",
                    engine_root = Path.GetFullPath(fakeEngine),
                    state_root = Path.GetFullPath(fakeUpdateRoot)
                },
                new JsonSerializerOptions
                {
                    WriteIndented = true
                }));

        await using var fakeSupervisor =
            new NativeAgentSupervisor(
                acquireInstanceLease: false);
        var processor =
            new FilesUpdateRequestProcessor(
                fakeSupervisor);

        var applyResult =
            await processor.ProcessRequestAsync(
                fakeOptions,
                applyRequest);

        True(
            applyResult.Success,
            applyResult.Error ?? "Core apply failed.");
        Equal(
            "new-value\n",
            await File.ReadAllTextAsync(target));

        var backupManifest = Path.Combine(
            fakeUpdateRoot,
            "backups",
            updateId,
            "manifest.json");
        True(
            File.Exists(backupManifest),
            "Core apply did not create rollback backup.");

        using (var applyState = JsonDocument.Parse(
            await File.ReadAllTextAsync(applyRequest)))
        {
            Equal(
                "completed",
                applyState.RootElement
                    .GetProperty("status")
                    .GetString());
        }

        var rollbackRequest = Path.Combine(
            requestRoot,
            "rollback.json");
        await File.WriteAllTextAsync(
            rollbackRequest,
            JsonSerializer.Serialize(
                new
                {
                    schema_version = 1,
                    request_id = "broker-rollback",
                    component = "files",
                    action = "rollback",
                    update_id = updateId,
                    requested_at = DateTimeOffset.UtcNow,
                    status = "pending_core",
                    engine_root = Path.GetFullPath(fakeEngine),
                    state_root = Path.GetFullPath(fakeUpdateRoot)
                },
                new JsonSerializerOptions
                {
                    WriteIndented = true
                }));

        var rollbackResult =
            await processor.ProcessRequestAsync(
                fakeOptions,
                rollbackRequest);

        True(
            rollbackResult.Success,
            rollbackResult.Error ?? "Core rollback failed.");
        Equal(
            "old-value\n",
            await File.ReadAllTextAsync(target));

        using (var rollbackState = JsonDocument.Parse(
            await File.ReadAllTextAsync(rollbackRequest)))
        {
            Equal(
                "completed",
                rollbackState.RootElement
                    .GetProperty("status")
                    .GetString());
        }

        True(
            File.Exists(
                Path.Combine(
                    fakeUpdateRoot,
                    "last_result.json")),
            "Core Update Broker did not write last_result.json.");
        True(
            File.Exists(
                Path.Combine(
                    fakeUpdateRoot,
                    "history.jsonl")),
            "Core Update Broker did not write history.jsonl.");
    });

    await RunAsync("coordinator refresh and stop publish health correctly", async () =>
    {
        var health = await coordinator.RefreshHealthAsync(options);
        True(health.Ready, health.Error ?? "Files health failed.");

        True(
            registry.TryGet(
                FilesAgentManifestFactory.AgentId,
                out var ready) &&
            ready?.Health == AgentHealthState.Ready,
            "Registry did not retain Ready Files health.");

        var stop = await coordinator.StopAsync();
        True(stop.Success, stop.Message ?? "Files stop failed.");

        True(
            registry.TryGet(
                FilesAgentManifestFactory.AgentId,
                out var stopped) &&
            stopped?.Health == AgentHealthState.Offline,
            "Registry did not publish Offline after stop.");

        supervisor.TryGetSnapshot(
            FilesProcessFactory.ProcessId,
            out var snapshot);

        Equal(
            AgentProcessState.Stopped,
            snapshot!.State);
    });
}
finally
{
    try
    {
        await supervisor.StopAllAsync();
    }
    catch
    {
    }

    try
    {
        Directory.Delete(validationRoot, recursive: true);
    }
    catch
    {
    }
}

Console.WriteLine(
    failed == 0
        ? $"FILES_TEST_PASS passed={passed} failed={failed}"
        : $"FILES_TEST_FAIL passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

async Task<string[]> ListToolsAsync(
    HttpClient client,
    Uri uri)
{
    using var response = await RpcAsync(
        client,
        uri,
        new
        {
            jsonrpc = "2.0",
            id = Guid.NewGuid().ToString("N"),
            method = "tools/list",
            @params = new { }
        });

    return response.RootElement
        .GetProperty("result")
        .GetProperty("tools")
        .EnumerateArray()
        .Select(
            item => item.GetProperty("name").GetString() ?? "")
        .Where(name => !string.IsNullOrWhiteSpace(name))
        .OrderBy(name => name, StringComparer.Ordinal)
        .ToArray();
}

async Task<ToolCallResult> CallToolAsync(
    HttpClient client,
    Uri uri,
    string toolName,
    object arguments,
    bool expectError = false)
{
    using var rpc = await RpcAsync(
        client,
        uri,
        new
        {
            jsonrpc = "2.0",
            id = Guid.NewGuid().ToString("N"),
            method = "tools/call",
            @params = new
            {
                name = toolName,
                arguments
            }
        });

    if (rpc.RootElement.TryGetProperty(
            "error",
            out var rpcError))
    {
        var text = rpcError.ToString();

        if (!expectError)
        {
            throw new InvalidOperationException(
                $"Tool '{toolName}' RPC error: {text}");
        }

        return new ToolCallResult(
            false,
            true,
            text);
    }

    var result = rpc.RootElement.GetProperty("result");
    var isError =
        result.TryGetProperty("isError", out var errorElement) &&
        errorElement.ValueKind == JsonValueKind.True;

    var textPayload = ExtractToolText(result);

    if (isError && !expectError)
    {
        throw new InvalidOperationException(
            $"Tool '{toolName}' failed: {textPayload}");
    }

    if (!isError && expectError)
    {
        throw new InvalidOperationException(
            $"Tool '{toolName}' unexpectedly succeeded: {textPayload}");
    }

    return new ToolCallResult(
        !isError,
        isError,
        textPayload);
}

static string ExtractToolText(JsonElement result)
{
    if (result.TryGetProperty(
            "structuredContent",
            out var structured) &&
        structured.ValueKind is not JsonValueKind.Null and
            not JsonValueKind.Undefined)
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
            .Where(text => !string.IsNullOrWhiteSpace(text))
            .ToArray();

        if (texts.Length > 0)
        {
            return string.Join("\n", texts);
        }
    }

    return result.ToString();
}

static int FindIntProperty(
    string jsonText,
    string propertyName)
{
    using var document = JsonDocument.Parse(jsonText);
    return FindProperty(
        document.RootElement,
        propertyName,
        out var value)
        ? value.GetInt32()
        : 0;
}

static string? FindStringProperty(
    string jsonText,
    string propertyName)
{
    using var document = JsonDocument.Parse(jsonText);
    return FindProperty(
        document.RootElement,
        propertyName,
        out var value)
        ? value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : value.ToString()
        : null;
}

static bool FindBoolProperty(
    string jsonText,
    string propertyName)
{
    using var document = JsonDocument.Parse(jsonText);
    return FindProperty(
        document.RootElement,
        propertyName,
        out var value) &&
        value.ValueKind == JsonValueKind.True;
}

static bool FindProperty(
    JsonElement element,
    string name,
    out JsonElement value)
{
    if (element.ValueKind == JsonValueKind.Object)
    {
        foreach (var property in element.EnumerateObject())
        {
            if (string.Equals(
                    property.Name,
                    name,
                    StringComparison.Ordinal))
            {
                value = property.Value.Clone();
                return true;
            }

            if (FindProperty(
                    property.Value,
                    name,
                    out value))
            {
                return true;
            }
        }
    }
    else if (element.ValueKind == JsonValueKind.Array)
    {
        foreach (var child in element.EnumerateArray())
        {
            if (FindProperty(
                    child,
                    name,
                    out value))
            {
                return true;
            }
        }
    }
    else if (element.ValueKind == JsonValueKind.String)
    {
        var nestedText = element.GetString();

        if (!string.IsNullOrWhiteSpace(nestedText))
        {
            try
            {
                using var nested = JsonDocument.Parse(nestedText);
                if (FindProperty(
                        nested.RootElement,
                        name,
                        out value))
                {
                    value = value.Clone();
                    return true;
                }
            }
            catch (JsonException)
            {
            }
        }
    }

    value = default;
    return false;
}

static async Task<JsonDocument> RpcAsync(
    HttpClient client,
    Uri uri,
    object payload)
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

    using var response = await client.SendAsync(request);
    var body = await response.Content.ReadAsStringAsync();

    if (!response.IsSuccessStatusCode)
    {
        throw new HttpRequestException(
            $"HTTP {(int)response.StatusCode}: {body}");
    }

    var contentType =
        response.Content.Headers.ContentType?.MediaType ?? "";

    if (contentType.Contains(
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

static async Task WaitUntilAsync(
    Func<Task<bool>> predicate,
    TimeSpan timeout)
{
    var deadline = DateTime.UtcNow + timeout;

    while (DateTime.UtcNow < deadline)
    {
        if (await predicate())
        {
            return;
        }

        await Task.Delay(100);
    }

    throw new TimeoutException(
        $"Condition was not satisfied within {timeout}.");
}

static int FindFreeDevelopmentPort(string host)
{
    var address = IPAddress.Parse(host);

    for (var port = 18900; port <= 18999; port++)
    {
        TcpListener? listener = null;
        try
        {
            listener = new TcpListener(address, port);
            listener.Start();
            return port;
        }
        catch (SocketException)
        {
        }
        finally
        {
            listener?.Stop();
        }
    }

    throw new InvalidOperationException(
        "No free Zagent Development Gateway port is available.");
}

async Task RunAsync(
    string name,
    Func<Task> test)
{
    try
    {
        await test();
        passed++;
        Console.WriteLine($"PASS {name}");
    }
    catch (Exception ex)
    {
        failed++;
        Console.WriteLine($"FAIL {name}: {ex}");
    }
}

static void True(
    bool condition,
    string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void False(
    bool condition,
    string message) =>
    True(!condition, message);

static void Equal<T>(
    T expected,
    T actual)
{
    if (!EqualityComparer<T>.Default.Equals(
            expected,
            actual))
    {
        throw new InvalidOperationException(
            $"Expected '{expected}', actual '{actual}'.");
    }
}

sealed record ToolCallResult(
    bool Success,
    bool IsError,
    string Text) : IDisposable
{
    public void Dispose()
    {
    }
}
using Zagent.Shared;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Agents.Files;

public static class FilesAgentManifestFactory
{
    public const string AgentId = "files.service";

    public static IReadOnlyList<string> KnownToolNames { get; } =
    [
        "files_append",
        "files_backup",
        "files_backup_list",
        "files_build",
        "files_capabilities",
        "files_command_cancel",
        "files_command_capabilities",
        "files_copy",
        "files_copy_batch_between_profiles",
        "files_copy_between_profiles",
        "files_cross_profile_capabilities",
        "files_delete",
        "files_diff",
        "files_exec_command",
        "files_execute",
        "files_exists",
        "files_get_root",
        "files_git",
        "files_hash",
        "files_list",
        "files_mkdir",
        "files_move",
        "files_node",
        "files_npm",
        "files_npx",
        "files_operation_cancel",
        "files_operation_list",
        "files_operation_status",
        "files_patch",
        "files_ping",
        "files_powershell_run",
        "files_process_list",
        "files_process_start",
        "files_process_stop",
        "files_profile_default_get",
        "files_profile_get",
        "files_profile_list",
        "files_profile_pending_list",
        "files_profile_reload",
        "files_profile_request_add",
        "files_profile_request_delete",
        "files_profile_request_status",
        "files_profile_request_update",
        "files_profile_switch",
        "files_read",
        "files_read_bytes_b64",
        "files_restore",
        "files_runtime_info",
        "files_search",
        "files_session_list",
        "files_session_open",
        "files_session_status",
        "files_session_switch",
        "files_stat",
        "files_syntax_check",
        "files_test",
        "files_tree",
        "files_unzip",
        "files_update_abort",
        "files_update_apply",
        "files_update_capabilities",
        "files_update_history",
        "files_update_mark_delete",
        "files_update_prepare",
        "files_update_rollback",
        "files_update_stage_b64",
        "files_update_stage_text",
        "files_update_status",
        "files_update_validate",
        "files_write",
        "files_zip",
    ];

    public static AgentManifest Create(
        string version,
        string bindHost,
        int port,
        AgentEnvironment environment = AgentEnvironment.Production)
    {
        var capabilities = KnownToolNames
            .Select(CreateCapability)
            .ToArray();

        return new AgentManifest(
            ProtocolVersion: ZagentProductInfo.AgentProtocolVersion,
            Agent: new AgentIdentity(
                Id: AgentId,
                Name: "Zagent Files",
                Version: version),
            Environment: environment,
            Runtime: new AgentRuntimeDescriptor(
                Language: "python",
                Version: "3.11",
                Entrypoint: "app.core.run_mcp"),
            Transport: new AgentTransportDescriptor(
                Kind: "http-mcp",
                BindHost: bindHost,
                Port: port,
                Path: "/mcp",
                LocalOnly: true),
            Lifecycle: new AgentLifecycleDescriptor(
                GracefulShutdownSeconds: 3),
            Health: new AgentHealthDescriptor(
                Probe: "mcp-initialize",
                Target: $"http://{bindHost}:{port}/mcp",
                IntervalSeconds: 10,
                TimeoutSeconds: 4),
            Capabilities: capabilities,
            Metadata: new Dictionary<string, string>
            {
                ["public_tool_count"] =
                    KnownToolNames.Count.ToString(),
                ["command_layer_version"] = "3.1.3",
                ["profile_model"] = "approved-sandbox",
                ["update_owner"] = "Zagent Core"
            });
    }

    public static string ToCapabilityName(string toolName)
    {
        if (!toolName.StartsWith(
                "files_",
                StringComparison.Ordinal))
        {
            throw new ArgumentException(
                $"Unexpected Files tool name '{toolName}'.",
                nameof(toolName));
        }

        return "files." + toolName[6..];
    }

    private static CapabilityDescriptor CreateCapability(
        string toolName)
    {
        var suffix = toolName[6..];
        var readOnly = ReadOnly.Contains(suffix);
        var background = Background.Contains(suffix);
        var admin = Admin.Contains(suffix);
        var cancellable =
            Cancellable.Contains(suffix);
        var resumable =
            string.Equals(
                suffix,
                "copy_batch_between_profiles",
                StringComparison.Ordinal);

        return new CapabilityDescriptor(
            Name: ToCapabilityName(toolName),
            Description: $"Zagent Files MCP tool {toolName}.",
            Access: admin
                ? CapabilityAccess.Admin
                : readOnly
                    ? CapabilityAccess.Read
                    : CapabilityAccess.Write,
            Execution: background
                ? CapabilityExecution.Background
                : CapabilityExecution.Fast,
            Approval:
                suffix.StartsWith(
                    "profile_request_",
                    StringComparison.Ordinal)
                    ? CapabilityApproval.User
                    : admin
                        ? CapabilityApproval.Policy
                        : CapabilityApproval.None,
            SupportsCancel: cancellable,
            SupportsProgress: resumable,
            SupportsResume: resumable,
            ResourcePolicy: readOnly
                ? ResourcePolicy.ReadLock
                : ResourcePolicy.WriteLock);
    }

    private static readonly HashSet<string> ReadOnly =
        new(StringComparer.Ordinal)
        {
            "backup_list",
            "capabilities",
            "command_capabilities",
            "cross_profile_capabilities",
            "diff",
            "exists",
            "get_root",
            "hash",
            "list",
            "operation_list",
            "operation_status",
            "ping",
            "process_list",
            "profile_default_get",
            "profile_get",
            "profile_list",
            "profile_pending_list",
            "profile_reload",
            "profile_request_status",
            "read",
            "read_bytes_b64",
            "runtime_info",
            "search",
            "session_list",
            "session_status",
            "stat",
            "syntax_check",
            "tree",
            "update_capabilities",
            "update_history",
            "update_status"
        };

    private static readonly HashSet<string> Background =
        new(StringComparer.Ordinal)
        {
            "backup",
            "build",
            "copy",
            "copy_batch_between_profiles",
            "copy_between_profiles",
            "delete",
            "exec_command",
            "execute",
            "git",
            "move",
            "node",
            "npm",
            "npx",
            "powershell_run",
            "process_start",
            "restore",
            "test",
            "unzip",
            "zip"
        };

    private static readonly HashSet<string> Cancellable =
        new(StringComparer.Ordinal)
        {
            "build",
            "copy_batch_between_profiles",
            "exec_command",
            "git",
            "node",
            "npm",
            "npx",
            "powershell_run",
            "test"
        };

    private static readonly HashSet<string> Admin =
        new(StringComparer.Ordinal)
        {
            "process_stop",
            "update_apply",
            "update_rollback"
        };
}

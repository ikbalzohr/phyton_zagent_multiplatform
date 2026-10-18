using Zagent.Shared;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Agents.Web;

public static class WebAgentManifestFactory
{
    public const string AgentId = "web.service";

    public static IReadOnlyList<string> KnownToolNames { get; } =
    [
        "web_act",
        "web_allow_host_add",
        "web_allow_host_remove",
        "web_assert_checked",
        "web_assert_element",
        "web_assert_enabled",
        "web_assert_text",
        "web_assert_url",
        "web_assert_visible",
        "web_audit",
        "web_back",
        "web_bridge_authorize_request",
        "web_bridge_disconnect",
        "web_bridge_pair",
        "web_bridge_pair_status",
        "web_bridge_profile_binding",
        "web_bridge_reconnect",
        "web_bridge_revoke",
        "web_bridge_select_tab",
        "web_bridge_status",
        "web_bridge_tabs",
        "web_browser_attach_cdp",
        "web_browser_start",
        "web_browser_stop",
        "web_check",
        "web_chrome_launch_profile",
        "web_chrome_launch_status",
        "web_chrome_profiles",
        "web_clear",
        "web_clear_permissions",
        "web_click",
        "web_close",
        "web_close_tab",
        "web_console_clear",
        "web_console_errors",
        "web_console_logs",
        "web_cookies_clear",
        "web_cookies_get",
        "web_cookies_set",
        "web_device_list",
        "web_dialog_accept",
        "web_dialog_dismiss",
        "web_dialog_info",
        "web_double_click",
        "web_download",
        "web_downloads",
        "web_drag_drop",
        "web_evaluate_js",
        "web_external_hosts_set",
        "web_fill",
        "web_find",
        "web_find_role",
        "web_find_text",
        "web_focus",
        "web_forward",
        "web_get_accessibility_tree",
        "web_get_attribute",
        "web_get_bounds",
        "web_get_element",
        "web_get_elements",
        "web_get_html",
        "web_get_page_state",
        "web_get_text",
        "web_get_title",
        "web_get_url",
        "web_get_viewport",
        "web_grant_permissions",
        "web_har_start",
        "web_har_stop",
        "web_hover",
        "web_inspect",
        "web_js_eval_set",
        "web_keyboard_press",
        "web_native_chrome_attach",
        "web_native_chrome_detach",
        "web_native_chrome_detect",
        "web_native_chrome_status",
        "web_native_chrome_tabs",
        "web_network_block",
        "web_network_clear",
        "web_network_errors",
        "web_network_find",
        "web_network_mock",
        "web_network_request_detail",
        "web_network_requests",
        "web_network_response",
        "web_network_routes_clear",
        "web_new_tab",
        "web_open",
        "web_performance_metrics",
        "web_ping",
        "web_press",
        "web_recording_export_test",
        "web_recording_replay",
        "web_recording_start",
        "web_recording_stop",
        "web_reload",
        "web_right_click",
        "web_runtime_info",
        "web_save_pdf",
        "web_screenshot",
        "web_screenshot_element",
        "web_screenshot_full_page",
        "web_scroll",
        "web_scroll_into_view",
        "web_security_status",
        "web_select",
        "web_session_close",
        "web_session_close_all",
        "web_session_list",
        "web_session_open",
        "web_session_save",
        "web_session_status",
        "web_set_device",
        "web_set_geolocation",
        "web_set_viewport",
        "web_status",
        "web_storage_clear",
        "web_storage_get",
        "web_storage_set",
        "web_storage_state_load",
        "web_storage_state_save",
        "web_switch_tab",
        "web_tabs",
        "web_target_add",
        "web_target_remove",
        "web_target_test",
        "web_targets",
        "web_trace_start",
        "web_trace_stop",
        "web_type",
        "web_uncheck",
        "web_upload_file",
        "web_video_start",
        "web_video_stop",
        "web_visual_act_and_observe",
        "web_visual_compare",
        "web_visual_frame_extract",
        "web_visual_ingest",
        "web_visual_latest",
        "web_visual_list",
        "web_visual_prune",
        "web_visual_snapshot",
        "web_visual_store_status",
        "web_wait",
        "web_wait_for_element",
        "web_wait_for_network_idle",
        "web_wait_for_text",
        "web_wait_for_url",
        "web_workflow",
        "web_workflow_resume",
    ];

    public static AgentManifest Create(
        string version,
        string bindHost,
        int port,
        AgentEnvironment environment = AgentEnvironment.Production)
    {
        return new AgentManifest(
            ProtocolVersion: ZagentProductInfo.AgentProtocolVersion,
            Agent: new AgentIdentity(
                Id: AgentId,
                Name: "Zagent Web",
                Version: version),
            Environment: environment,
            Runtime: new AgentRuntimeDescriptor(
                Language: "typescript/node",
                Version: ">=20.18 <27",
                Entrypoint: "dist/index.js"),
            Transport: new AgentTransportDescriptor(
                Kind: "http-mcp",
                BindHost: bindHost,
                Port: port,
                Path: "/mcp",
                LocalOnly: true),
            Lifecycle: new AgentLifecycleDescriptor(
                GracefulShutdownSeconds: 5),
            Health: new AgentHealthDescriptor(
                Probe: "http-json",
                Target: $"http://{bindHost}:{port}/health",
                IntervalSeconds: 10,
                TimeoutSeconds: 4),
            Capabilities:
                KnownToolNames.Select(CreateCapability).ToArray(),
            Metadata: new Dictionary<string, string>
            {
                ["public_tool_count"] = KnownToolNames.Count.ToString(),
                ["chrome_bridge_version"] = "1.3.3",
                ["browser_ownership"] = "external-native-chrome",
                ["default_runtime_mode"] = "native_attach",
                ["default_session_isolation"] = "tabs",
                ["pairing_model"] = "profile-bound-time-limited"
            });
    }

    public static string ToCapabilityName(
        string toolName)
    {
        if (!toolName.StartsWith(
                "web_",
                StringComparison.Ordinal))
        {
            throw new ArgumentException(
                $"Unexpected Web tool name '{toolName}'.",
                nameof(toolName));
        }

        return "web." + toolName[4..];
    }

    private static CapabilityDescriptor CreateCapability(
        string toolName)
    {
        var suffix = toolName[4..];
        var readOnly = ReadOnly.Contains(suffix);
        var admin = Admin.Contains(suffix);
        var userApproval =
            suffix.StartsWith(
                "bridge_pair",
                StringComparison.Ordinal) ||
            suffix.StartsWith(
                "bridge_authorize",
                StringComparison.Ordinal);

        var background =
            Background.Contains(suffix);

        return new CapabilityDescriptor(
            Name: ToCapabilityName(toolName),
            Description: $"Zagent Web MCP tool {toolName}.",
            Access: admin
                ? CapabilityAccess.Admin
                : readOnly
                    ? CapabilityAccess.Read
                    : CapabilityAccess.Action,
            Execution: background
                ? CapabilityExecution.Background
                : CapabilityExecution.Fast,
            Approval: userApproval
                ? CapabilityApproval.User
                : admin
                    ? CapabilityApproval.Policy
                    : CapabilityApproval.None,
            SupportsCancel: false,
            SupportsProgress:
                suffix is "workflow" or "workflow_resume",
            SupportsResume:
                suffix == "workflow_resume",
            ResourcePolicy: readOnly
                ? ResourcePolicy.ReadLock
                : ResourcePolicy.Exclusive);
    }

    private static readonly HashSet<string> ReadOnly =
        new(StringComparer.Ordinal)
        {
            "assert_checked",
            "assert_element",
            "assert_enabled",
            "assert_text",
            "assert_url",
            "assert_visible",
            "audit",
            "bridge_pair_status",
            "bridge_profile_binding",
            "bridge_status",
            "bridge_tabs",
            "chrome_launch_status",
            "chrome_profiles",
            "console_errors",
            "console_logs",
            "cookies_get",
            "device_list",
            "dialog_info",
            "downloads",
            "find",
            "find_role",
            "find_text",
            "get_accessibility_tree",
            "get_attribute",
            "get_bounds",
            "get_element",
            "get_elements",
            "get_html",
            "get_page_state",
            "get_text",
            "get_title",
            "get_url",
            "get_viewport",
            "inspect",
            "native_chrome_detect",
            "native_chrome_status",
            "native_chrome_tabs",
            "network_errors",
            "network_find",
            "network_request_detail",
            "network_requests",
            "network_response",
            "performance_metrics",
            "ping",
            "runtime_info",
            "security_status",
            "session_list",
            "session_status",
            "status",
            "storage_get",
            "tabs",
            "targets",
            "visual_latest",
            "visual_list",
            "visual_store_status"
        };

    private static readonly HashSet<string> Admin =
        new(StringComparer.Ordinal)
        {
            "allow_host_add",
            "allow_host_remove",
            "clear_permissions",
            "external_hosts_set",
            "grant_permissions",
            "js_eval_set",
            "visual_prune"
        };

    private static readonly HashSet<string> Background =
        new(StringComparer.Ordinal)
        {
            "download",
            "har_stop",
            "recording_replay",
            "save_pdf",
            "screenshot",
            "screenshot_element",
            "screenshot_full_page",
            "trace_stop",
            "video_stop",
            "visual_act_and_observe",
            "visual_compare",
            "visual_frame_extract",
            "visual_snapshot",
            "wait",
            "wait_for_element",
            "wait_for_network_idle",
            "wait_for_text",
            "wait_for_url",
            "workflow",
            "workflow_resume"
        };
}

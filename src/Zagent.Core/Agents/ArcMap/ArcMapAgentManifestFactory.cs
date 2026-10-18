using Zagent.Shared;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Agents.ArcMap;

public static class ArcMapAgentManifestFactory
{
    public const string AgentId = "arcmap.service";

    public static IReadOnlyList<string> KnownToolNames { get; } =
    [
        "arcmap_add_layer",
        "arcmap_add_temporary_layer",
        "arcmap_agent_safety_status",
        "arcmap_apply_layout_recipe",
        "arcmap_apply_map_recipe",
        "arcmap_apply_symbology_from_layer",
        "arcmap_buffer",
        "arcmap_calculate_geometry_xy",
        "arcmap_capture_layer_style",
        "arcmap_clear_selection",
        "arcmap_clip",
        "arcmap_compare_layer_extents",
        "arcmap_connect_gis_mapserver",
        "arcmap_create_file_gdb",
        "arcmap_create_native_grid",
        "arcmap_delete_style_snapshot",
        "arcmap_dissolve",
        "arcmap_edit_guard_acquire",
        "arcmap_edit_guard_release",
        "arcmap_edit_guard_status",
        "arcmap_erase_features",
        "arcmap_export_bundle",
        "arcmap_export_data_driven_pages_pdf",
        "arcmap_export_jpeg",
        "arcmap_export_pdf",
        "arcmap_export_png",
        "arcmap_export_preflight",
        "arcmap_export_tiff",
        "arcmap_get_active_dataframe",
        "arcmap_get_agent_context",
        "arcmap_get_broken_data_sources",
        "arcmap_get_capability_matrix",
        "arcmap_get_data_driven_pages_state",
        "arcmap_get_dataframe_state",
        "arcmap_get_feature_count",
        "arcmap_get_field_statistics",
        "arcmap_get_geometry_summary",
        "arcmap_get_label_state",
        "arcmap_get_layer_capabilities",
        "arcmap_get_layer_extent",
        "arcmap_get_layer_order",
        "arcmap_get_layer_state",
        "arcmap_get_layout_element_state",
        "arcmap_get_layout_manifest",
        "arcmap_get_map_recipe_schema",
        "arcmap_get_native_grid_properties",
        "arcmap_get_native_layer_properties",
        "arcmap_get_native_renderer_state",
        "arcmap_get_renderer_capabilities",
        "arcmap_get_selection_state",
        "arcmap_get_status",
        "arcmap_get_symbology_state",
        "arcmap_get_unique_values",
        "arcmap_goal_build_map",
        "arcmap_goal_cancel",
        "arcmap_goal_execute",
        "arcmap_goal_plan",
        "arcmap_goal_report",
        "arcmap_goal_resume",
        "arcmap_goal_status",
        "arcmap_goal_validate",
        "arcmap_gp_preflight",
        "arcmap_import_coordinates_to_shp",
        "arcmap_inspect_current_map",
        "arcmap_intersect",
        "arcmap_list_fields",
        "arcmap_list_layers",
        "arcmap_list_layout_elements",
        "arcmap_list_layout_text",
        "arcmap_list_native_grids",
        "arcmap_list_native_scale_bars",
        "arcmap_list_style_snapshots",
        "arcmap_list_temporary_layers",
        "arcmap_merge_layers",
        "arcmap_move_layer",
        "arcmap_near",
        "arcmap_ping",
        "arcmap_project_features",
        "arcmap_query_features",
        "arcmap_refresh",
        "arcmap_refresh_native_unique_values",
        "arcmap_remove_layer",
        "arcmap_remove_native_grid",
        "arcmap_remove_temporary_layer",
        "arcmap_rename_layer",
        "arcmap_replace_data_source",
        "arcmap_restore_layer_style",
        "arcmap_restore_native_grid_state",
        "arcmap_restore_snapshot",
        "arcmap_rollback_map_recipe",
        "arcmap_save_current_map",
        "arcmap_select_by_attribute",
        "arcmap_select_by_location",
        "arcmap_set_class_breaks",
        "arcmap_set_definition_query",
        "arcmap_set_label_class",
        "arcmap_set_label_expression",
        "arcmap_set_layer_scale_range",
        "arcmap_set_layer_transparency",
        "arcmap_set_layer_visibility",
        "arcmap_set_layout_element_position",
        "arcmap_set_layout_element_state",
        "arcmap_set_layout_text",
        "arcmap_set_map_scale",
        "arcmap_set_native_grid_properties",
        "arcmap_set_native_label_preset",
        "arcmap_set_native_layer_properties",
        "arcmap_set_native_scale_bar",
        "arcmap_set_native_unique_values_renderer",
        "arcmap_set_title",
        "arcmap_set_unique_value_field",
        "arcmap_smart_corner_commit",
        "arcmap_smart_corner_preflight",
        "arcmap_smart_corner_preview",
        "arcmap_smart_corner_review",
        "arcmap_smart_corner_rollback",
        "arcmap_smart_corner_status",
        "arcmap_smart_corner_validate",
        "arcmap_snapshot_state",
        "arcmap_spatial_join",
        "arcmap_stage2_batch_build",
        "arcmap_stage2_build_a4",
        "arcmap_stage2_discover_data",
        "arcmap_stage2_generic_gp",
        "arcmap_stage2_list_checkpoints",
        "arcmap_stage2_preview_match",
        "arcmap_stage2_restore_checkpoint",
        "arcmap_stage2_validate_template",
        "arcmap_stage3_add_dataset_auto",
        "arcmap_stage3_blank_init",
        "arcmap_stage3_build_blank_a4",
        "arcmap_stage3_build_no_data_a4",
        "arcmap_stage3_create_featureclass",
        "arcmap_stage3_create_geometry_features",
        "arcmap_stage3_create_legend",
        "arcmap_stage3_create_neatline",
        "arcmap_stage3_create_north_arrow",
        "arcmap_stage3_create_scale_bar",
        "arcmap_stage3_create_text",
        "arcmap_stage3_create_xy_featureclass",
        "arcmap_stage3_ensure_dataframe",
        "arcmap_stage3_export_current",
        "arcmap_stage3_health",
        "arcmap_stage3_ingest_folder",
        "arcmap_stage3_restore_checkpoint",
        "arcmap_stage3_save_checkpoint",
        "arcmap_stage3_set_extent_auto",
        "arcmap_stage3_set_page_a4",
        "arcmap_toggle_labels",
        "arcmap_union_layers",
        "arcmap_update_native_category",
        "arcmap_validate_data_source",
        "arcmap_validate_layout_bounds",
        "arcmap_validate_map_recipe",
        "arcmap_visual_latest",
        "arcmap_visual_list",
        "arcmap_visual_prune",
        "arcmap_visual_snapshot",
        "arcmap_window_capture",
        "arcmap_zoom_to_layer",
    ];

    public static AgentManifest Create(
        string version,
        string bindHost,
        int port,
        string mcpPath = "/mcp",
        AgentEnvironment environment = AgentEnvironment.Production)
    {
        return new AgentManifest(
            ProtocolVersion: ZagentProductInfo.AgentProtocolVersion,
            Agent: new AgentIdentity(
                Id: AgentId,
                Name: "Zagent ArcMap",
                Version: version,
                Vendor: "Zagent"),
            Environment: environment,
            Runtime: new AgentRuntimeDescriptor(
                Language: "python",
                Version: "3.11",
                Entrypoint: "mcp_server.server_http"),
            Transport: new AgentTransportDescriptor(
                Kind: "http-mcp",
                BindHost: bindHost,
                Port: port,
                Path: mcpPath,
                LocalOnly: true),
            Lifecycle: new AgentLifecycleDescriptor(
                GracefulShutdownSeconds: 3),
            Health: new AgentHealthDescriptor(
                Probe: "mcp+arcmap-bridge",
                Target: $"http://{bindHost}:{port}{mcpPath}",
                IntervalSeconds: 10,
                TimeoutSeconds: 4),
            Capabilities:
                KnownToolNames.Select(CreateCapability).ToArray(),
            Dependencies:
            [
                new AgentDependencyDescriptor(
                    Id: "esri.arcmap.desktop",
                    Required: true,
                    MinimumVersion: "10.6.1",
                    External: true)
            ],
            Metadata: new Dictionary<string, string>
            {
                ["public_tool_count"] = KnownToolNames.Count.ToString(),
                ["stage2_tool_count"] = "8",
                ["stage3_tool_count"] = "20",
                ["arcmap_desktop_ownership"] = "external",
                ["bridge_ownership"] = "exclusive-session",
                ["default_export_formats"] = "PDF,PNG",
                ["default_export_dpi"] = "400",
                ["default_output_folder"] = "Hasil Peta"
            });
    }

    public static string ToCapabilityName(
        string toolName)
    {
        if (!toolName.StartsWith(
                "arcmap_",
                StringComparison.Ordinal))
        {
            throw new ArgumentException(
                $"Unexpected ArcMap tool name '{toolName}'.",
                nameof(toolName));
        }

        return "arcmap." + toolName[7..];
    }

    private static CapabilityDescriptor CreateCapability(
        string toolName)
    {
        var suffix = toolName[7..];
        var readOnly = IsReadOnly(suffix);
        var admin = IsAdmin(suffix);
        var background = IsBackground(suffix);

        return new CapabilityDescriptor(
            Name: ToCapabilityName(toolName),
            Description: $"Zagent ArcMap MCP tool {toolName}.",
            Access: admin
                ? CapabilityAccess.Admin
                : readOnly
                    ? CapabilityAccess.Read
                    : CapabilityAccess.Action,
            Execution: admin
                ? CapabilityExecution.Exclusive
                : background
                    ? CapabilityExecution.Background
                    : CapabilityExecution.Fast,
            Approval: admin
                ? CapabilityApproval.Policy
                : CapabilityApproval.None,
            SupportsCancel: false,
            SupportsProgress:
                suffix is "stage2_batch_build" or
                    "stage2_build_a4" or
                    "stage3_build_blank_a4",
            SupportsResume: false,
            ResourcePolicy: readOnly
                ? ResourcePolicy.ReadLock
                : ResourcePolicy.Exclusive);
    }

    private static bool IsReadOnly(string suffix) =>
        suffix is "agent_safety_status" or "ping" or
            "smart_corner_preflight" or "smart_corner_preview" or
            "smart_corner_review" or "smart_corner_validate" or
            "smart_corner_status" or
            "get_status" or "gp_preflight" or
            "goal_plan" or "goal_validate" or
            "goal_status" or "goal_report" or
            "inspect_current_map" or
            "export_preflight" or
            "stage3_health" ||
        suffix.StartsWith("get_", StringComparison.Ordinal) ||
        suffix.StartsWith("list_", StringComparison.Ordinal) ||
        suffix.StartsWith("validate_", StringComparison.Ordinal) ||
        suffix.StartsWith("compare_", StringComparison.Ordinal) ||
        suffix.StartsWith("query_", StringComparison.Ordinal) ||
        suffix is "stage2_discover_data" or
            "stage2_preview_match" or
            "stage2_validate_template" or
            "stage2_list_checkpoints" or
            "visual_latest" or
            "visual_list";

    private static bool IsAdmin(string suffix) =>
        suffix is "save_current_map" or
            "calculate_geometry_xy" or "import_coordinates_to_shp" or
            "smart_corner_commit" or "smart_corner_rollback" or
            "remove_native_grid" or
            "near" or
            "buffer" or
            "clip" or
            "dissolve" or
            "erase_features" or
            "intersect" or
            "union_layers" or
            "spatial_join" or
            "project_features" or
            "create_file_gdb" or
            "stage2_generic_gp" or
            "stage2_build_a4" or
            "stage2_batch_build" or
            "stage2_restore_checkpoint" or
            "stage3_create_featureclass" or
            "stage3_create_xy_featureclass" or
            "stage3_create_geometry_features" or
            "stage3_build_blank_a4" or
            "stage3_build_no_data_a4" or
            "stage3_restore_checkpoint" or
            "goal_build_map" or
            "goal_execute" or
            "goal_resume" or
            "goal_cancel" or
            "visual_prune";

    private static bool IsBackground(string suffix) =>
        suffix.StartsWith("export_", StringComparison.Ordinal) ||
        suffix is "apply_map_recipe" or
            "rollback_map_recipe" or
            "stage3_ingest_folder" or
            "stage3_export_current" or
            "visual_snapshot" or
            "window_capture";
}

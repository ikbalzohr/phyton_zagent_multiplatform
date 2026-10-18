# MCP Tool Catalog

## Read
- arcmap_agent_safety_status
- arcmap_ping
- arcmap_get_status
- arcmap_inspect_current_map
- arcmap_list_layout_text
- arcmap_list_layout_elements
- arcmap_list_layers

## Live unsaved write
- arcmap_set_title
- arcmap_set_layout_text
- arcmap_set_layout_element_position
- arcmap_set_map_scale
- arcmap_set_layer_visibility
- arcmap_zoom_to_layer
- arcmap_set_definition_query
- arcmap_add_layer
- arcmap_replace_data_source
- arcmap_toggle_labels
- arcmap_set_label_expression
- arcmap_apply_symbology_from_layer
- arcmap_select_by_attribute
- arcmap_clear_selection
- arcmap_refresh

## Destructive / persistent policy-gated
- arcmap_remove_layer (destructive policy)
- arcmap_save_current_map (save policy)

## Geoprocessing policy-gated
- arcmap_buffer
- arcmap_clip
- arcmap_dissolve
- arcmap_intersect
- arcmap_spatial_join
- arcmap_near (also requires destructive operations because ArcGIS Near adds NEAR_* fields to the input dataset)

## Export
- arcmap_export_pdf
- arcmap_export_png
- arcmap_export_jpeg

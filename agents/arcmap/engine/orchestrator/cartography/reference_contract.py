from __future__ import annotations

from copy import deepcopy


REFERENCE_ANALYSIS_SCHEMA = {
    "reference_type": "administration_map",
    "page": {
        "orientation": "landscape",
        "background_rgb": [207, 255, 190],
    },
    "regions": {
        "main_map": {"x": 0.032, "y": 0.035, "w": 0.688, "h": 0.93},
        "side_panel": {"x": 0.755, "y": 0.035, "w": 0.23, "h": 0.93},
    },
    "panel_sections": [
        "title",
        "orientation_scale",
        "legend",
        "crs",
        "provenance",
        "insets",
    ],
    "visual_hierarchy": [
        "project_boundary",
        "labels",
        "river",
        "road",
        "admin_polygon",
        "basemap",
    ],
    "inset_count": 2,
    "grid_on_all_sides": True,
}


def normalize_reference_analysis(value=None):
    value = deepcopy(value or {})
    out = deepcopy(REFERENCE_ANALYSIS_SCHEMA)
    for key, item in value.items():
        if isinstance(item, dict) and isinstance(out.get(key), dict):
            merged = deepcopy(out[key])
            merged.update(item)
            out[key] = merged
        else:
            out[key] = deepcopy(item)
    return out


def reference_analysis_prompt_contract():
    """
    Model-facing contract for an upstream vision system. The vision system
    should return normalized geometry and semantic observations, never ArcMap
    implementation details.
    """
    return {
        "coordinate_space": "normalized_page_0_1",
        "required": [
            "page.orientation",
            "regions.main_map",
            "regions.side_panel",
            "panel_sections",
            "visual_hierarchy",
            "inset_count",
            "grid_on_all_sides",
        ],
        "optional": [
            "dominant_colors",
            "title_lines",
            "legend_items",
            "typography",
            "section_ratios",
            "notes",
        ],
    }

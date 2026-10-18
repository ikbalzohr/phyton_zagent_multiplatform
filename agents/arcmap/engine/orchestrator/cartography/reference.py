from __future__ import annotations

from copy import deepcopy

DEFAULT_ADMIN_REFERENCE = {
    "reference_type": "administration_map",
    "page": {"orientation": "landscape"},
    "regions": {
        "main_map": {"x": 0.032, "y": 0.035, "w": 0.688, "h": 0.93},
        "side_panel": {"x": 0.755, "y": 0.035, "w": 0.23, "h": 0.93},
    },
    "panel_sections": ["title", "orientation_scale", "legend", "crs", "provenance", "insets"],
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
    "page_background": "light_green",
    "panel_background": "white",
}


def _merge(base, override):
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


class ReferenceLayoutInterpreter:
    """
    Converts model/vision-derived reference metrics into a deterministic
    cartographic target. The image understanding step can live outside ArcMap;
    the resulting normalized geometry is durable and auditable here.
    """

    def interpret(self, reference_analysis=None):
        return _merge(DEFAULT_ADMIN_REFERENCE, reference_analysis or {})

    def layout_similarity_targets(self, reference_analysis=None):
        ref = self.interpret(reference_analysis)
        return {
            "main_map_box": ref["regions"]["main_map"],
            "side_panel_box": ref["regions"]["side_panel"],
            "panel_sections": list(ref.get("panel_sections") or []),
            "inset_count": int(ref.get("inset_count") or 0),
            "grid_on_all_sides": bool(ref.get("grid_on_all_sides")),
            "visual_hierarchy": list(ref.get("visual_hierarchy") or []),
        }

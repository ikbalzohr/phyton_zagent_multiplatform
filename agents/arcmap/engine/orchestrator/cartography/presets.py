from __future__ import annotations

from copy import deepcopy


CARTOGRAPHIC_PRESETS = {
    "administration_reference_a4": {
        "target_mode": "CURRENT_IN_PLACE",
        "work_on_active_mxd": True,
        "source_edit_policy": "in_place",
        "save_policy": "overwrite",
        "cartographic_profile": "administration_a4_landscape",
        "persistence": {
            "mode": "CURRENT_MXD_IN_PLACE",
            "require_active_document": True,
            "require_document_in_project_root": True,
            "create_recovery_checkpoint": True,
            "save_current_mxd": True,
            "create_final_mxd_copy": False,
        },
        "layout": {
            "paper": "A4",
            "orientation": "landscape",
        },
        "outputs": {
            "formats": ["PDF", "PNG"],
            "dpi": 400,
            "save_mxd": True,
            "output_subdir": "Hasil Peta",
            "overwrite_policy": "deny",
        },
        "max_repair_cycles": 3,
        "visual_preview_dpi": 200,
        "reference_policy": {"require_analysis": True},
        "cartographic_notes": [
            "Main map occupies the left majority of the page.",
            "Information panel is vertical on the right.",
            "Project boundary is the dominant red outline.",
            "Roads are light neutral lines; rivers are cyan.",
            "Legend, north arrow, scale bar, CRS block, provenance and two insets are required.",
            "Grid/graticule labels are required on all sides.",
        ],
    },
    "administration_a4": {
        "target_mode": "CURRENT_IN_PLACE",
        "work_on_active_mxd": True,
        "source_edit_policy": "in_place",
        "save_policy": "overwrite",
        "cartographic_profile": "administration_a4_landscape",
        "persistence": {
            "mode": "CURRENT_MXD_IN_PLACE",
            "create_recovery_checkpoint": True,
            "save_current_mxd": True,
            "create_final_mxd_copy": False,
        },
        "outputs": {
            "formats": ["PDF", "PNG"],
            "dpi": 400,
            "save_mxd": True,
            "output_subdir": "Hasil Peta",
        },
    },
    "location_a4": {
        "target_mode": "CURRENT_IN_PLACE",
        "work_on_active_mxd": True,
        "source_edit_policy": "in_place",
        "save_policy": "overwrite",
        "cartographic_profile": "location_a4_landscape",
        "outputs": {
            "formats": ["PDF", "PNG"],
            "dpi": 400,
            "save_mxd": True,
            "output_subdir": "Hasil Peta",
        },
    },
    "thematic_a4": {
        "target_mode": "CURRENT_IN_PLACE",
        "work_on_active_mxd": True,
        "source_edit_policy": "in_place",
        "save_policy": "overwrite",
        "cartographic_profile": "thematic_a4_landscape",
        "outputs": {
            "formats": ["PDF", "PNG"],
            "dpi": 400,
            "save_mxd": True,
            "output_subdir": "Hasil Peta",
        },
    },
}


def _merge(base, override):
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def preset_names():
    return sorted(CARTOGRAPHIC_PRESETS)


def get_preset(name):
    key = str(name or "").strip()
    if key not in CARTOGRAPHIC_PRESETS:
        raise KeyError("Unknown cartographic preset: %s" % key)
    return deepcopy(CARTOGRAPHIC_PRESETS[key])


def apply_cartographic_preset(goal):
    goal = deepcopy(goal or {})
    name = str(goal.get("cartographic_preset") or "").strip()
    if not name:
        return goal
    preset = get_preset(name)
    merged = _merge(preset, goal)
    merged["cartographic_preset"] = name
    return merged

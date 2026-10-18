from __future__ import annotations

from copy import deepcopy

CARTOGRAPHIC_PROFILES = {
    "administration_a4_landscape": {
        "profile_version": "1.0",
        "paper": {"name": "A4", "orientation": "landscape", "width_cm": 29.7, "height_cm": 21.0},
        "layout": {
            "page_background_rgb": [207, 255, 190],
            "margin_cm": 0.15,
            "main_map": {"x": 0.032, "y": 0.035, "w": 0.688, "h": 0.93},
            "side_panel": {"x": 0.755, "y": 0.035, "w": 0.23, "h": 0.93},
            "panel_gap": 0.025,
            "sections": [
                {"id": "title", "height": 0.15},
                {"id": "orientation_scale", "height": 0.095},
                {"id": "legend", "height": 0.285},
                {"id": "crs", "height": 0.125},
                {"id": "provenance", "height": 0.115},
                {"id": "insets", "height": 0.23},
            ],
            "border_width_pt": 1.0,
            "divider_width_pt": 0.8,
        },
        "typography": {
            "font": "Arial",
            "title_pt": 15.0,
            "subtitle_pt": 11.0,
            "panel_heading_pt": 10.5,
            "body_pt": 8.0,
            "label_pt": 8.5,
            "label_rgb": [255, 230, 0],
            "label_halo_rgb": [0, 0, 0],
            "label_halo_pt": 1.2,
        },
        "symbology": {
            "project_boundary": {
                "line_rgb": [255, 0, 0],
                "line_width_pt": 2.6,
                "fill_rgb": [255, 0, 0],
                "fill_transparency": 100,
                "priority": 100,
            },
            "road": {
                "line_rgb": [235, 235, 235],
                "line_width_pt": 0.8,
                "priority": 55,
            },
            "river": {
                "line_rgb": [0, 190, 255],
                "line_width_pt": 0.75,
                "priority": 60,
            },
            "admin_polygon": {
                "line_rgb": [115, 70, 130],
                "line_width_pt": 0.55,
                "fill_rgb": [205, 150, 230],
                "fill_transparency": 82,
                "priority": 35,
            },
            "thematic_polygon": {
                "line_rgb": [120, 90, 50],
                "line_width_pt": 0.45,
                "fill_rgb": [230, 205, 120],
                "fill_transparency": 76,
                "priority": 30,
            },
            "basemap": {"priority": 0},
        },
        "labels": {
            "admin_polygon": {
                "field_candidates": ["DESA", "DESA_KELUR", "DESA_KEL", "NAMA_DESA", "NAME", "NAMOBJ"],
                "enabled": True,
                "remove_duplicates": True,
                "allow_overlap": False,
                "priority": 80,
            }
        },
        "scale": {
            "target_fill_ratio": 0.76,
            "margin_factor": 1.15,
            "nice_series": [1, 2, 2.5, 5, 10],
            "bar_segments": 4,
            "bar_subdivisions": 2,
            "units": "Meter",
        },
        "grid": {
            "enabled": True,
            "kind": "graticule",
            "format": "DMS",
            "labels": ["TOP", "BOTTOM", "LEFT", "RIGHT"],
            "max_lines_per_axis": 8,
            "min_lines_per_axis": 4,
        },
        "insets": {
            "count": 2,
            "selection_order": ["buol", "sulteng", "sulawesi", "indonesia"],
            "highlight_rgb": [255, 255, 0],
            "highlight_width_pt": 1.8,
        },
        "qa": {
            "min_main_map_ratio": 0.62,
            "max_main_map_ratio": 0.76,
            "min_side_panel_ratio": 0.20,
            "max_side_panel_ratio": 0.31,
            "max_label_overlap_ratio": 0.08,
            "max_whitespace_ratio": 0.18,
            "require_legend": True,
            "require_north_arrow": True,
            "require_scale_bar": True,
            "require_crs_block": True,
            "require_grid": True,
            "require_two_insets": True,
            "require_artifacts": ["PDF", "PNG"],
            "min_visual_score": 0.82,
            "min_reference_similarity": 0.88,
            "min_pixel_reference_similarity": 0.35,
        },
        "repair": {"max_cycles": 3},
    }
}


def _deep_merge(base, override):
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


PROFILE_VARIANTS = {
    "administration_a4_portrait": {
        "base": "administration_a4_landscape",
        "override": {
            "paper": {"orientation": "portrait", "width_cm": 21.0, "height_cm": 29.7},
            "layout": {
                "main_map": {"x": 0.035, "y": 0.29, "w": 0.93, "h": 0.675},
                "side_panel": {"x": 0.035, "y": 0.035, "w": 0.93, "h": 0.225},
                "sections": [
                    {"id": "title", "height": 0.18},
                    {"id": "orientation_scale", "height": 0.14},
                    {"id": "legend", "height": 0.20},
                    {"id": "crs", "height": 0.13},
                    {"id": "provenance", "height": 0.13},
                    {"id": "insets", "height": 0.22},
                ],
            },
        },
    },
    "location_a4_landscape": {
        "base": "administration_a4_landscape",
        "override": {
            "profile_version": "1.0-location",
            "layout": {
                "main_map": {"x": 0.025, "y": 0.035, "w": 0.735, "h": 0.93},
                "side_panel": {"x": 0.785, "y": 0.035, "w": 0.195, "h": 0.93},
            },
            "symbology": {
                "project_boundary": {"line_width_pt": 3.0},
                "road": {"line_width_pt": 0.7},
                "river": {"line_width_pt": 0.65},
            },
            "qa": {"min_reference_similarity": 0.84},
        },
    },
    "thematic_a4_landscape": {
        "base": "administration_a4_landscape",
        "override": {
            "profile_version": "1.0-thematic",
            "symbology": {
                "thematic_polygon": {
                    "line_rgb": [90, 70, 30],
                    "line_width_pt": 0.65,
                    "fill_rgb": [240, 205, 90],
                    "fill_transparency": 42,
                    "priority": 48,
                }
            },
            "layout": {
                "sections": [
                    {"id": "title", "height": 0.13},
                    {"id": "orientation_scale", "height": 0.09},
                    {"id": "legend", "height": 0.34},
                    {"id": "crs", "height": 0.12},
                    {"id": "provenance", "height": 0.12},
                    {"id": "insets", "height": 0.20},
                ]
            },
        },
    },
    "simple_a4_landscape": {
        "base": "administration_a4_landscape",
        "override": {
            "profile_version": "1.0-simple",
            "layout": {
                "main_map": {"x": 0.035, "y": 0.04, "w": 0.74, "h": 0.92},
                "side_panel": {"x": 0.80, "y": 0.04, "w": 0.17, "h": 0.92},
            },
            "grid": {"enabled": False},
            "insets": {"count": 1},
            "qa": {
                "require_grid": False,
                "require_two_insets": False,
                "min_reference_similarity": 0.0,
            },
        },
    },
}


def profile_names():
    return sorted(set(CARTOGRAPHIC_PROFILES) | set(PROFILE_VARIANTS))


def get_profile(name="administration_a4_landscape", overrides=None):
    name = str(name or "administration_a4_landscape")
    if name in CARTOGRAPHIC_PROFILES:
        base = CARTOGRAPHIC_PROFILES[name]
    elif name in PROFILE_VARIANTS:
        variant = PROFILE_VARIANTS[name]
        base_name = variant["base"]
        base = _deep_merge(
            CARTOGRAPHIC_PROFILES[base_name],
            variant.get("override") or {},
        )
    else:
        raise KeyError("Unknown cartographic profile: %s" % name)
    out = _deep_merge(base, overrides or {})
    out["profile_name"] = name
    return out

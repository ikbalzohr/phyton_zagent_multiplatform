from __future__ import annotations

import math


def nice_number(value, series=(1, 2, 2.5, 5, 10), ceiling=True):
    value = float(value or 0)
    if value <= 0:
        return value
    exponent = math.floor(math.log10(value))
    base = 10.0 ** exponent
    normalized = value / base
    ordered = list(series)
    if ceiling:
        for candidate in ordered:
            if normalized <= candidate:
                return candidate * base
        return 10.0 * base
    selected = ordered[0]
    for candidate in ordered:
        if candidate <= normalized:
            selected = candidate
        else:
            break
    return selected * base


def nice_scale(raw_scale, series=(1, 2, 2.5, 5, 10)):
    return int(round(nice_number(raw_scale, series=series, ceiling=True)))


def choose_scale(current_scale=None, extent_scale=None, margin_factor=1.15, series=(1, 2, 2.5, 5, 10)):
    source = float(extent_scale or current_scale or 0)
    if source <= 0:
        return None
    return nice_scale(source * float(margin_factor or 1.0), series=series)


def scale_bar_spec(scale, segments=4, subdivisions=2, units="Meter"):
    scale = float(scale or 0)
    if scale <= 0:
        return {"enabled": False}
    # Approximate useful ground length occupying ~25% of an A4 map width.
    target_ground = scale * 0.055
    total = nice_number(target_ground, ceiling=False)
    if total <= 0:
        total = target_ground
    segment = total / max(1, int(segments))
    return {
        "enabled": True,
        "scale": scale,
        "units": units,
        "segments": int(segments),
        "subdivisions": int(subdivisions),
        "total_ground_length": total,
        "segment_ground_length": segment,
        "labels": [round(segment * i, 3) for i in range(int(segments) + 1)],
    }


def graticule_interval(extent, geographic=True, min_lines=4, max_lines=8):
    if not extent:
        return None
    xmin = float(extent.get("xmin") if isinstance(extent, dict) else extent[0])
    ymin = float(extent.get("ymin") if isinstance(extent, dict) else extent[1])
    xmax = float(extent.get("xmax") if isinstance(extent, dict) else extent[2])
    ymax = float(extent.get("ymax") if isinstance(extent, dict) else extent[3])
    span = max(abs(xmax - xmin), abs(ymax - ymin))
    if span <= 0:
        return None
    target_lines = max(int(min_lines), min(int(max_lines), 6))
    raw = span / float(target_lines)
    if geographic:
        candidates = [
            1.0 / 3600.0, 2.0 / 3600.0, 5.0 / 3600.0, 10.0 / 3600.0,
            15.0 / 3600.0, 30.0 / 3600.0, 1.0 / 60.0, 2.0 / 60.0,
            5.0 / 60.0, 10.0 / 60.0, 15.0 / 60.0, 30.0 / 60.0,
            1.0, 2.0, 5.0,
        ]
        return min(candidates, key=lambda x: abs(x - raw))
    return nice_number(raw, ceiling=True)


def build_scale_grid_spec(dataframe_state, profile):
    scale_cfg = (profile or {}).get("scale") or {}
    grid_cfg = (profile or {}).get("grid") or {}
    scale = choose_scale(
        current_scale=(dataframe_state or {}).get("scale"),
        extent_scale=(dataframe_state or {}).get("extent_scale"),
        margin_factor=scale_cfg.get("margin_factor", 1.15),
        series=scale_cfg.get("nice_series") or [1, 2, 2.5, 5, 10],
    )
    extent = (dataframe_state or {}).get("extent")
    geographic = bool((dataframe_state or {}).get("is_geographic", True))
    interval = graticule_interval(
        extent,
        geographic=geographic,
        min_lines=grid_cfg.get("min_lines_per_axis", 4),
        max_lines=grid_cfg.get("max_lines_per_axis", 8),
    ) if grid_cfg.get("enabled", True) else None
    return {
        "scale": scale,
        "scale_bar": scale_bar_spec(
            scale,
            segments=scale_cfg.get("bar_segments", 4),
            subdivisions=scale_cfg.get("bar_subdivisions", 2),
            units=scale_cfg.get("units", "Meter"),
        ),
        "grid": dict(grid_cfg, interval=interval),
    }

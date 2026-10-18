from __future__ import annotations


class CartographicRepairEngine:
    def __init__(self, max_cycles=3):
        self.max_cycles = max(0, min(int(max_cycles), 3))

    def propose(self, qa_result, specification, cycle=1):
        if cycle < 1 or cycle > self.max_cycles:
            return {"ok": False, "status": "REPAIR_BUDGET_EXHAUSTED", "operations": []}
        operations = []
        for issue in (qa_result or {}).get("issues") or []:
            code = issue.get("code")
            if code == "LEGEND_OVERFLOW":
                operations.append({"action": "resize_legend", "factor": 1.15, "max_factor": 1.45})
                operations.append({"action": "reduce_legend_font", "delta_pt": -0.5, "min_pt": 6.5})
            elif code == "LABEL_COLLISION_EXCESSIVE":
                operations.append({"action": "reduce_label_font", "delta_pt": -0.5, "min_pt": 6.5})
                operations.append({"action": "increase_label_priority_filter", "delta": 10})
            elif code == "WHITESPACE_EXCESSIVE":
                operations.append({"action": "zoom_main_map", "factor": 0.90})
            elif code == "PROJECT_BOUNDARY_NOT_VISIBLE":
                operations.append({"action": "strengthen_role_style", "role": "project_boundary", "line_width_delta": 0.6})
            elif code == "MAIN_MAP_TOO_SMALL":
                operations.append({"action": "expand_main_map", "delta_ratio": 0.03})
            elif code == "MAIN_MAP_TOO_LARGE":
                operations.append({"action": "shrink_main_map", "delta_ratio": 0.02})
            elif code == "LAYOUT_OVERLAP":
                operations.append({"action": "reflow_side_panel", "gap_delta": 0.003})
            elif code in ("LEGEND_MISSING", "NORTH_ARROW_MISSING", "SCALE_BAR_MISSING", "CRS_BLOCK_MISSING"):
                operations.append({"action": "recreate_required_element", "code": code})
            elif code == "INSETS_INCOMPLETE":
                operations.append({"action": "rebuild_insets", "count": 2})
            elif code == "GRID_MISSING":
                operations.append({"action": "rebuild_grid"})
            elif code == "REFERENCE_LAYOUT_MISMATCH":
                operations.append({"action": "snap_layout_to_reference"})
            elif code in ("MAIN_MAP_OUT_OF_BOUNDS", "SIDE_PANEL_OUT_OF_BOUNDS"):
                operations.append({"action": "snap_layout_to_reference"})
            elif code == "ROAD_LOW_CONTRAST":
                operations.append({"action": "strengthen_role_style", "role": "road", "line_width_delta": 0.35})
            elif code == "RIVER_LOW_CONTRAST":
                operations.append({"action": "strengthen_role_style", "role": "river", "line_width_delta": 0.35})
            elif code in ("LEGEND_LOW_READABILITY", "LEGEND_OVERFLOW"):
                operations.append({"action": "resize_legend", "factor": 1.12, "max_factor": 1.45})
            elif code == "TITLE_LOW_READABILITY":
                operations.append({"action": "reflow_side_panel", "gap_delta": 0.002})
            elif code in ("INSET_LOW_READABILITY", "INSETS_INCOMPLETE"):
                operations.append({"action": "rebuild_insets", "count": 2})
            elif code in ("GRID_LOW_READABILITY", "GRID_MISSING"):
                operations.append({"action": "rebuild_grid"})
            elif code in ("SIDE_PANEL_TOO_SMALL", "SIDE_PANEL_TOO_LARGE"):
                operations.append({"action": "snap_layout_to_reference"})
        deduped = []
        seen = set()
        for op in operations:
            key = repr(sorted(op.items()))
            if key not in seen:
                seen.add(key)
                deduped.append(op)
        return {
            "ok": bool(deduped),
            "status": "REPAIR_PLANNED" if deduped else "NO_REPAIR_AVAILABLE",
            "cycle": int(cycle),
            "max_cycles": self.max_cycles,
            "operations": deduped,
        }

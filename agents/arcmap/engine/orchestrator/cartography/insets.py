from __future__ import annotations

from copy import deepcopy


class InsetPlanner:
    def plan(self, semantic_interpreter, semantic_layers, profile):
        config = deepcopy((profile or {}).get("insets") or {})
        count = int(config.get("count") or 2)
        selected = semantic_interpreter.choose_insets(
            semantic_layers or [],
            count=count,
            order=config.get("selection_order") or None,
        )
        items = []
        for idx, row in enumerate(selected):
            items.append({
                "name": "INSET_%02d" % (idx + 1),
                "path": row.get("path"),
                "source_name": row.get("name"),
                "semantic_role": row.get("semantic_role"),
                "context_rank": idx,
                "show_main_extent": True,
                "highlight_rgb": list(config.get("highlight_rgb") or [255, 255, 0]),
                "highlight_width_pt": float(config.get("highlight_width_pt") or 1.8),
            })
        return {
            "required_count": count,
            "count": len(items),
            "items": items,
            "config": config,
        }

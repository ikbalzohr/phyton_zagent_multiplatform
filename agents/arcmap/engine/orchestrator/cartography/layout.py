from __future__ import annotations

from copy import deepcopy


class CartographicLayoutComposer:
    """
    Deterministic normalized-page layout composer.

    Coordinates use a 0..1 page space so the same composition can be applied
    to ArcMap page units regardless of whether the underlying document reports
    centimetres, millimetres, or inches.
    """

    def section_boxes(self, layout):
        layout = deepcopy(layout or {})
        panel = layout.get("side_panel") or {}
        sections = layout.get("sections") or []
        x = float(panel.get("x") or 0)
        y = float(panel.get("y") or 0)
        w = float(panel.get("w") or 0)
        h = float(panel.get("h") or 0)
        weights = [max(0.0, float(row.get("height") or 0)) for row in sections]
        total = sum(weights) or 1.0
        cursor = y + h
        boxes = {}
        for row, weight in zip(sections, weights):
            height = h * (weight / total)
            cursor -= height
            boxes[str(row.get("id") or "section")] = {
                "x": x,
                "y": cursor,
                "w": w,
                "h": height,
            }
        return boxes

    def compose(self, profile, reference_target=None):
        profile = deepcopy(profile or {})
        reference = deepcopy(reference_target or {})
        layout = deepcopy(profile.get("layout") or {})
        regions = reference.get("regions") or {}
        if regions.get("main_map"):
            layout["main_map"] = deepcopy(regions["main_map"])
        if regions.get("side_panel"):
            layout["side_panel"] = deepcopy(regions["side_panel"])
        boxes = self.section_boxes(layout)
        return {
            "paper": deepcopy(profile.get("paper") or {}),
            "page_background_rgb": layout.get("page_background_rgb"),
            "main_map_box": deepcopy(layout.get("main_map") or {}),
            "side_panel_box": deepcopy(layout.get("side_panel") or {}),
            "section_boxes": boxes,
            "border_width_pt": float(layout.get("border_width_pt") or 1.0),
            "divider_width_pt": float(layout.get("divider_width_pt") or 0.8),
        }

    def geometry_manifest(self, composed):
        rows = []
        for name in ("main_map_box", "side_panel_box"):
            box = deepcopy((composed or {}).get(name) or {})
            rows.append({"id": name, "box": box, "kind": "region"})
        for name, box in ((composed or {}).get("section_boxes") or {}).items():
            rows.append({"id": name, "box": deepcopy(box), "kind": "section"})
        return rows

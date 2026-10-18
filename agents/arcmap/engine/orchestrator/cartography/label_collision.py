from __future__ import annotations


class LabelCollisionPolicy:
    def tune(self, label_plan, dataframe_scale=None, feature_counts=None):
        feature_counts = feature_counts or {}
        scale = float(dataframe_scale or 0)
        rows = []
        for row in label_plan or []:
            item = dict(row)
            count = int(feature_counts.get(item.get("layer_name"), 0) or 0)
            density = "normal"
            if count > 250:
                density = "high"
                item["font_size_pt"] = max(6.5, float(item.get("font_size_pt") or 8.5) - 1.0)
                item["allow_overlap"] = False
                item["remove_duplicates"] = True
            elif count > 100:
                density = "medium"
                item["font_size_pt"] = max(7.0, float(item.get("font_size_pt") or 8.5) - 0.5)
            if scale and scale > 150000:
                item["font_size_pt"] = max(6.5, float(item.get("font_size_pt") or 8.5) - 0.5)
            item["density_class"] = density
            rows.append(item)
        rows.sort(key=lambda x: (-int(x.get("priority") or 0), str(x.get("layer_name") or "")))
        return rows

    def collision_feedback_to_repairs(self, overlap_ratio):
        ratio = float(overlap_ratio or 0)
        if ratio <= 0.04:
            return []
        repairs = [{"action": "reduce_label_font", "delta_pt": -0.5, "min_pt": 6.5}]
        if ratio > 0.08:
            repairs.append({"action": "increase_label_priority_filter", "delta": 60})
        return repairs

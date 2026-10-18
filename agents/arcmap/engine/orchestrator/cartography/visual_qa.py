from __future__ import annotations

import math

from .vision_feedback import normalize_visual_feedback


def _area(box):
    if not box:
        return 0.0
    return max(0.0, float(box.get("w") or 0)) * max(0.0, float(box.get("h") or 0))


def _inside(box):
    if not box:
        return False
    x = float(box.get("x") or 0)
    y = float(box.get("y") or 0)
    w = float(box.get("w") or 0)
    h = float(box.get("h") or 0)
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= 1.0001 and y + h <= 1.0001


def _box_similarity(actual, target):
    if not actual or not target:
        return 0.0
    diffs = []
    for key in ("x", "y", "w", "h"):
        diffs.append(abs(float(actual.get(key) or 0) - float(target.get(key) or 0)))
    # Normalized layout coordinates are 0..1. A cumulative deviation of 0.4
    # is treated as completely dissimilar.
    penalty = min(1.0, sum(diffs) / 0.4)
    return max(0.0, 1.0 - penalty)


class CartographicVisualQA:
    def evaluate(self, metrics, specification, vision_feedback=None):
        metrics = metrics or {}
        spec = specification or {}
        qa = spec.get("qa") or {}
        issues = []
        checks = {}

        main_box = metrics.get("main_map_box") or ((spec.get("layout") or {}).get("main_map"))
        panel_box = metrics.get("side_panel_box") or ((spec.get("layout") or {}).get("side_panel"))
        main_area = _area(main_box)
        panel_area = _area(panel_box)
        checks["main_map_area_ratio"] = main_area
        checks["side_panel_area_ratio"] = panel_area

        reference = spec.get("reference_target") or {}
        regions = reference.get("regions") or {}
        main_similarity = _box_similarity(main_box, regions.get("main_map") or {})
        panel_similarity = _box_similarity(panel_box, regions.get("side_panel") or {})
        reference_similarity = (main_similarity + panel_similarity) / 2.0
        checks["reference_main_map_similarity"] = round(main_similarity, 4)
        checks["reference_side_panel_similarity"] = round(panel_similarity, 4)
        checks["reference_similarity"] = round(reference_similarity, 4)
        minimum_reference = float(qa.get("min_reference_similarity") or 0)
        if minimum_reference and reference_similarity < minimum_reference:
            issues.append({
                "code": "REFERENCE_LAYOUT_MISMATCH",
                "severity": "error",
                "actual": round(reference_similarity, 4),
                "minimum": minimum_reference,
            })

        if not _inside(main_box):
            issues.append({"code": "MAIN_MAP_OUT_OF_BOUNDS", "severity": "error"})
        if not _inside(panel_box):
            issues.append({"code": "SIDE_PANEL_OUT_OF_BOUNDS", "severity": "error"})
        if main_area < float(qa.get("min_main_map_ratio") or 0):
            issues.append({"code": "MAIN_MAP_TOO_SMALL", "severity": "error", "actual": main_area})
        if main_area > float(qa.get("max_main_map_ratio") or 1):
            issues.append({"code": "MAIN_MAP_TOO_LARGE", "severity": "warning", "actual": main_area})

        required_flags = {
            "legend_present": qa.get("require_legend"),
            "north_arrow_present": qa.get("require_north_arrow"),
            "scale_bar_present": qa.get("require_scale_bar"),
            "crs_block_present": qa.get("require_crs_block"),
            "grid_present": qa.get("require_grid"),
        }
        for metric_name, required in required_flags.items():
            checks[metric_name] = bool(metrics.get(metric_name))
            if required and not metrics.get(metric_name):
                issues.append({"code": metric_name.upper().replace("_PRESENT", "_MISSING"), "severity": "error"})

        inset_count = int(metrics.get("inset_count") or 0)
        checks["inset_count"] = inset_count
        if qa.get("require_two_insets") and inset_count < 2:
            issues.append({"code": "INSETS_INCOMPLETE", "severity": "error", "actual": inset_count, "required": 2})

        label_overlap = float(metrics.get("label_overlap_ratio") or 0)
        whitespace = float(metrics.get("whitespace_ratio") or 0)
        checks["label_overlap_ratio"] = label_overlap
        checks["whitespace_ratio"] = whitespace
        if label_overlap > float(qa.get("max_label_overlap_ratio") or 1):
            issues.append({"code": "LABEL_COLLISION_EXCESSIVE", "severity": "warning", "actual": label_overlap})
        if whitespace > float(qa.get("max_whitespace_ratio") or 1):
            issues.append({"code": "WHITESPACE_EXCESSIVE", "severity": "warning", "actual": whitespace})

        if metrics.get("legend_overflow"):
            issues.append({"code": "LEGEND_OVERFLOW", "severity": "error"})
        if metrics.get("layout_overlap_count", 0):
            issues.append({"code": "LAYOUT_OVERLAP", "severity": "error", "count": metrics.get("layout_overlap_count")})
        if metrics.get("broken_data_sources"):
            issues.append({"code": "BROKEN_DATA_SOURCE", "severity": "error", "items": metrics.get("broken_data_sources")})
        if not metrics.get("project_boundary_visible", True):
            issues.append({"code": "PROJECT_BOUNDARY_NOT_VISIBLE", "severity": "error"})

        feedback = normalize_visual_feedback(vision_feedback or {})
        feedback_metrics = feedback.get("metrics") or {}
        for key in ("label_overlap_ratio", "whitespace_ratio"):
            if feedback_metrics.get(key) is not None:
                checks[key] = float(feedback_metrics[key])
                if key == "label_overlap_ratio":
                    label_overlap = float(feedback_metrics[key])
                elif key == "whitespace_ratio":
                    whitespace = float(feedback_metrics[key])
        if feedback_metrics.get("label_overlap_ratio") is not None:
            ratio = float(feedback_metrics["label_overlap_ratio"])
            if ratio > float(qa.get("max_label_overlap_ratio") or 1):
                if not any(x.get("code") == "LABEL_COLLISION_EXCESSIVE" for x in issues):
                    issues.append({"code": "LABEL_COLLISION_EXCESSIVE", "severity": "warning", "actual": ratio})
        if feedback_metrics.get("whitespace_ratio") is not None:
            ratio = float(feedback_metrics["whitespace_ratio"])
            if ratio > float(qa.get("max_whitespace_ratio") or 1):
                if not any(x.get("code") == "WHITESPACE_EXCESSIVE" for x in issues):
                    issues.append({"code": "WHITESPACE_EXCESSIVE", "severity": "warning", "actual": ratio})
        for item in feedback.get("issues") or []:
            issues.append(dict(item))
        visual_score = feedback.get("score")
        if visual_score is None:
            penalties = sum(0.14 if x.get("severity") == "error" else 0.05 for x in issues)
            visual_score = max(0.0, 1.0 - penalties)
        checks["visual_score"] = round(float(visual_score), 4)

        errors = [x for x in issues if x.get("severity") == "error"]
        min_score = float(qa.get("min_visual_score") or 0)
        ok = not errors and float(visual_score) >= min_score
        return {
            "ok": ok,
            "status": "PASS" if ok else "FAIL",
            "score": round(float(visual_score), 4),
            "minimum_score": min_score,
            "checks": checks,
            "issues": issues,
            "errors": errors,
            "warnings": [x for x in issues if x.get("severity") != "error"],
        }

from __future__ import annotations

from copy import deepcopy


VISUAL_FEEDBACK_SCHEMA = {
    "score": None,
    "issues": [],
    "metrics": {
        "label_overlap_ratio": None,
        "whitespace_ratio": None,
        "project_boundary_contrast": None,
        "road_readability": None,
        "river_readability": None,
        "legend_readability": None,
        "title_readability": None,
        "inset_readability": None,
        "grid_readability": None,
        "panel_balance": None,
        "reference_similarity": None,
    },
    "observations": [],
}


ALLOWED_ISSUES = {
    "LABEL_COLLISION_EXCESSIVE",
    "WHITESPACE_EXCESSIVE",
    "PROJECT_BOUNDARY_NOT_VISIBLE",
    "ROAD_LOW_CONTRAST",
    "RIVER_LOW_CONTRAST",
    "LEGEND_OVERFLOW",
    "LEGEND_LOW_READABILITY",
    "TITLE_LOW_READABILITY",
    "INSETS_INCOMPLETE",
    "INSET_LOW_READABILITY",
    "GRID_MISSING",
    "GRID_LOW_READABILITY",
    "LAYOUT_OVERLAP",
    "REFERENCE_LAYOUT_MISMATCH",
    "MAIN_MAP_TOO_SMALL",
    "MAIN_MAP_TOO_LARGE",
    "SIDE_PANEL_TOO_SMALL",
    "SIDE_PANEL_TOO_LARGE",
}


def normalize_visual_feedback(value=None):
    value = deepcopy(value or {})
    out = deepcopy(VISUAL_FEEDBACK_SCHEMA)
    if value.get("score") is not None:
        out["score"] = max(0.0, min(1.0, float(value["score"])))
    metrics = value.get("metrics") or {}
    out["metrics"].update(metrics)
    out["observations"] = [str(x) for x in (value.get("observations") or [])]
    issues = []
    for row in value.get("issues") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").upper()
        if code not in ALLOWED_ISSUES:
            continue
        severity = str(row.get("severity") or "warning").lower()
        if severity not in ("warning", "error"):
            severity = "warning"
        item = dict(row)
        item["code"] = code
        item["severity"] = severity
        issues.append(item)
    out["issues"] = issues
    return out


def visual_feedback_prompt_contract():
    return {
        "input": "rendered ArcMap layout preview",
        "score_range": [0.0, 1.0],
        "required_checks": [
            "overall composition",
            "main-map versus side-panel balance",
            "title hierarchy and readability",
            "legend readability and overflow",
            "north arrow and scale visibility",
            "project-boundary visual dominance",
            "road and river contrast",
            "label collision and clipping",
            "grid/graticule readability",
            "inset map readability and extent highlight",
            "excess whitespace",
            "similarity to supplied reference composition",
        ],
        "output_schema": deepcopy(VISUAL_FEEDBACK_SCHEMA),
        "allowed_issue_codes": sorted(ALLOWED_ISSUES),
    }


def merge_visual_feedback(*values):
    merged = normalize_visual_feedback({})
    scores = []
    issues = []
    observations = []
    metrics = dict(merged.get("metrics") or {})
    seen = set()
    for value in values:
        current = normalize_visual_feedback(value or {})
        if current.get("score") is not None:
            scores.append(float(current["score"]))
        for issue in current.get("issues") or []:
            key = (issue.get("code"), issue.get("severity"), str(issue.get("reason") or ""))
            if key not in seen:
                seen.add(key)
                issues.append(dict(issue))
        observations.extend(str(x) for x in (current.get("observations") or []))
        for key, item in (current.get("metrics") or {}).items():
            if item is not None:
                metrics[key] = item
    return normalize_visual_feedback({
        "score": (sum(scores) / float(len(scores))) if scores else None,
        "issues": issues,
        "metrics": metrics,
        "observations": observations,
    })

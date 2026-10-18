# -*- coding: utf-8 -*-
"""Deterministic smart-corner geometry, shared by ArcMap 10.6 Python 2.7 and unit tests.

No ArcPy, COM, file IO, screenshots or live MXD state in this module.
Input vertices are source vertex records with x/y (original map coordinates),
metric_x/metric_y (analysis coordinates in metres), vertex_index.
The original XY is never resampled, averaged, simplified or moved.
"""
from __future__ import division

import hashlib
import json
import math


class CornerGeometryError(ValueError):
    def __init__(self, code, message):
        ValueError.__init__(self, code + ": " + message)
        self.code = code


def _finite(value):
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise CornerGeometryError("INVALID_GEOMETRY", "Non-finite coordinate")
    return number


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point(row):
    if isinstance(row, dict):
        x = _finite(row["x"])
        y = _finite(row["y"])
        mx = _finite(row.get("metric_x", x))
        my = _finite(row.get("metric_y", y))
        index = int(row.get("vertex_index", 0))
    else:
        x, y = _finite(row[0]), _finite(row[1])
        mx, my, index = x, y, 0
    return {"x": x, "y": y, "metric_x": mx, "metric_y": my,
            "vertex_index": index}


def ring_area(ring):
    """Signed metric shoelace area: negative means clockwise."""
    total = 0.0
    for idx, p in enumerate(ring):
        q = ring[(idx + 1) % len(ring)]
        total += p["metric_x"] * q["metric_y"] - q["metric_x"] * p["metric_y"]
    return total * 0.5


def _orientation(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _between(a, b, c, eps):
    return (min(a[0], b[0]) - eps <= c[0] <= max(a[0], b[0]) + eps and
            min(a[1], b[1]) - eps <= c[1] <= max(a[1], b[1]) + eps)


def _crossing(a, b, c, d, eps):
    # Robust enough for input preflight, independent of map display scale.
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    if o1 * o2 < -eps and o3 * o4 < -eps:
        return True
    for o, p, q, r in ((o1, a, b, c), (o2, a, b, d),
                       (o3, c, d, a), (o4, c, d, b)):
        if abs(o) <= eps and _between(p, q, r, eps):
            return True
    return False


def _ensure_simple_ring(ring, eps):
    n = len(ring)
    points = [(p["metric_x"], p["metric_y"]) for p in ring]
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or j == (i + 1) % n or (j + 1) % n == i:
                continue
            if _crossing(a, b, points[j], points[(j + 1) % n], eps):
                raise CornerGeometryError("INVALID_GEOMETRY", "Self-intersecting polygon ring")


def normalize_ring(vertices, coordinate_epsilon=1e-8, anchor="northmost_west_tie"):
    """Normalize a single, closed/unclosed outer ring without changing geometry.

    Removes only closure and consecutive *analytically duplicate* points.
    Source vertex_index remains attached to original vertices.
    """
    if anchor != "northmost_west_tie":
        raise CornerGeometryError("UNSUPPORTED_ANCHOR", "Only northmost_west_tie supported")
    epsilon = _finite(coordinate_epsilon)
    if epsilon <= 0:
        raise CornerGeometryError("INVALID_TOLERANCE", "coordinate_epsilon must be positive")
    raw = []
    for idx, row in enumerate(vertices):
        item = _point(row)
        if not isinstance(row, dict) or "vertex_index" not in row:
            item["vertex_index"] = idx
        raw.append(item)
    if len(raw) >= 2 and _distance(
        (raw[0]["metric_x"], raw[0]["metric_y"]),
        (raw[-1]["metric_x"], raw[-1]["metric_y"])) <= epsilon:
        raw.pop()
    ring = []
    dropped = []
    for item in raw:
        if ring and _distance((ring[-1]["metric_x"], ring[-1]["metric_y"]),
                              (item["metric_x"], item["metric_y"])) <= epsilon:
            dropped.append(item["vertex_index"])
        else:
            ring.append(item)
    if len(ring) >= 2 and _distance(
            (ring[0]["metric_x"], ring[0]["metric_y"]),
            (ring[-1]["metric_x"], ring[-1]["metric_y"])) <= epsilon:
        dropped.append(ring[-1]["vertex_index"])
        ring.pop()
    if len(ring) < 3:
        raise CornerGeometryError("INVALID_GEOMETRY", "Fewer than three distinct vertices")
    signed = ring_area(ring)
    xs = [p["metric_x"] for p in ring]
    ys = [p["metric_y"] for p in ring]
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    if abs(signed) <= max(epsilon * epsilon, extent * epsilon * 0.01):
        raise CornerGeometryError("INVALID_GEOMETRY", "Zero/degenerate area")
    _ensure_simple_ring(ring, epsilon * epsilon)
    source_winding = "CW" if signed < 0 else "CCW"
    if signed > 0:
        ring.reverse()
    # Stable across ring starting index and reversed orientation.
    start = min(range(len(ring)), key=lambda i: (
        -ring[i]["metric_y"], ring[i]["metric_x"],
        ring[i]["vertex_index"]))
    ring = ring[start:] + ring[:start]
    return {"vertices": ring, "source_winding": source_winding,
            "clockwise": ring_area(ring) < 0, "removed_duplicate_indices": dropped}


def _offset_to_chord(a, b, p):
    vx, vy = b[0] - a[0], b[1] - a[1]
    length_sq = vx * vx + vy * vy
    if length_sq <= 0:
        return _distance(a, p)
    t = min(1.0, max(0.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / length_sq))
    return _distance(p, (a[0] + t * vx, a[1] + t * vy))


def classify_vertices(vertices, min_turn_deg=45.0, straight_turn_deg=3.0,
                      collinear_tolerance_m=0.05, coordinate_epsilon_m=1e-8,
                      min_segment_length_m=0.0):
    """Return all candidates and their reasons. REVIEW points are not auto-committed."""
    threshold = _finite(min_turn_deg)
    straight = _finite(straight_turn_deg)
    tolerance = _finite(collinear_tolerance_m)
    shortest = _finite(min_segment_length_m)
    if not (0 < straight < threshold < 180) or tolerance < 0 or shortest < 0:
        raise CornerGeometryError("INVALID_PARAMETERS", "Angle/tolerance thresholds invalid")
    normalized = normalize_ring(vertices, coordinate_epsilon_m)
    ring = normalized["vertices"]
    result = []
    for i, vertex in enumerate(ring):
        prev = ring[(i - 1) % len(ring)]
        nxt = ring[(i + 1) % len(ring)]
        a = (prev["metric_x"], prev["metric_y"])
        p = (vertex["metric_x"], vertex["metric_y"])
        b = (nxt["metric_x"], nxt["metric_y"])
        v1 = (p[0] - a[0], p[1] - a[1])
        v2 = (b[0] - p[0], b[1] - p[1])
        prev_len = math.hypot(v1[0], v1[1])
        next_len = math.hypot(v2[0], v2[1])
        if min(prev_len, next_len) <= coordinate_epsilon_m:
            raise CornerGeometryError("INVALID_GEOMETRY", "Zero-length ring edge")
        signed_turn = math.degrees(math.atan2(
            v1[0] * v2[1] - v1[1] * v2[0],
            v1[0] * v2[0] + v1[1] * v2[1]))
        turn = abs(signed_turn)
        offset = _offset_to_chord(a, b, p)
        if turn >= 175:
            kind, reason = "REVIEW", "HAIRPIN_OR_SPIKE"
        elif shortest > 0 and min(prev_len, next_len) < shortest:
            kind, reason = "REVIEW", "SHORT_SEGMENT_AMBIGUOUS"
        elif turn >= threshold:
            kind, reason = "CORNER", "SIGNIFICANT_DIRECTION_CHANGE"
        elif turn <= straight and offset <= tolerance:
            kind, reason = "STRAIGHT", "LOW_TURN_COLLINEAR"
        else:
            kind, reason = "REVIEW", "INTERMEDIATE_BEND_OR_NOISE"
        result.append({
            "vertex_index": vertex["vertex_index"], "x": vertex["x"],
            "y": vertex["y"], "metric_x": vertex["metric_x"],
            "metric_y": vertex["metric_y"], "clockwise_position": i + 1,
            "class": kind, "reason_code": reason,
            "signed_turn_deg": signed_turn, "absolute_turn_deg": turn,
            "chord_offset_m": offset, "previous_length_m": prev_len,
            "next_length_m": next_len
        })
    counts = {k: len([p for p in result if p["class"] == k])
              for k in ("CORNER", "STRAIGHT", "REVIEW")}
    return {"clockwise": True, "source_winding": normalized["source_winding"],
            "removed_duplicate_indices": normalized["removed_duplicate_indices"],
            "candidates": result, "counts": counts}


def select_reviewed_candidates(analysis, include_indices=None, exclude_indices=None,
                               require_minimum=False):
    """Reviewed corners follow boundary traversal, not angle-sort to centroid."""
    include_indices = list(include_indices or [])
    exclude_indices = list(exclude_indices or [])
    include = set(int(i) for i in include_indices)
    exclude = set(int(i) for i in exclude_indices)
    if len(include) != len(include_indices) or len(exclude) != len(exclude_indices):
        raise CornerGeometryError("INVALID_REVIEW", "Duplicate override indices")
    all_indices = set(int(x["vertex_index"]) for x in analysis["candidates"])
    if (include | exclude) - all_indices or include & exclude:
        raise CornerGeometryError("INVALID_REVIEW", "Unknown/conflicting review vertex indices")
    selected = []
    for candidate in analysis["candidates"]:
        index = int(candidate["vertex_index"])
        if (candidate["class"] == "CORNER" and index not in exclude) or index in include:
            row = dict(candidate)
            row["Id"] = len(selected) + 1
            row["decision"] = "MANUAL_INCLUDE" if index in include else "AUTO_CORNER"
            selected.append(row)
    if require_minimum and len(selected) < 3:
        raise CornerGeometryError("ZERO_CANDIDATES", "Fewer than three reviewed corners")
    coordinates = [(x["x"], x["y"]) for x in selected]
    if len(set(coordinates)) != len(coordinates):
        raise CornerGeometryError("INVALID_REVIEW", "Repeated candidate coordinates")
    return selected


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()

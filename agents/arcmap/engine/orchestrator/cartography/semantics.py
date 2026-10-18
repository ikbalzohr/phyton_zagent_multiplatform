from __future__ import annotations

import os
import re

ROLE_RULES = [
    ("project_boundary", [
        r"^(pt|izin|iup|konsesi|project|proyek)\b.*?(pl|polygon)?$",
        r"buol.*agri.*lestari",
        r"batas.*(pt|izin|project)",
    ]),
    ("road", [r"jalan", r"road", r"transport"]),
    ("river", [r"sungai", r"aliran", r"river", r"hidro"]),
    ("admin_polygon", [r"desa", r"kelur", r"kecamatan", r"admin"]),
    ("thematic_polygon", [r"pippib", r"tutupan", r"kawasan", r"fungsi", r"landuse"]),
    ("basemap", [r"basemap", r"google.*earth", r"satellite", r"citra", r"imagery"]),
    ("inset", [r"inset", r"indonesia", r"sulawesi", r"sulteng", r"buol"]),
]

GEOMETRY_BONUS = {
    "project_boundary": {"Polygon": 0.12},
    "admin_polygon": {"Polygon": 0.10},
    "thematic_polygon": {"Polygon": 0.08},
    "road": {"Polyline": 0.12, "Line": 0.12},
    "river": {"Polyline": 0.12, "Line": 0.12},
}


def _text(item):
    path = str((item or {}).get("path") or (item or {}).get("relative") or (item or {}).get("name") or "")
    return re.sub(r"[^a-z0-9]+", " ", os.path.basename(path).lower()).strip()


class DatasetSemanticInterpreter:
    def classify(self, item):
        text = _text(item)
        geometry = str((item or {}).get("shape_type") or (item or {}).get("geometry") or "")
        candidates = []
        for role, patterns in ROLE_RULES:
            score = 0.0
            matches = []
            for pattern in patterns:
                if re.search(pattern, text, re.I):
                    score += 0.42 if not matches else 0.18
                    matches.append(pattern)
            score += GEOMETRY_BONUS.get(role, {}).get(geometry, 0.0)
            if role == "basemap" and str((item or {}).get("kind") or "").upper() in ("ECW", "TIF", "TIFF", "IMG", "SID", "RASTERDATASET"):
                score += 0.35
            if role == "inset" and "inset" in text:
                score += 0.35
            if score > 0:
                candidates.append({"role": role, "score": min(score, 1.0), "matches": matches})
        if "pippib" in text:
            candidates.append({"role": "thematic_polygon", "score": 0.98, "matches": ["pippib_override"]})
        if text.startswith("inset ") or " inset " in (" " + text + " "):
            candidates.append({"role": "inset", "score": 0.99, "matches": ["inset_override"]})
        candidates.sort(key=lambda x: (-x["score"], x["role"]))
        role = candidates[0]["role"] if candidates else "unknown"
        confidence = candidates[0]["score"] if candidates else 0.0
        out = dict(item or {})
        out["semantic_role"] = role
        out["semantic_confidence"] = round(confidence, 4)
        out["semantic_candidates"] = candidates[:4]
        return out

    def interpret(self, items):
        rows = [self.classify(item) for item in (items or [])]
        rows.sort(key=lambda x: (
            -float(x.get("semantic_confidence") or 0.0),
            str(x.get("semantic_role") or ""),
            str(x.get("name") or x.get("path") or ""),
        ))
        return rows

    def choose(self, rows, role, required=False):
        candidates = [x for x in (rows or []) if x.get("semantic_role") == role]
        if not candidates:
            if required:
                raise ValueError("Required semantic role not found: %s" % role)
            return None
        return sorted(candidates, key=lambda x: (-float(x.get("semantic_confidence") or 0.0), len(str(x.get("path") or ""))))[0]

    def choose_main_basemap(self, rows):
        candidates = [x for x in (rows or []) if x.get("semantic_role") == "basemap"]
        if not candidates:
            return None
        def rank(row):
            name = str(row.get("name") or row.get("path") or "").lower()
            alternate_penalty = 1 if re.search(r"[_\-\s](copy|backup|bak|old|\d+)$", os.path.splitext(name)[0]) else 0
            suffix_penalty = 1 if re.search(r"[_\-]2(?:\.|$)", name) else 0
            size = int(row.get("size_bytes") or 0)
            confidence = float(row.get("semantic_confidence") or 0.0)
            return (
                alternate_penalty + suffix_penalty,
                -confidence,
                -size,
                len(name),
                name,
            )
        return sorted(candidates, key=rank)[0]

    def choose_insets(self, rows, count=2, order=None):
        order = order or ["buol", "sulteng", "sulawesi", "indonesia"]
        explicit_insets = [
            x for x in (rows or [])
            if x.get("semantic_role") == "inset"
        ]
        candidates = explicit_insets or [
            x for x in (rows or [])
            if x.get("semantic_role") == "basemap"
        ]

        buckets = dict((idx, []) for idx in range(len(order)))
        fallback = []
        for row in candidates:
            text = _text(row)
            matched_rank = None
            for idx, token in enumerate(order):
                if token in text:
                    matched_rank = idx
                    break
            target = buckets.get(matched_rank) if matched_rank is not None else fallback
            target.append(row)

        def score(row):
            return (
                -float(row.get("semantic_confidence") or 0.0),
                -int(row.get("size_bytes") or 0),
                str(row.get("path") or ""),
            )

        selected = []
        seen = set()
        # First pass: one best inset per geographic context.
        for idx in range(len(order)):
            rows_for_rank = sorted(buckets[idx], key=score)
            for row in rows_for_rank:
                path = str(row.get("path") or "")
                if path and path not in seen:
                    seen.add(path)
                    selected.append(row)
                    break
            if len(selected) >= int(count):
                return selected[:int(count)]

        # Second pass: remaining explicit inset candidates, then fallback basemaps.
        remaining = []
        for idx in range(len(order)):
            remaining.extend(sorted(buckets[idx], key=score)[1:])
        remaining.extend(sorted(fallback, key=score))
        for row in remaining:
            path = str(row.get("path") or "")
            if path and path not in seen:
                seen.add(path)
                selected.append(row)
            if len(selected) >= int(count):
                break
        return selected[:int(count)]

    def layer_order(self, rows):
        priority = {
            "basemap": 0,
            "admin_polygon": 20,
            "thematic_polygon": 30,
            "river": 60,
            "road": 70,
            "project_boundary": 100,
            "unknown": 10,
            "inset": -10,
        }
        return sorted(rows or [], key=lambda x: priority.get(x.get("semantic_role"), 10))


ADMIN_FIELD_CANDIDATES = {
    "desa": ["DESA", "DESA_KELUR", "DESA_KEL", "KELURAHAN", "NAMA_DESA", "NAMOBJ"],
    "kecamatan": ["KECAMATAN", "KEC", "NAMA_KEC", "WADMKC"],
    "kabupaten": ["KAB_KOTA", "KABUPATEN", "KAB", "NAMA_KAB", "WADMKK"],
    "provinsi": ["PROVINSI", "PROPINSI", "PROV", "NAMA_PROV", "WADMPR"],
}


def infer_administrative_location(samples):
    """
    Resolve administrative hierarchy only from supplied authoritative samples.
    Samples may be feature attribute dictionaries or metadata rows containing
    an 'attributes' object. Conflicting values are not guessed; the most common
    non-empty value is selected and conflicts are reported.
    """
    samples = samples or []
    resolved = {}
    conflicts = {}
    for level, candidates in ADMIN_FIELD_CANDIDATES.items():
        values = []
        for sample in samples:
            attrs = sample.get("attributes") if isinstance(sample, dict) else None
            attrs = attrs if isinstance(attrs, dict) else (sample if isinstance(sample, dict) else {})
            lookup = dict((str(k).upper(), v) for k, v in attrs.items())
            for candidate in candidates:
                value = lookup.get(candidate.upper())
                if value not in (None, ""):
                    text = str(value).strip()
                    if text:
                        values.append(text)
                        break
        if not values:
            continue
        counts = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        resolved[level] = ranked[0][0]
        if len(ranked) > 1:
            conflicts[level] = [{"value": value, "count": count} for value, count in ranked]
    return {
        "location": resolved,
        "conflicts": conflicts,
        "authoritative_sample_count": len(samples),
    }

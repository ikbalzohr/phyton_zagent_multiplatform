from __future__ import annotations

import re
from copy import deepcopy

_ACTIVE_MXD_PATTERNS = (
    r"\bmxd\s+aktif\b",
    r"\bactive\s+mxd\b",
    r"\bcurrent\s+mxd\b",
    r"\bfile\s+mxd\s+yang\s+aktif\b",
    r"\bgunakan\s+mxd\s+aktif\b",
    r"\bkerjakan\s+.*mxd\s+aktif\b",
    r"\bsimpan\s+.*mxd\s+yang\s+sama\b",
)

_REFERENCE_PATTERNS = (
    r"seperti\s+(contoh|referensi|gambar)",
    r"ikuti\s+(contoh|referensi|gambar)",
    r"sesuai\s+(contoh|referensi|gambar)",
)


def _raw_text(goal):
    return " ".join([
        str((goal or {}).get("raw_goal") or ""),
        str((goal or {}).get("interpreted_goal") or ""),
        str((goal or {}).get("title") or ""),
    ]).strip()


def _parse_ignore_datasets(text):
    values = []
    patterns = [
        r"abaikan(?:\s+dulu)?\s+['\"]?([A-Za-z0-9_.-]+)",
        r"jangan\s+gunakan\s+['\"]?([A-Za-z0-9_.-]+)",
        r"exclude\s+['\"]?([A-Za-z0-9_.-]+)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            token = str(match).strip("'\".,;: ")
            if token and token.lower() not in {x.lower() for x in values}:
                values.append(token)
    return values


def infer_goal_defaults(goal):
    out = deepcopy(goal or {})
    text = _raw_text(out)
    low = text.lower()

    if any(re.search(pattern, low, re.I) for pattern in _ACTIVE_MXD_PATTERNS):
        out["work_on_active_mxd"] = True

    if not out.get("cartographic_preset"):
        if "peta administrasi" in low or "administration map" in low:
            has_reference = bool(out.get("reference_image") or out.get("reference_analysis"))
            out["cartographic_preset"] = (
                "administration_reference_a4"
                if has_reference or any(re.search(pattern, low, re.I) for pattern in _REFERENCE_PATTERNS)
                else "administration_a4"
            )
        elif any(token in low for token in ("peta lokasi", "location map", "peta situasi")):
            out["cartographic_preset"] = "location_a4"
        elif any(token in low for token in ("peta tematik", "thematic map", "pippib", "tutupan lahan")):
            out["cartographic_preset"] = "thematic_a4"

    if any(re.search(pattern, low, re.I) for pattern in _REFERENCE_PATTERNS):
        policy = dict(out.get("reference_policy") or {})
        policy.setdefault("require_analysis", True)
        out["reference_policy"] = policy

    dpi = re.search(r"\b(\d{3,4})\s*dpi\b", low, re.I)
    if dpi:
        outputs = dict(out.get("outputs") or {})
        outputs["dpi"] = max(72, min(2400, int(dpi.group(1))))
        out["outputs"] = outputs

    ignored = list(out.get("ignore_datasets") or [])
    for token in _parse_ignore_datasets(text):
        if token.lower() not in {str(x).lower() for x in ignored}:
            ignored.append(token)
    if ignored:
        out["ignore_datasets"] = ignored

    if "hasil peta" in low:
        outputs = dict(out.get("outputs") or {})
        outputs.setdefault("output_subdir", "Hasil Peta")
        out["outputs"] = outputs

    return out

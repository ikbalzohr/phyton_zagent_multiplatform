from __future__ import annotations

import os
import re
from datetime import datetime


def build_crs_block(spatial_reference):
    sr = spatial_reference or {}
    if isinstance(sr, str):
        return {
            "coordinate_system": sr,
            "projection": "",
            "datum": "",
            "units": "",
        }
    return {
        "coordinate_system": sr.get("name") or sr.get("spatial_reference") or "",
        "projection": sr.get("projection") or sr.get("projection_name") or "",
        "datum": sr.get("datum") or sr.get("datum_name") or "",
        "units": sr.get("linear_unit") or sr.get("units") or "",
        "factory_code": sr.get("factory_code") or sr.get("wkid"),
    }


def infer_source_label(item):
    path = str((item or {}).get("path") or (item or {}).get("name") or "")
    name = os.path.basename(path)
    low = name.lower()
    if "google" in low or "ge_" in low or low.endswith(".ecw"):
        return "Base Map / Citra Satelit"
    role = (item or {}).get("semantic_role")
    if role == "road":
        return "Data Jaringan Jalan"
    if role == "river":
        return "Data Sungai dan Aliran Air"
    if role == "admin_polygon":
        return "Data Administrasi"
    if role == "project_boundary":
        return "Data Batas PT / Area Studi"
    if role == "thematic_polygon":
        return "Data Tematik"
    return re.sub(r"[_\-]+", " ", os.path.splitext(name)[0]).strip()


def _infer_year(item):
    explicit = (item or {}).get("year")
    if explicit not in (None, ""):
        try:
            return int(explicit)
        except Exception:
            return explicit
    path = str((item or {}).get("path") or (item or {}).get("name") or "")
    years = [
        int(value)
        for value in re.findall(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)", path)
    ]
    return years[-1] if years else None


def build_provenance(items, year=None, analysis_credit="Analisis Spasial Zagent ArcMap Orchestrator"):
    year = int(year or datetime.now().year)
    seen = set()
    rows = []
    for item in items or []:
        label = infer_source_label(item)
        source_year = _infer_year(item)
        key = (label, source_year)
        if not label or key in seen:
            continue
        seen.add(key)
        rows.append({
            "label": label,
            "year": source_year,
            "source_path": (item or {}).get("path"),
            "semantic_role": (item or {}).get("semantic_role"),
        })
    rows.append({"label": analysis_credit, "year": year, "semantic_role": "analysis"})
    return rows


def build_title_lines(title, project_name="", admin=None, year=None):
    admin = admin or {}
    lines = [str(title or "PETA ADMINISTRASI").upper()]
    if project_name:
        lines.append(str(project_name).upper())
    for key in ("desa", "kecamatan", "kabupaten", "provinsi"):
        value = admin.get(key)
        if value:
            prefix = {
                "desa": "DESA",
                "kecamatan": "KECAMATAN",
                "kabupaten": "KABUPATEN",
                "provinsi": "PROVINSI",
            }[key]
            lines.append("%s %s" % (prefix, str(value).upper()))
    lines.append("TAHUN %s" % int(year or datetime.now().year))
    return lines

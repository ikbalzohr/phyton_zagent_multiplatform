from __future__ import annotations


def _field_names(row):
    fields = (row or {}).get("fields") or []
    result = []
    for field in fields:
        if isinstance(field, dict):
            result.append(str(field.get("name") or ""))
        else:
            result.append(str(field))
    return result


def select_label_field(row, candidates):
    fields = _field_names(row)
    upper = {name.upper(): name for name in fields}
    for candidate in candidates or []:
        if str(candidate).upper() in upper:
            return upper[str(candidate).upper()]
    for name in fields:
        low = name.lower()
        if "nama" in low or "name" in low or "desa" in low:
            return name
    return ""


def build_label_plan(semantic_layers, profile):
    label_profiles = (profile or {}).get("labels") or {}
    typography = (profile or {}).get("typography") or {}
    plan = []
    for row in semantic_layers or []:
        role = row.get("semantic_role")
        cfg = label_profiles.get(role) or {}
        if not cfg or not cfg.get("enabled", False):
            continue
        field = select_label_field(row, cfg.get("field_candidates") or [])
        if not field:
            continue
        plan.append({
            "role": role,
            "layer_name": row.get("layer_name") or row.get("name") or "",
            "field": field,
            "expression": "[%s]" % field,
            "font": typography.get("font", "Arial"),
            "font_size_pt": float(typography.get("label_pt") or 8.5),
            "text_rgb": list(typography.get("label_rgb") or [255, 230, 0]),
            "halo_rgb": list(typography.get("label_halo_rgb") or [0, 0, 0]),
            "halo_pt": float(typography.get("label_halo_pt") or 1.2),
            "remove_duplicates": bool(cfg.get("remove_duplicates", True)),
            "allow_overlap": bool(cfg.get("allow_overlap", False)),
            "priority": int(cfg.get("priority") or 50),
        })
    return plan


def build_recipe_operations(label_plan, data_frame=""):
    operations = []
    for row in label_plan or []:
        if not row.get("layer_name"):
            continue
        operations.append({
            "action": "set_label_class",
            "params": {
                "layer_name": row["layer_name"],
                "data_frame": data_frame,
                "class_index": 0,
                "expression": row.get("expression") or "",
                "show_class_labels": True,
                "show_labels": True,
                "expression_parser": "VBScript",
            },
        })
    return operations

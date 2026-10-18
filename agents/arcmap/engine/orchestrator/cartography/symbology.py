from __future__ import annotations

from copy import deepcopy


def style_for_role(role, profile):
    return deepcopy(((profile or {}).get("symbology") or {}).get(role) or {})


def _layer_name(row):
    return str((row or {}).get("layer_name") or (row or {}).get("name") or (row or {}).get("semantic_role") or "")


def build_symbology_plan(semantic_layers, profile):
    plan = []
    for row in semantic_layers or []:
        role = row.get("semantic_role") or "unknown"
        if role == "inset":
            continue
        style = style_for_role(role, profile)
        if not style:
            continue
        plan.append({
            "role": role,
            "layer_name": _layer_name(row),
            "path": row.get("path"),
            "style": style,
            "priority": int(style.get("priority") or 0),
        })
    plan.sort(key=lambda x: (x["priority"], x["layer_name"]))
    return plan


def build_layer_order(symbology_plan):
    return [row["layer_name"] for row in sorted(symbology_plan or [], key=lambda x: x.get("priority", 0))]


def build_recipe_operations(symbology_plan, data_frame=""):
    operations = []
    for row in symbology_plan or []:
        name = row.get("layer_name")
        style = row.get("style") or {}
        if not name:
            continue
        if "transparency" in style:
            operations.append({
                "action": "set_layer_transparency",
                "params": {
                    "layer_name": name,
                    "data_frame": data_frame,
                    "transparency": int(style["transparency"]),
                },
            })
        if "min_scale" in style or "max_scale" in style:
            operations.append({
                "action": "set_layer_scale_range",
                "params": {
                    "layer_name": name,
                    "data_frame": data_frame,
                    "min_scale": float(style.get("min_scale") or 0),
                    "max_scale": float(style.get("max_scale") or 0),
                },
            })
    return operations

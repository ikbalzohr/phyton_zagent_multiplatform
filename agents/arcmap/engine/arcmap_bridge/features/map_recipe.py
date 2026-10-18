# -*- coding: utf-8 -*-
from __future__ import print_function

import uuid

from core.registry import action, get
from core.safety import require_live_write
from features import observability
from features import cartography

_RECIPE_RUNS = {}
_RECIPE_ORDER = []
_MAX_RUNS = 20

_ALLOWED_ACTIONS = {
    "set_title": {"style_sensitive": False},
    "set_layout_text": {"style_sensitive": False},
    "set_layout_element_position": {"style_sensitive": False},
    "set_layout_element_state": {"style_sensitive": False},
    "set_map_scale": {"style_sensitive": False},
    "set_layer_visibility": {"style_sensitive": False},
    "set_definition_query": {"style_sensitive": False},
    "toggle_labels": {"style_sensitive": False},
    "set_label_expression": {"style_sensitive": False},
    "set_label_class": {"style_sensitive": False},
    "rename_layer": {"style_sensitive": False},
    "move_layer": {"style_sensitive": False},
    "set_layer_transparency": {"style_sensitive": False},
    "set_layer_scale_range": {"style_sensitive": False},
    "apply_symbology_from_layer": {"style_sensitive": True},
    "set_unique_value_field": {"style_sensitive": True},
    "set_class_breaks": {"style_sensitive": True},
    "apply_cartographic_program": {"style_sensitive": False}
}

_STYLE_LAYER_PARAM = {
    "apply_symbology_from_layer": "layer_name",
    "set_unique_value_field": "layer_name",
    "set_class_breaks": "layer_name"
}


def _schema():
    return {
        "version": 1,
        "recipe": {
            "name": "optional human-readable name",
            "operations": [
                {
                    "action": "one of allowed_actions",
                    "params": "object matching the underlying ArcMap action payload"
                }
            ]
        },
        "allowed_actions": sorted(_ALLOWED_ACTIONS.keys()),
        "limits": {"max_operations": 100},
        "atomic_behavior": (
            "A live-state snapshot is created first. If a symbology action is present, "
            "a session-owned .lyr style snapshot is captured before changing that layer. "
            "On failure, live state and captured styles are restored. "
            "Cartographic programs may create layout/data-frame elements and therefore "
            "must be protected by the Strategy D persistent MXD checkpoint. MXD is never saved by map_recipe itself."
        )
    }


def _validate(recipe):
    errors = []
    warnings = []
    if not isinstance(recipe, dict):
        return ["recipe must be an object"], warnings

    operations = recipe.get("operations", [])
    if not isinstance(operations, list):
        return ["recipe.operations must be a list"], warnings
    if not operations:
        errors.append("recipe.operations may not be empty")
    if len(operations) > 100:
        errors.append("Maximum 100 operations per recipe")

    for index, item in enumerate(operations):
        if not isinstance(item, dict):
            errors.append("operation {0} must be an object".format(index))
            continue
        action_name = item.get("action", "")
        params = item.get("params", {})
        if action_name not in _ALLOWED_ACTIONS:
            errors.append(
                "operation {0}: action is not allowed: {1}".format(index, action_name))
        if not isinstance(params, dict):
            errors.append("operation {0}: params must be an object".format(index))
        if action_name in _STYLE_LAYER_PARAM and not params.get("layer_name"):
            errors.append("operation {0}: layer_name is required for style action".format(index))

    return errors, warnings


def _style_key(params):
    return "{0}::{1}".format(params.get("data_frame", ""), params.get("layer_name", ""))


def _cleanup_style_tokens(tokens):
    rows = []
    for token in tokens:
        try:
            rows.append(cartography.delete_style_snapshot({"token": token}))
        except Exception as exc:
            rows.append({"ok": False, "token": token, "error": str(exc)})
    return rows


def _restore_style_tokens(tokens):
    rows = []
    for token in tokens:
        try:
            rows.append(cartography.restore_layer_style({"token": token}))
        except Exception as exc:
            rows.append({"ok": False, "token": token, "error": str(exc)})
    return rows


@action("get_map_recipe_schema")
def get_map_recipe_schema(command):
    return {"ok": True, "schema": _schema(), "saved": False}


@action("validate_map_recipe")
def validate_map_recipe(command):
    recipe = command.get("recipe", {})
    errors, warnings = _validate(recipe)
    return {
        "ok": len(errors) == 0,
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "operation_count": len(recipe.get("operations", [])) if isinstance(recipe, dict) else 0,
        "saved": False
    }


@action("apply_map_recipe")
def apply_map_recipe(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    recipe = command.get("recipe", {})
    errors, warnings = _validate(recipe)
    if errors:
        return {
            "ok": False,
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "saved": False
        }

    dry_run = bool(command.get("dry_run", False))
    if dry_run:
        return {
            "ok": True,
            "valid": True,
            "dry_run": True,
            "operation_count": len(recipe.get("operations", [])),
            "warnings": warnings,
            "saved": False
        }

    atomic = bool(command.get("atomic", True))
    snapshot_result = observability.snapshot_state({})
    snapshot_id = snapshot_result.get("snapshot_id")
    style_tokens = []
    style_keys = set()
    results = []

    try:
        for index, item in enumerate(recipe.get("operations", [])):
            action_name = item.get("action")
            params = dict(item.get("params", {}))
            meta = _ALLOWED_ACTIONS[action_name]

            if meta.get("style_sensitive"):
                key = _style_key(params)
                if key not in style_keys:
                    snap = cartography.capture_layer_style({
                        "layer_name": params.get("layer_name", ""),
                        "data_frame": params.get("data_frame", "")
                    })
                    if not snap.get("ok"):
                        raise RuntimeError(
                            "Could not capture style before operation {0}: {1}".format(
                                index, snap.get("error", "unknown error")))
                    style_tokens.append(snap.get("token"))
                    style_keys.add(key)

            func = get(action_name)
            if func is None:
                raise RuntimeError("Registered action disappeared: {0}".format(action_name))
            payload = dict(params)
            payload["action"] = action_name
            result = func(payload)
            results.append({
                "index": index,
                "action": action_name,
                "result": result
            })
            if not isinstance(result, dict) or not result.get("ok"):
                message = result.get("error", "operation failed") if isinstance(result, dict) else "operation failed"
                raise RuntimeError("operation {0} ({1}) failed: {2}".format(index, action_name, message))

    except Exception as exc:
        rollback_state = None
        rollback_styles = []
        cleanup = []
        if atomic and snapshot_id:
            rollback_state = observability.restore_snapshot({"snapshot_id": snapshot_id})
            rollback_styles = _restore_style_tokens(style_tokens)
            cleanup = _cleanup_style_tokens(style_tokens)
        return {
            "ok": False,
            "error": str(exc),
            "atomic": atomic,
            "snapshot_id": snapshot_id,
            "results": results,
            "rolled_back": bool(atomic),
            "rollback_state": rollback_state,
            "rollback_styles": rollback_styles,
            "style_cleanup": cleanup,
            "saved": False
        }

    run_id = str(uuid.uuid4())
    _RECIPE_RUNS[run_id] = {
        "snapshot_id": snapshot_id,
        "style_tokens": style_tokens,
        "recipe_name": recipe.get("name", "") or "",
        "rolled_back": False
    }
    _RECIPE_ORDER.append(run_id)
    while len(_RECIPE_ORDER) > _MAX_RUNS:
        old = _RECIPE_ORDER.pop(0)
        stale = _RECIPE_RUNS.pop(old, None)
        if stale:
            _cleanup_style_tokens(stale.get("style_tokens", []))

    return {
        "ok": True,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "recipe_name": recipe.get("name", "") or "",
        "operation_count": len(results),
        "results": results,
        "style_snapshot_count": len(style_tokens),
        "atomic": atomic,
        "saved": False
    }


@action("rollback_map_recipe")
def rollback_map_recipe(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    run_id = command.get("run_id", "")
    state = _RECIPE_RUNS.get(run_id)
    if state is None:
        return {
            "ok": False,
            "error": "Unknown recipe run_id: {0}".format(run_id),
            "saved": False
        }
    if state.get("rolled_back"):
        return {
            "ok": True,
            "run_id": run_id,
            "already_rolled_back": True,
            "saved": False
        }

    rollback_state = observability.restore_snapshot({
        "snapshot_id": state.get("snapshot_id", "")
    })
    rollback_styles = _restore_style_tokens(state.get("style_tokens", []))
    cleanup = _cleanup_style_tokens(state.get("style_tokens", []))
    state["rolled_back"] = True

    return {
        "ok": bool(rollback_state.get("ok")),
        "run_id": run_id,
        "rollback_state": rollback_state,
        "rollback_styles": rollback_styles,
        "style_cleanup": cleanup,
        "saved": False
    }

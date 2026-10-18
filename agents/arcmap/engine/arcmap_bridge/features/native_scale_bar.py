# -*- coding: utf-8 -*-
"""ARC-07: guard CURRENT-layout scale-bar inspection before ArcObjects COM.

ArcMap's UI thread can stall when an arbitrary GRAPHIC_ELEMENT is queried as
IMapSurroundFrame.  First enumerate ArcPy MAPSURROUND_ELEMENT candidates and
never touch COM when no such element exists.  Do not switch to page-layout
view or save the MXD in a read-only inspection.
"""
from __future__ import division
import arcpy
from core.registry import action
from core.current_map import get_mxd
from core.safety import require_live_write
from stage3 import bridge as arcobjects

UNITS = {"METERS": (9, "m", 1.0),
         "KILOMETERS": (10, "km", 1000.0)}

# A malformed COM graphics cursor must not produce an unbounded scan.
_MAX_GRAPHICS = 512
_PENDING_SCALEBAR_CHANGE = None


def _candidate_names(required_name=None):
    """ArcPy-only, read-only gate.  No typed COM until a surround is known."""
    mxd = get_mxd()
    surrounds = arcpy.mapping.ListLayoutElements(mxd, "MAPSURROUND_ELEMENT")
    names = []
    for element in surrounds:
        name = str(getattr(element, "name", "") or "").strip()
        if not name:
            # Unnamed surrounds cannot be correlated with an ArcObjects element
            # without querying arbitrary graphics on the UI thread.
            raise RuntimeError(
                "SCALE_BAR_UNNAMED_SURROUND: name the map surround before "
                "native COM inspection; no change was made")
        names.append(name)
    if required_name is not None:
        if required_name not in names:
            return set()
        return set([required_name])
    return set(names)


def _element_name(element, carto):
    """Use the generic element name before asking for MapSurround COM."""
    try:
        name = getattr(element, "Name", None)
        if name:
            return str(name).strip()
    except Exception:
        pass
    try:
        return str(
            element.QueryInterface(carto.IElementProperties).Name or ""
        ).strip()
    except Exception:
        return ""


def _scale_bars(required_name=None):
    candidates = _candidate_names(required_name)
    if not candidates:
        # Critical safe path for an MXD with no MAPSURROUND_ELEMENT objects:
        # no AppRef, no GraphicsContainer.Reset/Next, no COM QueryInterface.
        return None, []

    client, framework, arcmapui, carto = arcobjects._typed_arcobjects_modules()
    app = client.CreateObject("esriFramework.AppRef",
                              interface=framework.IApplication)
    arcobjects._verify_current_process(app)
    doc = app.Document.QueryInterface(arcmapui.IMxDocument)
    layout = doc.PageLayout.QueryInterface(carto.IPageLayout)
    graphics = layout.QueryInterface(carto.IGraphicsContainer)
    graphics.Reset()
    rows = []
    remaining = set(candidates)
    for _ in range(_MAX_GRAPHICS):
        element = graphics.Next()
        if element is None:
            break
        # Never query random graphics, text, data frames or frames as
        # IMapSurroundFrame; only elements ArcPy identified as surrounds.
        name = _element_name(element, carto)
        if name not in remaining:
            continue
        # Correlate each candidate once even if it is a north arrow or another
        # non-scale-bar surround. Do not depend on COM Next() returning None.
        remaining.discard(name)
        try:
            frame = element.QueryInterface(carto.IMapSurroundFrame)
            bar = frame.MapSurround.QueryInterface(carto.IScaleBar)
        except Exception:
            if required_name is not None or not remaining:
                break
            continue
        rows.append((name, bar))
        if required_name is not None or not remaining:
            break
    else:
        raise RuntimeError(
            "SCALE_BAR_GRAPHICS_LIMIT: candidates not correlated within "
            "safe graphics scan bound")
    return doc, rows


def _state(name, bar):
    return {"element_name": name, "units": int(bar.Units),
            "unit_label": str(bar.UnitLabel),
            "division": float(bar.Division),
            "divisions": int(bar.Divisions),
            "subdivisions": int(bar.Subdivisions)}


def _state_matches(expected, actual):
    if not actual:
        return False
    for key in ("units", "unit_label", "divisions", "subdivisions"):
        if expected[key] != actual[key]:
            return False
    try:
        wanted = float(expected["division"])
        got = float(actual["division"])
        return abs(wanted - got) <= max(1e-9, abs(wanted) * 1e-9)
    except Exception:
        return False


@action("list_native_scale_bars")
def list_native_scale_bars(command):
    global _PENDING_SCALEBAR_CHANGE
    doc, rows = _scale_bars()
    states = [_state(n, b) for n, b in rows]
    pending = _PENDING_SCALEBAR_CHANGE
    if pending:
        matches = [(n, b) for n, b in rows if n == pending["name"]]
        observed = _state(pending["name"], matches[0][1]) if len(matches) == 1 else None
        if pending["stage"] == "verify_change":
            if _state_matches(pending["requested"], observed):
                verification = {"status": "verified", "before": pending["before"],
                                "after": observed}
                _PENDING_SCALEBAR_CHANGE = None
                return {"ok": True, "scale_bars": states, "saved": False,
                        "backend": "arcpy_prefiltered_arcobjects",
                        "change_verification": verification}
            try:
                if len(matches) != 1:
                    raise RuntimeError("Scale bar target could not be uniquely reacquired")
                bar = matches[0][1]
                bar.Units = pending["before"]["units"]
                bar.UnitLabel = pending["before"]["unit_label"]
                bar.Division = pending["before"]["division"]
                arcpy.RefreshActiveView()
                pending["stage"] = "verify_rollback"
                pending["observed"] = observed
                pending["rollback_attempts"] = 1
                _PENDING_SCALEBAR_CHANGE = pending
                return {"ok": False, "error": "SCALE_BAR_POST_REFRESH_MISMATCH_ROLLBACK_REQUESTED",
                        "scale_bars": states, "saved": False,
                        "change_verification": {"status": "mismatch_rollback_requested",
                                                "before": pending["before"],
                                                "requested": pending["requested"],
                                                "observed": observed}}
            except Exception as exc:
                pending["stage"] = "rollback_unconfirmed"
                pending["rollback_error"] = str(exc)
                _PENDING_SCALEBAR_CHANGE = pending
                return {"ok": False, "error": "SCALE_BAR_ROLLBACK_FAILED",
                        "scale_bars": states, "saved": False,
                        "change_verification": {"status": "rollback_failed",
                                                "before": pending["before"],
                                                "observed": observed,
                                                "rollback_error": str(exc)}}
        if pending["stage"] == "verify_rollback":
            if _state_matches(pending["before"], observed):
                verification = {"status": "rolled_back", "before": pending["before"],
                                "after": observed, "observed_change": pending.get("observed")}
                _PENDING_SCALEBAR_CHANGE = None
                return {"ok": True, "scale_bars": states, "saved": False,
                        "backend": "arcpy_prefiltered_arcobjects",
                        "change_verification": verification}
            attempts = int(pending.get("rollback_attempts", 0))
            if len(matches) == 1 and attempts < 2:
                try:
                    bar = matches[0][1]
                    bar.Units = pending["before"]["units"]
                    bar.UnitLabel = pending["before"]["unit_label"]
                    bar.Division = pending["before"]["division"]
                    arcpy.RefreshActiveView()
                    pending["rollback_attempts"] = attempts + 1
                    _PENDING_SCALEBAR_CHANGE = pending
                    return {"ok": False, "error": "SCALE_BAR_ROLLBACK_RETRY_REQUESTED",
                            "scale_bars": states, "saved": False,
                            "change_verification": {"status": "rollback_retry_requested",
                                                    "before": pending["before"],
                                                    "observed": observed,
                                                    "attempts": attempts + 1}}
                except Exception as exc:
                    pending["rollback_error"] = str(exc)
            return {"ok": False, "error": "SCALE_BAR_ROLLBACK_UNCONFIRMED",
                    "scale_bars": states, "saved": False,
                    "change_verification": {"status": "rollback_unconfirmed",
                                            "before": pending["before"],
                                            "observed": observed,
                                            "rollback_attempts": pending.get("rollback_attempts", 0),
                                            "rollback_error": pending.get("rollback_error", "")}}
        return {"ok": False, "error": "SCALE_BAR_VERIFICATION_STATE_UNKNOWN",
                "scale_bars": states, "saved": False}
    return {"ok": True, "scale_bars": states, "saved": False,
            "backend": "arcpy_prefiltered_arcobjects"}


@action("set_native_scale_bar")
def set_native_scale_bar(command):
    global _PENDING_SCALEBAR_CHANGE
    if _PENDING_SCALEBAR_CHANGE is not None:
        return {"ok": False, "error": "SCALE_BAR_VERIFICATION_PENDING",
                "pending": _PENDING_SCALEBAR_CHANGE.get("name"), "saved": False}
    blocked = require_live_write()
    if blocked:
        return blocked
    name = str(command.get("element_name") or "").strip()
    if not name:
        raise ValueError("element_name required; no implicit first-match")
    target_unit = str(command.get("units") or "").upper()
    if target_unit not in UNITS:
        raise ValueError("units must be METERS or KILOMETERS")
    doc, rows = _scale_bars(name)
    selected = [(n, b) for n, b in rows if n == name]
    if len(selected) != 1:
        raise RuntimeError("Expected exactly one named scale bar")
    bar = selected[0][1]
    before = _state(name, bar)
    if before["units"] not in (9, 10):
        raise RuntimeError("Only existing meters/kilometers can be converted")
    next_code, next_label, next_factor = UNITS[target_unit]
    old_factor = 1.0 if before["units"] == 9 else 1000.0
    new_division = (before["division"] * old_factor / next_factor
                    if command.get("preserve_distance", True)
                    else before["division"])
    if new_division <= 0:
        raise ValueError("Scale bar division must be positive")
    requested = {"element_name": name, "units": next_code,
                 "unit_label": next_label, "division": new_division,
                 "divisions": before["divisions"],
                 "subdivisions": before["subdivisions"]}
    try:
        bar.Units = next_code
        bar.UnitLabel = next_label
        bar.Division = new_division
        arcpy.RefreshActiveView()
    except Exception:
        try:
            bar.Units = before["units"]
            bar.UnitLabel = before["unit_label"]
            bar.Division = before["division"]
            arcpy.RefreshActiveView()
        except Exception:
            pass
        raise

    # ArcMap can normalize the division after this action returns and the UI
    # processes its redraw. The next independent list call verifies or rolls
    # back; do not claim that an in-handler read is authoritative.
    _PENDING_SCALEBAR_CHANGE = {"name": name, "before": before,
                                "requested": requested,
                                "stage": "verify_change",
                                "rollback_attempts": 0}
    return {"ok": True, "before": before, "requested": requested,
            "saved": False, "verified_on_arcmap": False,
            "verification_pending": True}

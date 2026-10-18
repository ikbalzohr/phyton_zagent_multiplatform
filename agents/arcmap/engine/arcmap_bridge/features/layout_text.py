# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.current_map import get_mxd
from core.safety import require_live_write

def _text_elements(mxd):
    return arcpy.mapping.ListLayoutElements(mxd, "TEXT_ELEMENT")

@action("set_layout_text")
def set_layout_text(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("element_name", "")
    text = command.get("text", "")
    index = command.get("index", None)
    mxd = get_mxd()
    elements = _text_elements(mxd)
    target = None
    if index is not None:
        try:
            target = elements[int(index)]
        except Exception:
            return {"ok": False, "error": "Invalid layout text index"}
    elif name:
        for el in elements:
            if getattr(el, "name", "") == name:
                target = el
                break
    if target is None:
        return {"ok": False, "error": "Text element not found"}
    old = target.text
    target.text = text
    arcpy.RefreshActiveView()
    return {"ok": True, "name": getattr(target, "name", ""), "old_text": old, "text": text, "saved": False}

def _pick_unique_largest(elements):
    if not elements:
        return None

    sizes = []
    for el in elements:
        try:
            sizes.append(float(getattr(el, "fontSize", 0) or 0))
        except Exception:
            sizes.append(0.0)

    max_size = max(sizes)
    largest = []

    for i, size in enumerate(sizes):
        if abs(size - max_size) < 0.001:
            largest.append(elements[i])

    if len(largest) == 1:
        return largest[0]

    return None


def _find_title_element(mxd):
    elements = _text_elements(mxd)

    if not elements:
        return None, "No layout text elements found"

    named = []

    for el in elements:
        name = (getattr(el, "name", "") or "").upper()

        if ("MAP_TITLE" in name) or ("TITLE" in name) or ("JUDUL" in name):
            named.append(el)

    # Prioritas utama: element name
    if len(named) == 1:
        return named[0], None

    if len(named) > 1:
        target = _pick_unique_largest(named)

        if target is not None:
            return target, None

        return None, "Title element is ambiguous: multiple named title elements found"

    # Fallback aman: font terbesar yang unik
    target = _pick_unique_largest(elements)

    if target is not None:
        return target, None

    return None, (
        "Title element is ambiguous. "
        "Give the title element a unique name such as MAP_TITLE."
    )


@action("set_title")
def set_title(command):
    blocked = require_live_write()

    if blocked:
        return blocked

    value = (command.get("value") or command.get("title") or "").strip()

    if not value:
        return {"ok": False, "error": "Title cannot be empty"}

    mxd = get_mxd()

    target, error = _find_title_element(mxd)

    if target is None:
        return {
            "ok": False,
            "error": error or "Title element not found"
        }

    old = target.text
    target.text = value

    arcpy.RefreshActiveView()
    arcpy.RefreshTOC()

    return {
        "ok": True,
        "old_text": old,
        "value": value,
        "element_name": getattr(target, "name", ""),
        "font_size": getattr(target, "fontSize", None),
        "saved": False
    }

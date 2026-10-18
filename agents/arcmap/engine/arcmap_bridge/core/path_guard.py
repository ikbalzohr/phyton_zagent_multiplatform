# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import ntpath
from .config import PATHS


def _normalize(path):
    if not path:
        return ""
    path = os.path.expandvars(os.path.expanduser(path))
    return ntpath.normcase(ntpath.abspath(path))


def is_within(path, root):
    child = _normalize(path)
    base = _normalize(root)
    if not child or not base:
        return False
    return child == base or child.startswith(base.rstrip("\\/") + "\\")


def guard_manual_write(path, field_name="path"):
    """Block every persistent write targeting the immutable Manual baseline."""
    if not path:
        return {
            "ok": False,
            "blocked": True,
            "error": "{0} is required".format(field_name)
        }
    manual = PATHS.get("manual_baseline", "")
    if manual and is_within(path, manual):
        return {
            "ok": False,
            "blocked": True,
            "error": "Write blocked: Manual baseline is read-only.",
            "path": path,
            "manual_baseline": manual
        }
    return None

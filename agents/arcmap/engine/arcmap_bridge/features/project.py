# -*- coding: utf-8 -*-
from core.registry import action
from core.current_map import get_mxd
from core.safety import require_save
from core.path_guard import guard_manual_write

@action("save_current_map")
def save_current_map(command):
    blocked = require_save()
    if blocked:
        return blocked
    mxd = get_mxd()
    path = getattr(mxd, "filePath", "")
    blocked = guard_manual_write(path, "mxd.filePath")
    if blocked:
        return blocked
    mxd.save()
    return {"ok": True, "mxd": getattr(mxd, "filePath", ""), "saved": True}

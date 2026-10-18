# -*- coding: utf-8 -*-
"""ARC-08 user-announced manual edit interval."""
from core.registry import action
from core import concurrent_edit_guard as guard


@action("edit_guard_acquire")
def edit_guard_acquire(command):
    return guard.acquire(command)


@action("edit_guard_release")
def edit_guard_release(command):
    return guard.release(command)


@action("edit_guard_status")
def edit_guard_status(command):
    return guard.status(command)

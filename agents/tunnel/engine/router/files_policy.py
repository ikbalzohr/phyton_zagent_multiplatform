"""Canonical Files operation authority; names/configuration never confer authority.

Only exact entries are publishable. Direct owner administration has a separate
exact capability catalog; legacy requests, cross-profile transfer and updates stay
local-management-only, including their informational controls.
Command tools require BOTH execute and write; files_execute is a mutating wrapper
whose inner operation must additionally be authorized by the Files backend.
"""
from __future__ import annotations
from collections.abc import Collection
from .access import AuthorizationError
from .profile_admin import PROFILE_ADMIN_SCOPES


FILES_TOOL_SCOPES = {
    'files_allowlist_list': 'files:read',
    'files_allowlist_add': 'files:write',
    'files_allowlist_remove': 'files:write',
    'files_allowlist_replace': 'files:write',
    'files_ping': 'files:read',
    'files_runtime_info': 'files:read',
    'files_get_root': 'files:read',
    'files_exists': 'files:read',
    'files_list': 'files:read',
    'files_tree': 'files:read',
    'files_stat': 'files:read',
    'files_read': 'files:read',
    'files_read_bytes_b64': 'files:read',
    'files_search': 'files:read',
    'files_hash': 'files:read',
    'files_diff': 'files:read',
    'files_backup_list': 'files:read',
    'files_syntax_check': 'files:read',
    'files_project_instructions': 'files:read',
    'files_project_open': 'files:write',
    'files_workspace_status': 'files:read',
    'files_workspace_list': 'files:read',
    'files_operation_status': 'files:read',
    'files_operation_list': 'files:read',
    'files_capabilities': 'files:read',
    'files_write': 'files:write',
    'files_append': 'files:write',
    'files_patch': 'files:write',
    'files_mkdir': 'files:write',
    'files_copy': 'files:write',
    'files_move': 'files:write',
    'files_delete': 'files:write',
    'files_backup': 'files:write',
    'files_restore': 'files:write',
    'files_zip': 'files:write',
    'files_unzip': 'files:write',
    'files_workspace_open': 'files:write',
    'files_workspace_switch': 'files:write',
    'files_execute': 'files:write',
    'files_operation_cancel': 'files:write',
    'files_command_capabilities': 'files:execute',
    'files_command_cancel': 'files:execute',
    'files_exec_command': 'files:execute',
    'files_powershell_run': 'files:execute',
    'files_node': 'files:execute',
    'files_npm': 'files:execute',
    'files_npx': 'files:execute',
    'files_git': 'files:execute',
    'files_build': 'files:execute',
    'files_test': 'files:execute',
    'files_process_list': 'files:execute',
    'files_process_start': 'files:execute',
    'files_process_stop': 'files:execute',
}

MANAGEMENT_ONLY_TOOLS = {
    'files_profile_list', 'files_profile_get', 'files_profile_default_get',
    'files_profile_reload', 'files_profile_switch', 'files_profile_request_add',
    'files_profile_request_update', 'files_profile_request_delete',
    'files_profile_pending_list', 'files_profile_request_status',
    'files_cross_profile_capabilities', 'files_copy_between_profiles',
    'files_copy_batch_between_profiles',
    'files_update_capabilities', 'files_update_status', 'files_update_prepare',
    'files_update_stage_text', 'files_update_stage_b64', 'files_update_mark_delete',
    'files_update_validate', 'files_update_apply', 'files_update_history',
    'files_update_rollback', 'files_update_abort',
}


def scope_for_files_tool(tool: str) -> str:
    """Resolve an exact canonical public name; never infer from a name prefix."""
    if isinstance(tool, str) and tool in PROFILE_ADMIN_SCOPES:
        return PROFILE_ADMIN_SCOPES[tool]
    if not isinstance(tool, str) or tool not in FILES_TOOL_SCOPES:
        raise AuthorizationError('FILES_TOOL_NOT_AUTHORIZED', 403)
    return FILES_TOOL_SCOPES[tool]


def validate_files_tool_scope(tool: str, scope: str, scopes: Collection[str]) -> str:
    """Reject policy downgrade and derive effective access from trusted grants."""
    required = scope_for_files_tool(tool)
    if scope != required:
        raise AuthorizationError('FILES_TOOL_SCOPE_MISMATCH', 403, required)
    if not isinstance(scopes, (set, frozenset, list, tuple)) or not all(isinstance(s, str) for s in scopes):
        raise AuthorizationError('insufficient_scope', 403, required)
    if required not in scopes:
        raise AuthorizationError('insufficient_scope', 403, required)
    if required == 'files:execute' and 'files:write' not in scopes:
        raise AuthorizationError('insufficient_scope', 403, 'files:write')
    return 'read' if required == 'files:read' else 'write'

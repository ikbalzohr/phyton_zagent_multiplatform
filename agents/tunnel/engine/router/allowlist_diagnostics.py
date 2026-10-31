"""Fixed-name visibility diagnostics; never returns grants, paths or exceptions."""
import time

from .access import AuthorizationError
from .files_policy import FILES_TOOL_SCOPES

TOOLS = ('files_allowlist_list', 'files_allowlist_add', 'files_allowlist_remove', 'files_allowlist_replace')


def allowlist_diagnostics(auth, registry, policy_lookup):
    """Describe independent discovery/policy/scope/grant gates, not live health.

    This projection grants no authority, refreshes no discovery and does not
    inspect private Files state. Multiple blockers can coexist.
    """
    rows = []
    for name in TOOLS:
        blockers = []
        if name not in registry.tool_index:
            blockers.append('UPSTREAM_NOT_DISCOVERED')
        try:
            policy = policy_lookup(name)
        except AuthorizationError:
            blockers.append('POLICY_REJECTED')
        else:
            if not isinstance(policy, dict) or policy.get('scope') != FILES_TOOL_SCOPES[name]:
                blockers.append('POLICY_REJECTED')
            elif policy.get('enabled', True) is not True:
                blockers.append('POLICY_DISABLED')
        if FILES_TOOL_SCOPES[name] not in auth.scopes:
            blockers.append('SCOPE_MISSING')
        if name not in auth.tools:
            blockers.append('TOOL_NOT_GRANTED')
        if auth.expires_at <= time.time():
            blockers.append('AUTH_EXPIRED')
        rows.append({'name': name, 'blockers': blockers})
    return rows

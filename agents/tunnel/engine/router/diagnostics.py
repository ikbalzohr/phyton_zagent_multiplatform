"""Public remediation is code-only, never inferred from private runtime state.

Identical hints apply to every caller receiving a given stable error code. They
must not disclose grant membership, configured principals, paths or backend text.
"""

_PUBLIC_HINTS = {
    'TOOL_NOT_AUTHORIZED': 'Use tools/list for currently available tools. Ask the owner to verify deployed tool discovery, enabled tool policy, scope/tool grants and any required capability. This denial does not identify which check failed.',
    'FILES_RESOURCE_NOT_AUTHORIZED': 'Ask the owner to verify the Files resource binding, device/installation placement and approved enabled profile membership/default. A resource denial does not establish that Files is stopped.',
    'PROFILE_MANAGEMENT_NOT_AUTHORIZED': 'Profile management requires explicit owner capability, matching placement and scope/tool authorization. Ordinary Files write access is not sufficient; ask the owner to verify deployment configuration.',
    'PROFILE_CATALOG_NOT_CONFIGURED': 'Ask the owner to verify that exactly one supported Files backend is enabled in the Router configuration. Do not assume a profile operation succeeded.',
    'PROFILE_CATALOG_UNAVAILABLE': 'The private profile catalog could not be obtained. Ask the owner to inspect authenticated local diagnostics for private-channel, transport or response failures. Do not assume Files is stopped or retry a mutation without checking its receipt.',
}


def public_error(code: str) -> dict[str, str]:
    error = {'code': code}
    hint = _PUBLIC_HINTS.get(code)
    if hint is not None:
        error['hint'] = hint
    return error

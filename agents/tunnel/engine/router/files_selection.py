"""Per-request Files intent; only the grant/context supplies authority."""
from copy import deepcopy
import re

from .access import AuthorizationError
from .files_policy import FILES_TOOL_SCOPES
from .profile_admin import PROFILE_ADMIN_SCOPES, tool_schema

# These original domain APIs accept profile_id; other upstream APIs do not.
DOMAIN_PROFILE_ID_TOOLS = frozenset({'files_workspace_status', 'files_workspace_switch',
    'files_allowlist_list', 'files_allowlist_add', 'files_allowlist_remove', 'files_allowlist_replace'})
COMMAND_TOOLS = frozenset({'files_command_capabilities', 'files_command_cancel',
    'files_exec_command', 'files_powershell_run', 'files_node', 'files_npm', 'files_npx',
    'files_git', 'files_build', 'files_test', 'files_process_list', 'files_process_start',
    'files_process_stop'})
PROFILE_SCHEMA = {'type': 'string', 'minLength': 1, 'maxLength': 256,
                  'pattern': r'^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,255}$'}


def profile_id(value):
    if not isinstance(value, str) or re.fullmatch(PROFILE_SCHEMA['pattern'], value) is None:
        raise AuthorizationError('FILES_RESOURCE_NOT_AUTHORIZED', 403)
    return value


def files_tool_schema(tool):
    """One schema augmentation shared by discovery and invocation validation."""
    if tool['name'] in PROFILE_ADMIN_SCOPES:
        result = deepcopy(tool)
        result['inputSchema'] = tool_schema(tool['name'])
        return result
    if tool['name'] not in FILES_TOOL_SCOPES:
        return tool
    result = deepcopy(tool)
    schema = result['inputSchema']
    schema.setdefault('properties', {}).setdefault('profile_id', dict(PROFILE_SCHEMA))
    if tool['name'] in {'files_allowlist_list', 'files_allowlist_add', 'files_allowlist_remove', 'files_allowlist_replace'}:
        schema['additionalProperties'] = False
        if 'expected_revision' in schema['properties']:
            schema['properties']['expected_revision'] = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
        if 'profile_id' not in schema.get('required', []):
            schema.setdefault('required', []).append('profile_id')
    return result


def selected_profile(tool, arguments):
    """All explicitly supported aliases must agree; never infer from a path."""
    if tool not in FILES_TOOL_SCOPES:
        return None
    values = []
    if tool == 'files_execute':
        # The outer selector is Router intent; inner selectors/authority are
        # never forwarded as a second selection or journaled for execution.
        from .execution_context import reject_authority
        inner = arguments.get('arguments')
        reject_authority(inner)
        if {'profile_id', 'profile', 'active_profile', 'profiles',
                'source_profile', 'destination_profile'}.intersection(inner):
            raise ValueError('CLIENT_AUTHORITY_NOT_ALLOWED')
    if 'profile_id' in arguments:
        values.append(profile_id(arguments['profile_id']))
    if tool in COMMAND_TOOLS and 'profile' in arguments:
        values.append(profile_id(arguments['profile']))
    if tool == 'files_workspace_open':
        if 'active_profile' in arguments and arguments['active_profile'] is not None:
            values.append(profile_id(arguments['active_profile']))
        if 'profiles' in arguments:
            profiles = arguments['profiles']
            if not isinstance(profiles, list) or len(profiles) != 1:
                raise AuthorizationError('FILES_RESOURCE_NOT_AUTHORIZED', 403)
            values.append(profile_id(profiles[0]))
    if len(set(values)) > 1:
        raise AuthorizationError('PROFILE_SELECTOR_CONFLICT', 403)
    return values[0] if values else None


def forward_files_arguments(tool, arguments, context):
    """Strip only the new Router selector at the authenticated Files seam."""
    selected = selected_profile(tool, arguments)
    resources = context.get('effective_resources')
    if (not isinstance(resources, list) or len(resources) != 1
            or resources[0].get('kind') != 'files'
            or (selected is not None and selected != resources[0].get('profile_id'))):
        raise AuthorizationError('FILES_RESOURCE_NOT_AUTHORIZED', 403)
    result = dict(arguments)
    if tool not in DOMAIN_PROFILE_ID_TOOLS:
        result.pop('profile_id', None)
    return result

from __future__ import annotations
import inspect
import json
from pathlib import Path
from typing import get_type_hints
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ToolAnnotations
from app.mcp import legacy
from app.core.execution import Engine, READ
from app.core.diagnostic_events import CURRENT_ID, new_request_id, record
from app.core.execution_context import CURRENT, current, verify, request_meta, validate_profile
from app.profiles.administration import (PROFILE_ADMIN_TOOLS, CATALOG_TOOL,
                                        admin_call, catalog_snapshot, read_lease)


class TrustedFilesMCP(FastMCP):
    async def call_tool(self, name, arguments):
        from mcp.types import CallToolResult, TextContent
        correlation = new_request_id()
        token = CURRENT_ID.set(correlation)
        stage = 'files.authentication'
        try:
            # Metadata verification precedes all execution; diagnostics confer
            # no authority and never inspect supplied arguments or context.
            metadata = request_meta(self.get_context())
            stage = 'files.tool_dispatch'
            return await self._call_authenticated_tool(name, arguments, metadata)
        except Exception:
            record(stage, 'FILES_OPERATION_FAILED', correlation)
            error = {'code': 'FILES_OPERATION_FAILED', 'data': {'requestId': correlation}}
            return CallToolResult(isError=True,
                content=[TextContent(type='text', text='Files operation failed. Inspect owner diagnostics using the requestId.')],
                structuredContent={'error': error})
        finally:
            CURRENT_ID.reset(token)

    async def _call_authenticated_tool(self, name, arguments, metadata):
        if name in PROFILE_ADMIN_TOOLS or name == CATALOG_TOOL:
            from mcp.types import TextContent
            value = (await admin_call(name, arguments or {}, metadata) if name in PROFILE_ADMIN_TOOLS
                     else await catalog_snapshot(arguments or {}, metadata))
            return [TextContent(type='text', text=json.dumps(value, ensure_ascii=False, allow_nan=False))]
        controls = {'files_command_cancel','files_process_stop','files_process_list','files_operation_cancel','files_operation_status','files_operation_list'}
        async with read_lease(control=name in controls):
            return await self._call_data_tool(name, arguments, metadata)

    async def _call_data_tool(self, name, arguments, metadata):
        authority = verify(metadata, name, arguments or {})
        if name.startswith('files_update_'):
            raise PermissionError('MANAGEMENT_PLANE_ONLY')
        validate_profile(authority, engine.approved(authority['profile_id']))
        # Even a first workspace_switch must seed its resource-scoped session
        # from verified selection, never an unrelated local default root.
        engine.ensure_session(authority['session_id'], authority['profile_id'])
        # Import only for command calls: native startup does not require this
        # optional owner-managed facility. It takes explicit verified authority.
        from app.core.execution_context import COMMAND_TOOLS
        if name in COMMAND_TOOLS:
            from app.mcp.managed_commands import COMMAND_TOOL_NAMES, authorize_command_call
            if name not in COMMAND_TOOL_NAMES:
                raise PermissionError('UNKNOWN_FILES_COMMAND')
            authorize_command_call(name, arguments or {}, authority)
        token = CURRENT.set(authority)
        try:
            return await super().call_tool(name, arguments)
        finally:
            CURRENT.reset(token)
from app.core.batch import copy_batch_between_profiles
from app.core import updater
from app.profiles import manager

from app.paths import CONFIG_DIR
SETTINGS = json.loads((CONFIG_DIR / 'settings.json').read_text(encoding='utf-8'))
HOST, PORT = SETTINGS['host'], int(SETTINGS['port'])
if HOST not in ('localhost', '127.0.0.1', '127.0.0.3', '::1'):
    raise ValueError('Files backend must bind a private loopback address')


mcp = TrustedFilesMCP('Zagent Files 1.0.0', host=HOST, port=PORT, stateless_http=True,
              json_response=True, streamable_http_path='/mcp')
operations = {name[6:]: fn for name,fn in vars(legacy).items()
              if name.startswith('files_') and callable(fn)}
operations['copy_batch_between_profiles'] = copy_batch_between_profiles
engine = Engine(operations)


def register_profile_administration():
    definitions = {
        'list': [],
        'get': [('target_profile_id', str, inspect.Parameter.empty)],
        'create': [('target_profile_id', str, inspect.Parameter.empty), ('root', str, inspect.Parameter.empty),
                   ('expected_revision', str, inspect.Parameter.empty), ('idempotency_key', str, inspect.Parameter.empty),
                   ('mode', str, 'read-only'), ('enabled', bool, True), ('description', str, '')],
        'update': [('target_profile_id', str, inspect.Parameter.empty), ('changes', dict, inspect.Parameter.empty),
                   ('expected_revision', str, inspect.Parameter.empty), ('idempotency_key', str, inspect.Parameter.empty)],
        'delete': [('target_profile_id', str, inspect.Parameter.empty), ('expected_revision', str, inspect.Parameter.empty),
                   ('idempotency_key', str, inspect.Parameter.empty), ('replacement_default_id', str | None, None)],
        'set_default': [('target_profile_id', str, inspect.Parameter.empty), ('expected_revision', str, inspect.Parameter.empty),
                        ('idempotency_key', str, inspect.Parameter.empty)],
    }
    def make(tool, fields):
        async def invoke(**kwargs):
            metadata = request_meta(mcp.get_context())
            if tool == CATALOG_TOOL:
                return await catalog_snapshot(kwargs, metadata)
            return await admin_call(tool, kwargs, metadata)
        invoke.__name__ = tool
        invoke.__signature__ = inspect.Signature([inspect.Parameter(k, inspect.Parameter.KEYWORD_ONLY, annotation=t, default=d) for k,t,d in fields], return_annotation=dict)
        invoke.__annotations__ = {k:t for k,t,d in fields} | {'return':dict}
        return invoke
    for tool, action in PROFILE_ADMIN_TOOLS.items():
        mcp.add_tool(make(tool, definitions[action]), description='Authenticated direct owner profile administration; no pending approval.',
                     annotations=ToolAnnotations(readOnlyHint=action in ('list','get'), destructiveHint=action == 'delete', openWorldHint=False))
    mcp.add_tool(make(CATALOG_TOOL, []), description='Private authenticated catalog snapshot; never publish as an OAuth tool.',
                 annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))


register_profile_administration()


def metadata_from(ctx, metadata):
    # Explicit metadata is untrusted; only the verified invocation is authority.
    return current()


def scoped_owner(supplied=None):
    authority = current()
    if supplied and supplied != authority['workspace_id']:
        raise PermissionError('WORKSPACE_SCOPE_MISMATCH')
    return authority['session_id']


def allowed_profiles():
    allowed = {r.get('profile_id') for r in current()['effective_resources'] if r['kind'] == 'files'}
    if not allowed or any(not isinstance(p, str) or not p for p in allowed):
        raise PermissionError('FILES_PROFILE_SCOPE_REQUIRED')
    return allowed


def scoped_profile(profile):
    if profile and profile not in allowed_profiles():
        raise PermissionError('PROFILE_NOT_IN_RESOURCE_SCOPE')
    if profile:
        validate_profile(current(), engine.approved(profile))
    return profile


def workspace_view(value):
    allowed = allowed_profiles()
    if value['active_profile'] not in allowed:
        raise PermissionError('ACTIVE_PROFILE_NOT_IN_RESOURCE_SCOPE')
    scoped_profile(value['active_profile'])
    return {**value, 'workspace_id': current()['workspace_id'],
            'profiles': [p for p in value['profiles'] if p in allowed]}


def scoped_operation(operation_id):
    row = engine.journal.get(operation_id, scoped_owner())
    metadata = row.get('metadata') or {}
    scoped_profile(metadata.get('profile_id'))
    required = {r.get('resource_id') for r in metadata.get('effective_resources', [])}
    effective = {r['resource_id'] for r in current()['effective_resources']}
    if not required or not required.issubset(effective):
        raise PermissionError('OPERATION_RESOURCE_SCOPE_MISMATCH')
    return row


def register(op, fn):
    hints = get_type_hints(fn)
    params = [p.replace(annotation=hints.get(p.name, p.annotation))
              for p in inspect.signature(fn).parameters.values()]
    params += [inspect.Parameter('metadata', inspect.Parameter.KEYWORD_ONLY, default=None, annotation=dict | None),
               inspect.Parameter('ctx', inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Context)]
    async def wrapped(**kwargs):
        meta = metadata_from(kwargs.pop('ctx', None), kwargs.pop('metadata', None))
        return await engine.execute(op, kwargs, meta)
    wrapped.__name__ = 'files_' + op
    wrapped.__signature__ = inspect.Signature(params, return_annotation=dict)
    wrapped.__annotations__ = {p.name:p.annotation for p in params}
    wrapped.__annotations__['return'] = dict
    cap = engine.capability(op)
    mcp.add_tool(wrapped, description='Workspace-scoped '+op+'. Authenticated resource scope and approved roots are required.',
                 annotations=ToolAnnotations(readOnlyHint=op in READ, destructiveHint=op not in READ,
                                             idempotentHint=op in READ, openWorldHint=False),
                 meta={'zagent.capability':cap})


for operation, function in operations.items():
    register(operation, function)


@mcp.tool()
def files_workspace_open(workspace_id: str, profiles: list[str], active_profile: str | None = None) -> dict:
    """Mount already-approved profiles in a durable session. Does not grant new permissions."""
    return workspace_view(engine.session(scoped_owner(workspace_id), [scoped_profile(p) for p in profiles], scoped_profile(active_profile)))


@mcp.tool()
def files_workspace_status(workspace_id: str, profile_id: str | None = None) -> dict:
    """Return or auto-recover a durable session. profile_id seeds only a missing session."""
    return workspace_view(engine.ensure_session(scoped_owner(workspace_id), scoped_profile(profile_id or current().get('profile_id') or sorted(allowed_profiles())[0])))


@mcp.tool()
def files_workspace_list() -> list[dict]:
    """List durable Files sessions and their independent active profiles."""
    return [workspace_view(engine.ensure_session(scoped_owner(), scoped_profile(current().get('profile_id') or sorted(allowed_profiles())[0])))]


@mcp.tool()
def files_workspace_switch(workspace_id: str, profile_id: str) -> dict:
    """Explicitly switch one Files session without changing the global default."""
    result = engine.switch_session(scoped_owner(workspace_id), scoped_profile(profile_id))
    return {
        **workspace_view(result),
        'scope': 'principal_workspace_resource_profile_placement',
        'global_default_profile': manager.default_profile_name(),
    }


@mcp.tool()
async def files_execute(operation: str, arguments: dict, metadata: dict | None = None, ctx: Context = None) -> dict:
    """Authenticated Router adapter; arguments.metadata never grants authority."""
    return await engine.execute(operation, arguments, metadata_from(ctx, metadata))


@mcp.tool()
def files_operation_status(operation_id: str, workspace_id: str) -> dict:
    """Read local checkpoint/result after disconnect. Session ownership is enforced."""
    scoped_owner(workspace_id)
    return scoped_operation(operation_id)


@mcp.tool()
def files_operation_cancel(workspace_id: str, operation_id: str | None = None,
                           task_id: str | None = None) -> dict:
    """Cancel a checkpointed batch by local operation_id or Tunnel task_id."""
    owner = scoped_owner(workspace_id)
    row = scoped_operation(operation_id or engine.journal.find_by_task(task_id, owner)['operation_id'])
    return engine.cancel(operation_id=row['operation_id'], session_id=owner, task_id=task_id)


@mcp.tool()
def files_operation_list(workspace_id: str, limit: int = 50) -> list[dict]:
    """Locate running operations and checkpoints by owning session after disconnect."""
    with engine.journal.lock:
        ids = engine.journal.db.execute('SELECT operation_id FROM operations WHERE session_id=? ORDER BY updated DESC LIMIT ?',
                                       (scoped_owner(workspace_id), max(1,min(limit,100)))).fetchall()
    visible = []
    for row in ids:
        try:
            visible.append(scoped_operation(row[0]))
        except PermissionError:
            pass
    return visible


@mcp.tool()
def files_capabilities() -> dict:
    return {'service':'Zagent Files', 'version':'1.0.0', 'session_scoped_profiles':True,
            'global_default_is_new_session_seed_only':True,
            'explicit_session_switch':True,
            'automatic_session_recovery':True,
            'auto_mount_policy':'approved profiles only; no permission escalation; existing session active profile is never changed by transport profile hints',
            'native_fast_path':['ping','exists','read','write','append','patch','list','tree','stat','search','hash','diff'],
            'sqlite_wal':True, 'worker_threads':8, 'background_limit':6,
            'global_orchestrator':'Zagent Tunnel 1.0.0',
            'metadata_transport':['authenticated private-channel params._meta.zagent.execution_context'],
            'native_filesystem_boundary':'best-effort reparse rejection and revalidation; not an OS sandbox; TOCTOU remains against hostile local processes',
            'cross_profile_copy_enabled':False,
            'tunnel_session_orchestrator':'authenticated principal/workspace/resource context; legacy journal column is internal owner namespace',
            'locking':'canonical path + ancestor/descendant reader/writer, atomic multi-resource acquisition',
            'disconnect':'generic operations continue safely; cancellable batch receives cooperative cancel',
            'restart':'completed replay; checkpointed batch resume; ambiguous generic operations orphaned',
            'self_update':False,
            'self_update_scope':'staging/validation local; apply/rollback owned by Zagent Core',
            'update_owner':'Zagent Core',
            'update_apply_mode':'core_broker',
            'operations':{op:engine.capability(op) for op in operations}}



@mcp.tool()
def files_update_capabilities():
    return updater.capabilities()


@mcp.tool()
def files_update_status():
    return updater.status()


@mcp.tool()
def files_update_prepare(update_id: str, description: str = "", target_version: str = ""):
    return updater.prepare(update_id, description, target_version)


@mcp.tool()
def files_update_stage_text(update_id: str, path: str, content: str,
                            encoding: str = "utf-8", expected_sha256: str = ""):
    return updater.stage_text(update_id, path, content, encoding, expected_sha256)


@mcp.tool()
def files_update_stage_b64(update_id: str, path: str, content_b64: str,
                           expected_sha256: str = ""):
    return updater.stage_b64(update_id, path, content_b64, expected_sha256)


@mcp.tool()
def files_update_mark_delete(update_id: str, path: str):
    return updater.mark_delete(update_id, path)


@mcp.tool()
def files_update_validate(update_id: str):
    return updater.validate(update_id)


@mcp.tool()
def files_update_apply(update_id: str):
    return updater.apply(update_id)


@mcp.tool()
def files_update_history(limit: int = 20):
    return updater.history(limit)


@mcp.tool()
def files_update_rollback(update_id: str):
    return updater.rollback(update_id)


@mcp.tool()
def files_update_abort(update_id: str):
    return updater.abort(update_id)

# Co-host on the existing Core-owned Files listener; not a discovered MCP tool.
from app.allowlist.host import install_core_routes
allowlist_host = install_core_routes(mcp)


if __name__ == '__main__':
    mcp.run(transport='streamable-http')

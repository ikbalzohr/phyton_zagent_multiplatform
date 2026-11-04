"""Actual Registry serialization -> authenticated Files administration -> data.
NOT_RUN on Linux. No OAuth/network acceptance claim: transport captured in-process.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import pytest

if os.name != 'nt' or not os.environ.get('ZAGENT_DIRECT_PROFILE_FIXTURE_ROOT'):
    pytest.skip('Windows disposable runner required before product imports', allow_module_level=True)

from mcp.types import CallToolResult
from app.core.execution_context import request_meta, verify, validate_profile
from app.mcp import server as files
from app.profiles import administration as domain, manager
from router import server as perimeter
from router.access import AuthContext, AuthorizationError, ResourceAuthorizer
from router.execution_context import new_context, reject_authority
from router.files_policy import FILES_TOOL_SCOPES
from router.files_selection import files_tool_schema
from router.identity import Placement
from router.profile_admin import (PROFILE_ADMIN_SCOPES, catalog_context, new_admin_context,
    require_profile_management, validate_catalog, revalidate_admin)
from router.registry import MCPRegistry, UpstreamState


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # Each fixture writes only disposable fixture-owned paths, no legacy writer.
    root = tmp_path/'legacy'; root.mkdir(); (root/'marker.txt').write_text('original')
    manager.PROFILES_FILE.write_text(json.dumps({'schema_version':'2.0','active_profile':'legacy',
        'profiles':[{'name':'legacy','root':str(root),'mode':'read-write','enabled':True,'authorized_by_user':True}]}), encoding='utf-8')
    place = Placement('fixture-device', 'fixture-installation')
    scopes = ['files:read','files:write']
    tools = list(PROFILE_ADMIN_SCOPES) + ['files_read','files_write']
    auth = AuthContext('fixture-principal','fixture-workspace',frozenset(scopes),frozenset(tools),'revision',time.time()+600)
    grant = {'expires_at': time.time()+600,'revoked':False,'scopes':scopes,'tools':tools,
        'profile_management':{'version':1,'enabled':True,'workspace_id':auth.workspace_id,
            'device_id':place.device_id,'installation_id':place.installation_id,
            'actions':['list','get','create','update','delete','set_default']},
        'files_resource':{'kind':'files','resource_id':'fixture-resource','profile_id':'legacy',
            'allowed_profile_ids':['legacy'],'device_id':place.device_id,'installation_id':place.installation_id,'revoked':False}}
    authorizer = ResourceAuthorizer({'workspace_id':auth.workspace_id,'policy_revision':auth.policy_revision,'grants':{auth.principal_id:grant}})
    registry = object.__new__(MCPRegistry)
    registry.states = {'zagent_files':UpstreamState(service={'id':'zagent_files','namespace':'files','name':'Files','enabled':True},
        tools=[{'name':n,'inputSchema':{}} for n in tools]+[{'name':'files_profile_catalog_snapshot','inputSchema':{}}])}
    registry.clients = {}; registry.rebuild_index()
    async def init(state):
        pass
    async def post(state, payload, **kwargs):
        params = payload['params']; tool = params['name']; args = params['arguments']
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(
            headers={'x-zagent-internal-token':os.environ['ZAGENT_INTERNAL_TOKEN']}), meta=params['_meta']))
        if tool == 'files_profile_catalog_snapshot':
            assert set(params['_meta']) == {'zagent.profile_catalog_context'}
        elif tool in PROFILE_ADMIN_SCOPES:
            assert set(params['_meta']) == {'zagent.profile_admin_context'}
        # Exercise the real registration/frontdoor, not a copied verifier or
        # manually seeded engine session. Simulate only the HTTP request context.
        monkeypatch.setattr(files.mcp, 'get_context', lambda: ctx)
        result = await files.mcp.call_tool(tool, args)
        if isinstance(result, CallToolResult):
            if result.isError:
                raise PermissionError('Files frontdoor denied fixture operation')
            return {'result': result.model_dump(exclude_none=True)}
        if isinstance(result, tuple):
            content, structured = result
            return {'result':{'content':[item.model_dump() for item in content], 'structuredContent':structured}}
        return {'result':{'content':[item.model_dump() for item in result]}}
    registry.ensure_initialized = init; registry._post = post
    monkeypatch.setattr(perimeter, 'placement', place)
    monkeypatch.setattr(perimeter, 'authorizer', lambda: authorizer)
    monkeypatch.setattr(perimeter, 'registry', registry)
    monkeypatch.setattr(perimeter, '_policy', lambda tool: {'scope':PROFILE_ADMIN_SCOPES.get(tool, FILES_TOOL_SCOPES.get(tool)), 'enabled':True})
    return SimpleNamespace(root=root, place=place, auth=auth, grant=grant, authorizer=authorizer, registry=registry, tmp=tmp_path)


async def invoke(a, tool, args, context=None):
    context = context or new_admin_context(a.auth,a.place,a.authorizer,tool,args)
    ctx = SimpleNamespace(execution_context=context,session_id=a.auth.owner,request_id=context['request_id'],
        trace_id=context['trace_id'],task_id=context['task_id'],profile_id='',idempotency_key='',resource_key='installation:'+a.place.installation_id,
        access_mode='write',priority=2)
    result = await a.registry.invoke('zagent_files',tool,args,ctx)
    if isinstance(result.get('structuredContent'), dict):
        return result['structuredContent']
    return json.loads(result['content'][0]['text'])


def test_real_create_catalog_data_delete_receipt(setup, monkeypatch):
    async def run():
        a = setup
        assert 'files_profile_catalog_snapshot' not in a.registry.tool_index
        assert all(t['name'] != 'files_profile_catalog_snapshot' for t in a.registry.list_public_tools())
        snapshot = await a.registry.profile_catalog_snapshot(catalog_context(a.auth,a.place))
        target = a.tmp/'new'; target.mkdir()
        create = {'target_profile_id':'_new','root':str(target),'mode':'read-write','expected_revision':snapshot['revision'],'idempotency_key':'create'}
        result = await invoke(a,'files_profile_admin_create',create)
        assert result['status'] == 'committed'
        assert (await invoke(a,'files_profile_admin_create',create))['revision'] == result['revision']
        snapshot = await a.registry.profile_catalog_snapshot(catalog_context(a.auth,a.place))
        catalog = validate_catalog(snapshot,a.auth,a.place,a.authorizer)
        assert '_new' in catalog['allowed_profile_ids'] and a.grant['files_resource']['allowed_profile_ids'] == ['legacy']
        listed = await invoke(a,'files_profile_admin_list',{})
        assert any(p['name'] == '_new' for p in listed['profiles'])
        got = await invoke(a,'files_profile_admin_get',{'target_profile_id':'_new'})
        assert got['profiles'][0]['name'] == '_new'
        changed = await invoke(a,'files_profile_admin_update',{'target_profile_id':'_new',
            'changes':{'description':'Unicode α / bahasa'}, 'expected_revision':snapshot['revision'],'idempotency_key':'update'})
        defaulted = await invoke(a,'files_profile_admin_set_default',{'target_profile_id':'_new',
            'expected_revision':changed['revision'],'idempotency_key':'default'})
        snapshot = await a.registry.profile_catalog_snapshot(catalog_context(a.auth,a.place))
        catalog = validate_catalog(snapshot,a.auth,a.place,a.authorizer)
        assert catalog['default_profile_id'] == '_new'
        old = new_context(a.auth,a.place,'files:write','files_write',resource_authorizer=a.authorizer,selected_profile_id='_new',catalog=catalog)
        await invoke(a,'files_write',{'path':'new.txt','content':'paired','profile_id':'_new'},old)
        assert (target/'new.txt').read_text(encoding='utf-8') == 'paired'
        second = a.tmp/'reroot'; second.mkdir()
        rerooted = await invoke(a,'files_profile_admin_update',{'target_profile_id':'_new',
            'changes':{'root':str(second)},'expected_revision':snapshot['revision'],'idempotency_key':'reroot'})
        with pytest.raises((PermissionError, AuthorizationError)):
            await invoke(a,'files_write',{'path':'stale.txt','content':'must-not-retarget','profile_id':'_new'},old)
        assert not (second/'stale.txt').exists() and not (target/'stale.txt').exists()
        snapshot = await a.registry.profile_catalog_snapshot(catalog_context(a.auth,a.place))
        delete_args = {'target_profile_id':'_new','replacement_default_id':'legacy','expected_revision':snapshot['revision'],'idempotency_key':'delete'}
        deleted_context = new_admin_context(a.auth,a.place,a.authorizer,'files_profile_admin_delete',delete_args)
        deleted = await invoke(a,'files_profile_admin_delete',delete_args,deleted_context)
        assert deleted['status'] == 'committed' and (target/'new.txt').exists()
        assert (a.root/'marker.txt').read_text(encoding='utf-8') == 'original'
        current = validate_catalog(await a.registry.profile_catalog_snapshot(catalog_context(a.auth,a.place)),a.auth,a.place,a.authorizer)
        assert '_new' not in current['allowed_profile_ids']
        async def get(task):
            return {'session_id':a.auth.owner,'execution_context_json':json.dumps(deleted_context)}
        monkeypatch.setattr(perimeter.orchestrator.journal,'get',get)
        assert await perimeter._owned_task('deleted-receipt',a.auth)
        a.grant['profile_management']['enabled'] = False
        with pytest.raises(AuthorizationError):
            await perimeter._owned_task('deleted-receipt',a.auth)
    asyncio.run(run())


def test_explicit_profile_survives_disabled_default(setup):
    async def run():
        a = setup
        snapshot = await a.registry.profile_catalog_snapshot(catalog_context(a.auth,a.place))
        root = a.tmp/'selected'; root.mkdir()
        created = await invoke(a, 'files_profile_admin_create', {'target_profile_id':'selected',
            'root':str(root),'expected_revision':snapshot['revision'],'idempotency_key':'selected'})
        await invoke(a, 'files_profile_admin_update', {'target_profile_id':'legacy',
            'changes':{'enabled':False},'expected_revision':created['revision'],'idempotency_key':'disable-default'})
        catalog = validate_catalog(await a.registry.profile_catalog_snapshot(catalog_context(a.auth,a.place)), a.auth,a.place,a.authorizer)
        context = new_context(a.auth,a.place,'files:read','files_read',resource_authorizer=a.authorizer,
            selected_profile_id='selected',catalog=catalog)
        assert context['effective_resources'][0]['profile_id'] == 'selected'
        assert context['effective_resources'][0]['profile_generation'] == catalog['generations']['selected']
        with pytest.raises(AuthorizationError):
            new_context(a.auth,a.place,'files:read','files_read',resource_authorizer=a.authorizer,catalog=catalog)
        a.grant['profile_management'] = None
        with pytest.raises(AuthorizationError):
            validate_catalog(await a.registry.profile_catalog_snapshot(catalog_context(a.auth,a.place)),a.auth,a.place,a.authorizer)
    asyncio.run(run())


@pytest.mark.parametrize('change',[lambda g:g.pop('profile_management'), lambda g:g.update(profile_management=None), lambda g:g['profile_management'].update(enabled=False),
    lambda g:g['profile_management'].update(version=True),lambda g:g['profile_management'].update(extra='spoof'),
    lambda g:g['profile_management'].update(device_id='wrong'),lambda g:g.update(expires_at=time.time()-1),
    lambda g:g.update(revoked=True),lambda g:g.update(tools=[]),lambda g:g.update(scopes=['files:read'])])
def test_missing_malformed_changed_capability_denies(setup, change):
    change(setup.grant)
    with pytest.raises(AuthorizationError):
        require_profile_management(setup.auth,setup.place,setup.authorizer,'files_profile_admin_create')


def test_schema_and_public_spoof_rejection(setup):
    from jsonschema import Draft202012Validator, ValidationError
    for tool in PROFILE_ADMIN_SCOPES:
        schema = files_tool_schema({'name':tool,'inputSchema':{}})['inputSchema']
        assert 'profile_id' not in schema['properties'] and schema['additionalProperties'] is False
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate({'metadata':{'authorized':True}})
    for args in [{'metadata':{}},{'_meta':{}},{'principal_id':'fixture-principal'}]:
        with pytest.raises(ValueError):
            reject_authority(args)


def test_queued_capability_and_payload_change_denied(setup):
    a = setup
    ctx = new_admin_context(a.auth,a.place,a.authorizer,'files_profile_admin_list',{})
    a.grant['profile_management']['actions'].remove('list')
    with pytest.raises(AuthorizationError):
        revalidate_admin(ctx,a.auth,a.place,a.authorizer)
    a.grant['profile_management']['actions'].append('list')
    with pytest.raises(AuthorizationError):
        asyncio.run(invoke(a,'files_profile_admin_list',{'metadata':{}},ctx))

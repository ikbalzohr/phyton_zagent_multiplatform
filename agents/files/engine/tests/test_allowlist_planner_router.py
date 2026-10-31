"""Planner -> native owner loader -> Files HTTP -> Router catalog contract.

Windows-only disposable owner-ACL fixtures. No installed configuration, grants,
private keys or services are read or changed. The Router authorization context
and profile-generation provider are synthetic; this is NOT public ingress,
OAuth introspection, enrollment, checker hosting or live-session acceptance.
"""
import asyncio
import base64
import copy
from dataclasses import replace
from pathlib import Path
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from mcp.server.fastmcp import FastMCP
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from test_allowlist_adapter import protect, tmp_path
from test_allowlist_engine import env
from app.allowlist import bootstrap, protocol as p
from app.allowlist.host import FilesAllowlistHost, register_routes
from app.allowlist.owner_loader import SOURCE_FIELDS as PERSISTED_FIELDS, process_sid


@pytest.fixture
def chain(env, monkeypatch):
    # Import only pure Router modules, never server/config or live environment.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'tunnel' / 'engine'))
    from router.access import AuthContext, ResourceAuthorizer
    from router.identity import Placement
    from router.allowlist_admin import install_routes

    e = env
    root = e['tmp'] / 'planned-private'
    root.mkdir()
    protect(root)
    config = root / 'config'
    config.mkdir()
    protect(config)
    policy = config / 'policy.json'
    profiles = config / 'profiles.json'
    policy.write_bytes(e['policy_path'].read_bytes())
    profiles.write_bytes(e['profiles_path'].read_bytes())
    protect(policy)
    protect(profiles)
    placement = dict(principal_id='fixture-principal', workspace_id='fixture-workspace',
                     device_id='fixture-device', installation_id='fixture-install',
                     target_profile_id='agentRoot')
    request_key = Ed25519PrivateKey.generate()
    keys = {}
    for role, algorithm, key in [('approval', 'Ed25519', e['ed']),
                                 ('request', 'Ed25519', request_key),
                                 ('transport', 'X25519', e['x'])]:
        raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        keys[role] = dict(algorithm=algorithm, public_key=p.b64(raw), sha256=p.sha(raw),
                          key_id=role + '-' + p.sha(raw))
    bundle = p.canonical(dict(version=1, kind=bootstrap.BUNDLE_KIND, placement=placement, keys=keys))
    planned = bootstrap.plan(bundle, acknowledged_sha256=p.sha(bundle), placement=placement,
                             data_root=str(root), policy_path=str(policy), profiles_path=str(profiles),
                             owner_sid=process_sid(), expires_at=int(time.time()) + 3600)
    folder = root / 'allowlist'
    folder.mkdir()
    protect(folder)
    for name in planned['directories']:
        path = folder / name
        path.mkdir()
        protect(path)
    for name, encoded in planned['files'].items():
        path = folder / name
        path.write_bytes(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        protect(path)
    host = FilesAllowlistHost(folder / 'owner.json', post=lambda *a: pytest.fail('catalog must not call runtime/OAuth'))
    mcp = FastMCP('planned-fixture', stateless_http=True)
    register_routes(mcp, host)
    files_app = mcp.streamable_http_app()
    token = 'fixture-internal-token-at-least-32-bytes'
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN', token)
    grant = dict(scopes=['files:read', 'allowlist-admin'],
                 tools=['files_profile_admin_list', 'allowlist_admin_list'],
                 expires_at=time.time() + 3600, revoked=False,
                 files_resource=dict(kind='files', profile_id='agentRoot', allowed_profile_ids=['agentRoot'],
                                     device_id=placement['device_id'], installation_id=placement['installation_id'], revoked=False),
                 profile_management=dict(version=1, enabled=True, workspace_id=placement['workspace_id'],
                                         device_id=placement['device_id'], installation_id=placement['installation_id'], actions=['list']))
    auth = AuthContext(placement['principal_id'], placement['workspace_id'], frozenset(grant['scopes']),
                       frozenset(grant['tools']), 'fixture-revision', time.time() + 3600)
    authorizer = ResourceAuthorizer(dict(workspace_id=auth.workspace_id, policy_revision=auth.policy_revision,
                                        grants={auth.principal_id: grant}))
    state = {'auth': auth, 'allowed': ['agentRoot'], 'generation': 'fixture-generation'}
    async def catalog(current_auth, current_authorizer):
        current_authorizer.current_grant(current_auth)
        return dict(allowed_profile_ids=state['allowed'], generations={'agentRoot': state['generation']})
    async def run(action):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=files_app, client=('127.0.0.1', 3210)),
                                     base_url='http://127.0.0.1:18010') as upstream:
            class Registry:
                def enabled_states(self):
                    return [SimpleNamespace(service=dict(id='zagent_files', url='http://127.0.0.1:18010/mcp'))]
                def _client(self, service):
                    return upstream
            app = FastAPI()
            @app.middleware('http')
            async def fixture_auth(request, call_next):
                request.state.auth = state['auth']
                return await call_next(request)
            server = SimpleNamespace(app=app, Request=Request, registry=Registry(), authorizer=lambda: authorizer,
                                     placement=Placement(placement['device_id'], placement['installation_id']),
                                     _files_catalog=catalog)
            async def bounded_json(request):
                return await request.json()
            server.bounded_json = bounded_json
            route = install_routes(server)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://fixture.invalid') as client:
                return await action(client, route)
    return dict(host=host, planned=planned, folder=folder, policy=policy, profiles=profiles,
                before=(policy.read_bytes(), profiles.read_bytes()), placement=placement, run=run,
                auth=auth, state=state, grant=grant)


def catalog_response(c):
    async def action(client, route):
        return await client.post('/broker/allowlist/catalog', json={})
    return asyncio.run(c['run'](action))


def assert_inert(c):
    assert (c['policy'].read_bytes(), c['profiles'].read_bytes()) == c['before']
    for name in ('journal', 'replay'):
        assert list((c['folder'] / name).iterdir()) == []


def test_real_planner_source_projects_into_router_catalog(chain):
    c = chain
    persisted = p.loads((c['folder'] / 'capability.json').read_bytes())
    assert set(persisted) == PERSISTED_FIELDS
    assert 'mutations_ready' not in persisted
    assert c['host'].manifest['mutations_ready'] is False
    projected = c['host'].capability()
    assert projected == dict(persisted, mutations_ready=False)
    from router.allowlist_admin import SOURCE_FIELDS, capability_for
    assert set(projected) == SOURCE_FIELDS
    from router.identity import Placement
    place = Placement(c['placement']['device_id'], c['placement']['installation_id'])
    assert capability_for(projected, c['auth'], place, c['grant'], 'list') == c['placement']
    assert capability_for(projected, c['auth'], place, c['grant'], 'operation') == c['placement']
    response = catalog_response(c)
    assert response.status_code == 200, response.text
    assert response.json() == dict(version=1, placement=c['placement'], profile_generation='fixture-generation',
                                   capability_revision=c['planned']['capability_revision'], mutations_ready=False)
    assert response.headers['cache-control'] == 'no-store'
    assert_inert(c)


@pytest.mark.parametrize('fault', ['transport-field', 'revoked', 'expired', 'revision', 'placement', 'key-pin', 'manifest'])
def test_changed_planner_artifacts_deny_catalog(chain, fault):
    c = chain
    source = c['folder'] / 'capability.json'
    doc = p.loads(source.read_bytes())
    if fault == 'transport-field': doc['mutations_ready'] = False
    elif fault == 'revoked': doc['revoked'] = True
    elif fault == 'expired': doc['expires_at'] = int(time.time()) - 1
    elif fault == 'revision': doc['capability_revision'] = 'different'
    elif fault == 'placement': doc['placement']['device_id'] = 'different'
    elif fault == 'key-pin': (c['folder'] / 'request.pub').write_bytes(bytes(32))
    elif fault == 'manifest':
        manifest = copy.deepcopy(c['host'].manifest)
        manifest['mutations_ready'] = True
        (c['folder'] / 'owner.json').write_bytes(p.canonical(manifest))
    if fault not in ('key-pin', 'manifest'): source.write_bytes(p.canonical(doc))
    response = catalog_response(c)
    assert response.status_code == 403, response.text
    assert response.json() == {'error': 'ALLOWLIST_REQUEST_DENIED'}
    assert_inert(c)


@pytest.mark.parametrize('fault', ['dedicated-scope', 'dedicated-tool', 'files-scope', 'profile-tool',
                                  'profile-disabled', 'profile-actions', 'grant-revoked', 'grant-expired',
                                  'resource-revoked', 'resource-placement', 'resource-profile', 'catalog-profile'])
def test_router_independent_authority_gates_on_real_planned_host(chain, fault):
    c = chain
    auth = c['auth']
    if fault in ('dedicated-scope', 'files-scope'):
        scope = 'allowlist-admin' if fault == 'dedicated-scope' else 'files:read'
        c['state']['auth'] = replace(auth, scopes=auth.scopes - {scope})
    elif fault in ('dedicated-tool', 'profile-tool'):
        tool = 'allowlist_admin_list' if fault == 'dedicated-tool' else 'files_profile_admin_list'
        c['state']['auth'] = replace(auth, tools=auth.tools - {tool})
    elif fault == 'profile-disabled': c['grant']['profile_management']['enabled'] = False
    elif fault == 'profile-actions': c['grant']['profile_management']['actions'] = ['get']
    elif fault == 'grant-revoked': c['grant']['revoked'] = True
    elif fault == 'grant-expired': c['grant']['expires_at'] = time.time() - 1
    elif fault == 'resource-revoked': c['grant']['files_resource']['revoked'] = True
    elif fault == 'resource-placement': c['grant']['files_resource']['device_id'] = 'different'
    elif fault == 'resource-profile': c['grant']['files_resource']['allowed_profile_ids'] = ['different']
    elif fault == 'catalog-profile': c['state']['allowed'] = ['different']
    response = catalog_response(c)
    assert response.status_code == 403, response.text
    assert response.json() == {'error': 'ALLOWLIST_REQUEST_DENIED'}
    assert_inert(c)


def test_router_rejects_persisted_source_without_host_projection(chain, monkeypatch):
    c = chain
    persisted = p.loads((c['folder'] / 'capability.json').read_bytes())
    # Deliberately break just this transport seam, not the closed disk schema.
    with monkeypatch.context() as patch:
        patch.setattr(c['host'], 'capability', lambda: persisted)
        assert catalog_response(c).status_code == 403
    assert catalog_response(c).status_code == 200
    assert_inert(c)


def test_catalog_revalidates_source_after_success(chain):
    c = chain
    assert catalog_response(c).status_code == 200
    c['state']['generation'] = 'renewed-generation'
    assert catalog_response(c).json()['profile_generation'] == 'renewed-generation'
    source = c['folder'] / 'capability.json'
    original = source.read_bytes()
    doc = p.loads(original)
    doc['revoked'] = True
    source.write_bytes(p.canonical(doc))
    assert catalog_response(c).status_code == 403
    source.write_bytes(original)
    assert catalog_response(c).status_code == 200
    assert_inert(c)


def test_host_and_router_keep_mutations_disabled(chain):
    c = chain
    from router.allowlist_admin import capability_for
    from router.access import AuthorizationError
    from router.identity import Placement
    for method in ('prepare', 'backup', 'commit'):
        with pytest.raises(PermissionError, match='ALLOWLIST_MUTATIONS_NOT_READY'):
            asyncio.run(c['host'].dispatch({'body': {'method': method}}))
        with pytest.raises(AuthorizationError, match='ALLOWLIST_MUTATIONS_NOT_READY'):
            capability_for(c['host'].capability(), c['auth'], Placement(c['placement']['device_id'],
                           c['placement']['installation_id']), c['grant'], method)
    assert_inert(c)

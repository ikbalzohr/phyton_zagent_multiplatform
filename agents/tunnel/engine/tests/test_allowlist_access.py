"""Disposable HTTP fixtures; real introspection consumer, no live credentials."""
import json
import time
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
import httpx
from router import server, config
from router.access import principal_id
from router.identity import Placement

TOOL = 'zagent_allowlist_access'
TOOLS = ['files_allowlist_' + a for a in ('list', 'add', 'remove', 'replace')]

class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'tunnel.json'
        self.principal = principal_id('https://issuer.invalid', 'owner')
        grant = dict(scopes=['files:read','files:write'], tools=['files_profile_admin_update'],
            expires_at=time.time()+600, profile_management=dict(version=1, enabled=True,
            workspace_id='ws', device_id='d', installation_id='i', actions=['update']),
            files_resource=dict(kind='files',resource_id='r',profile_id='A',device_id='d',installation_id='i'))
        self.cfg = dict(resource_server=dict(resource_uri='https://resource.invalid', issuer='https://issuer.invalid',
            introspection_endpoint='https://issuer.invalid/introspect',workspace_id='ws',policy_revision='1',
            introspection_client_id='fixture', introspection_secret_env='FIXTURE_ACCESS_SECRET',
            authorization_servers=['https://issuer.invalid'],grants={self.principal:grant,'other':{'untouched':True}}),
            grant_writer_lock_version=1, tool_policy={}, unrelated={'credential':'fixture-sensitive-do-not-return'})
        self.save()
        self.introspect = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=dict(
            active=True,iss='https://issuer.invalid',sub='owner',exp=time.time()+600,
            aud='https://resource.invalid',scope='files:read files:write'))))
        self.addAsyncCleanup(self.introspect.aclose)
        self.owner = dict(workspace_id='ws',device_id='d',installation_id='i',resource_id='r',default_profile_id='A',allowed_profile_ids=['A'])
        self.catalog = dict(managed=True,revision='a'*64,profiles=[dict(name='A',authorized_by_user=True,enabled=True)],generations={'A':'g'},owner=deepcopy(self.owner))
        for obj,key,value in [(config,'TUNNEL_FILE',self.path),(server,'placement',Placement('d','i')),
            (server,'_auth_client',self.introspect),(server.registry,'tool_index',{t:('zagent_files',t) for t in TOOLS}),
            (server.registry,'list_public_tools',lambda:[dict(name=t,inputSchema={'type':'object'}) for t in TOOLS]),
            (server.registry,'profile_catalog_snapshot',AsyncMock(return_value=self.catalog))]:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        p=patch.dict('os.environ',{'FIXTURE_ACCESS_SECRET':'fixture'});p.start();self.addCleanup(p.stop)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='https://fixture.invalid')
        self.addAsyncCleanup(self.client.aclose)
    def save(self): self.path.write_text(json.dumps(self.cfg))
    async def rpc(self,method,params=None):
        return await self.client.post('/mcp',headers={'Authorization':'Bearer fixture'},json=dict(jsonrpc='2.0',id=1,method=method,params=params or {}))
    async def call(self,**args): return await self.rpc('tools/call',dict(name=TOOL,arguments=args))
    def value(self,r):
        result=r.json()['result']; self.assertFalse(result['isError']);return json.loads(result['content'][0]['text'])
    async def test_unmanaged_or_missing_owner_cannot_enable_memberships(self):
        for managed, owner in ((False, None), (True, None)):
            self.catalog.update(managed=managed, owner=owner)
            before = self.path.read_bytes()
            self.assertEqual((await self.call()).status_code, 403)
            self.assertEqual(before, self.path.read_bytes())

    async def test_duplicate_configuration_keys_are_not_normalized(self):
        raw = self.path.read_text().rstrip()
        self.path.write_text(raw[:-1] + ', "tool_policy": {}}')
        before = self.path.read_bytes()
        response = await self.call()
        self.assertTrue(response.status_code != 200 or 'error' in response.json())
        self.assertEqual(before, self.path.read_bytes())

    async def test_core_writer_protocol_is_required(self):
        for value in (None, False, 2):
            self.cfg['grant_writer_lock_version'] = value
            self.save()
            self.assertEqual((await self.call()).status_code, 403)

    async def test_discovery_plan_apply_new_auth(self):
        names=[t['name'] for t in (await self.rpc('tools/list')).json()['result']['tools']]
        self.assertIn(TOOL,names);self.assertFalse(set(TOOLS)&set(names))
        before=self.path.read_bytes(); plan=self.value(await self.call())
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(plan,self.value(await self.call()))
        result=self.value(await self.call(plan_only=False,expected_revision=plan['revision'],expected_plan=plan['expected_plan']))
        self.assertTrue(result['audit_verified']);self.assertNotIn('fixture-sensitive',json.dumps(result))
        after=json.loads(self.path.read_bytes());expected=deepcopy(self.cfg)
        expected['resource_server']['grants'][self.principal]['tools']+=TOOLS
        self.assertEqual(after,expected)
        names=[t['name'] for t in (await self.rpc('tools/list')).json()['result']['tools']]
        self.assertTrue(set(TOOLS)<=set(names))
        self.assertEqual(self.value(await self.call())['state'],'enabled')
        self.assertTrue(self.value(await self.call())['audit_verified'])

    async def test_denials_preserve_raw_config(self):
        original=deepcopy(self.cfg)
        mutations=[lambda g:g.pop('profile_management'),lambda g:g.update(expires_at=time.time()-1),
            lambda g:g.update(revoked=True),lambda g:g['profile_management'].update(actions=['list']),
            lambda g:g['profile_management'].update(workspace_id='other'),
            lambda g:g['files_resource'].update(device_id='other'),
            lambda g:g.update(tools='files_profile_admin_update'),lambda g:g.update(tools=['files_profile_admin_update',3]),
            lambda g:g.update(scopes=['files:write'])]
        for mutate in mutations:
            self.cfg=deepcopy(original);mutate(self.cfg['resource_server']['grants'][self.principal]);self.save()
            before=self.path.read_bytes();r=await self.call()
            self.assertTrue(r.status_code != 200 or 'error' in r.json());self.assertEqual(before,self.path.read_bytes())
        self.cfg=original;self.save()
        for args in [dict(target_principal='other'),dict(scopes=['files:write']),dict(tools=TOOLS),dict(root='x'),dict(command='x')]:
            before=self.path.read_bytes();self.assertIn('error',(await self.call(**args)).json());self.assertEqual(before,self.path.read_bytes())

    async def test_stale_revision_policy_backend_and_publication_denials(self):
        plan=self.value(await self.call());before=self.path.read_bytes()
        self.assertEqual((await self.call(plan_only=False,expected_revision='0'*64,expected_plan=plan['expected_plan'])).status_code,409)
        self.assertEqual(before,self.path.read_bytes())
        for name in [TOOL,*TOOLS]:
            self.cfg['tool_policy']={name:dict(scope='files:write',enabled=False)};self.save()
            self.assertNotEqual((await self.call()).status_code,200)
        self.cfg['tool_policy']={};self.save()
        with patch.dict(server.registry.tool_index,{TOOLS[0]:('zagent_files','renamed')}):
            self.assertEqual((await self.call()).status_code,409)
        from router import allowlist_access
        plan=self.value(await self.call());before=self.path.read_bytes()
        with patch.object(allowlist_access.os,'replace',side_effect=OSError('fixture-private-error')):
            response=await self.call(plan_only=False,expected_revision=plan['revision'],expected_plan=plan['expected_plan'])
            self.assertTrue(response.status_code != 200 or 'error' in response.json())
            self.assertNotIn('fixture-private-error',response.text)
        self.assertEqual(before,self.path.read_bytes());self.assertFalse(self.value(await self.call())['audit_verified'])

    async def test_managed_catalog_other_owner_and_other_principal_denied(self):
        self.catalog.update(managed=True,owner=dict(workspace_id='other',device_id='d',installation_id='i',resource_id='r',default_profile_id='A',allowed_profile_ids=['A']))
        self.assertEqual((await self.call()).status_code,403)
        self.catalog.update(managed=True,owner=deepcopy(self.owner))
        self.cfg['resource_server']['grants']['other']=deepcopy(self.cfg['resource_server']['grants'][self.principal])
        self.cfg['resource_server']['grants']['other'].pop('profile_management');self.save()
        before=self.path.read_bytes()
        from dataclasses import replace
        auth=await server.authorizer().authenticate('Bearer fixture',self.introspect)
        with patch.object(server.authorizer().__class__,'authenticate',AsyncMock(return_value=replace(auth,principal_id='other'))):
            self.assertEqual((await self.call()).status_code,403)
        self.assertEqual(before,self.path.read_bytes())

    async def test_concurrent_apply_one_commit_and_stale_config(self):
        import asyncio
        plan=self.value(await self.call())
        args=dict(plan_only=False,expected_revision=plan['revision'],expected_plan=plan['expected_plan'])
        responses=await asyncio.gather(self.call(**args),self.call(**args))
        self.assertEqual(sorted(r.status_code for r in responses),[200,409])
        self.assertTrue(self.value(await self.call())['audit_verified'])
        self.cfg['unrelated']['more']='changed';self.save()
        before=self.path.read_bytes()
        self.assertEqual((await self.call(**args)).status_code,409)
        self.assertEqual(before,self.path.read_bytes())

    async def test_fresh_commit_auth_revocation_blocks_write(self):
        from router.access import ResourceAuthorizer
        plan=self.value(await self.call());before=self.path.read_bytes()
        real=ResourceAuthorizer.authenticate
        count=0
        async def changed(instance,*args):
            nonlocal count
            count+=1
            if count==3:
                self.cfg['resource_server']['grants'][self.principal]['revoked']=True;self.save()
            return await real(instance,*args)
        with patch.object(ResourceAuthorizer,'authenticate',changed):
            self.assertEqual((await self.call(plan_only=False,expected_revision=plan['revision'],expected_plan=plan['expected_plan'])).status_code,403)
        self.assertEqual(json.loads(self.path.read_bytes())['resource_server']['grants'][self.principal]['tools'],['files_profile_admin_update'])

    @unittest.skipIf(__import__('os').name == 'nt', 'Unix permission contract')
    def test_new_lock_is_owner_private(self):
        from router.allowlist_access import writer
        with writer(self.path):
            self.assertEqual(Path(str(self.path)+'.access.lock').stat().st_mode & 0o777, 0o600)

    def test_writer_cas_and_shared_lock(self):
        from router.allowlist_access import writer,publish
        before=self.path.read_bytes()
        with writer(self.path):
            with self.assertRaises(OSError):config.atomic_write_json(self.path,{'bad':True})
            self.path.write_bytes(before+b' ')
            with self.assertRaisesRegex(Exception,'REVISION_CONFLICT'):
                publish(self.path,b'{}',before,lambda:None)
        self.assertEqual(self.path.read_bytes(),before+b' ')

    def test_shared_config_writer_preserves_mode_and_cleans_failed_stage(self):
        self.path.chmod(0o600)
        with patch('os.replace',side_effect=OSError('fixture')):
            with self.assertRaises(OSError):config.atomic_write_json(self.path,{'new':True})
        self.assertEqual(list(self.path.parent.glob('*.tmp')),[])
        config.atomic_write_json(self.path,{'new':True})
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

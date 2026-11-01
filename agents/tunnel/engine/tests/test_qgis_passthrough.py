import time
import unittest
from unittest.mock import patch
from router import server
from router.access import AuthContext, AuthorizationError, ResourceAuthorizer
from router.registry import MCPRegistry, UpstreamState

SERVICE = {'id': 'zagent_qgis', 'name': 'QGIS upstream', 'namespace': 'qgis',
           'url': 'http://127.0.0.1:18850/mcp', 'enabled': True, 'internal_auth': False}

class QgisPassthroughTests(unittest.TestCase):
    def setUp(self):
        from router.identity import Placement
        placement_patch=patch.object(server,'placement',Placement('device','installation'))
        placement_patch.start(); self.addCleanup(placement_patch.stop)
        self.registry = object.__new__(MCPRegistry)
        self.registry.states = {'zagent_qgis': UpstreamState(SERVICE.copy(), tools=[
            {'name': n, 'description': n, 'inputSchema': {'type': 'object', 'properties': {}}}
            for n in ('ping', 'execute_code', 'future_upstream_tool')])}
        self.registry.clients = {}
        self.registry.rebuild_index()
        self.auth = AuthContext('p', 'ws', frozenset({'files:read','files:write','files:execute'}),
            frozenset({'files_powershell_run'}), '1', time.time()+60)
        self.config = {'tool_policy': {'files_powershell_run': {'scope': 'files:execute', 'enabled': True}}}
        self.authorizer = ResourceAuthorizer({'workspace_id':'ws','policy_revision':'1', 'grants':{
            'p': {'files_resource': {'resource_id':'ws:files','kind':'files','profile_id':'agentRoot',
            'device_id':server.placement.device_id,'installation_id':server.placement.installation_id}}}})
        self.patches = [patch.object(server, 'registry', self.registry),
            patch.object(server, 'load_tunnel_config', return_value=self.config),
            patch.object(server, 'authorizer', return_value=self.authorizer)]
        for p in self.patches:p.start(); self.addCleanup(p.stop)

    def test_all_configured_upstream_tools_reuse_existing_command_authority(self):
        names = {t['name'] for t in server._visible(self.auth)}
        self.assertTrue({'qgis_ping','qgis_execute_code','qgis_future_upstream_tool'} <= names)
        self.assertNotIn('qgis_execute_code', self.auth.tools)

    def test_explicit_disable_and_unrelated_tools_are_not_broadened(self):
        self.config['tool_policy']['qgis_execute_code'] = {'scope':'files:execute','enabled':False}
        names = {t['name'] for t in server._visible(self.auth)}
        self.assertNotIn('qgis_execute_code', names)
        self.assertNotIn('files_read', names)
        self.config['tool_policy']['files_powershell_run']['enabled'] = False
        self.assertFalse(any(t['name'].startswith('qgis_') for t in server._visible(self.auth)))

    def test_missing_scope_membership_and_revoked_resource_deny(self):
        for scopes, tools in [({'files:read'}, {'files_powershell_run'}),
                              ({'files:read','files:write'}, set())]:
            auth = AuthContext('p','ws',frozenset(scopes),frozenset(tools),'1',time.time()+60)
            self.assertFalse(any(t['name'].startswith('qgis_') for t in server._visible(auth)))
        self.authorizer.config['grants']['p']['files_resource']['revoked'] = True
        self.assertFalse(any(t['name'].startswith('qgis_') for t in server._visible(self.auth)))


    def test_expired_token_and_wrong_service_never_get_passthrough_defaults(self):
        expired = AuthContext('p','ws',self.auth.scopes,self.auth.tools,'1',time.time()-1)
        self.assertFalse(any(t['name'].startswith('qgis_') for t in server._visible(expired)))
        self.registry.states['zagent_qgis'].service['id']='unrelated'
        self.assertFalse(any(t['name'].startswith('qgis_') for t in server._visible(self.auth)))

    def test_malformed_explicit_policy_and_execute_without_write_fail_closed(self):
        for malformed in (False, [], {}, {'scope':'files:read'}):
            self.config['tool_policy']['qgis_execute_code']=malformed
            self.assertNotIn('qgis_execute_code',{t['name'] for t in server._visible(self.auth)})
        auth=AuthContext('p','ws',frozenset({'files:read','files:execute'}),self.auth.tools,'1',time.time()+60)
        self.assertFalse(any(t['name'].startswith('qgis_') for t in server._visible(auth)))

    def test_context_keeps_qgis_identity_and_existing_files_resource(self):
        import asyncio
        from router.execution_context import validate_context
        context=asyncio.run(server._request_context(self.auth,server._policy('qgis_execute_code'),
            'qgis_execute_code',{}))
        self.assertEqual(context['public_tool'],'qgis_execute_code')
        self.assertEqual(context['required_scope'],'files:execute')
        self.assertEqual(context['effective_resources'][0]['profile_id'],'agentRoot')
        self.assertEqual(validate_context(context,server.placement),context)

    def test_client_authority_is_still_rejected(self):
        with self.assertRaises(ValueError):
            server._validate_tool('qgis_execute_code',{'principal_id':'attacker'},self.auth)

if __name__ == '__main__':unittest.main()

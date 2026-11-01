import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from router.registry import MCPRegistry, UpstreamState

class QgisTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_paginated_catalog_and_unmodified_result_without_private_credentials(self):
        requests = []
        result = {'content':[{'type':'image','data':'AA==','mimeType':'image/png'}],
                  'structuredContent':{'value':42}, 'isError': True}
        def handler(request):
            body=json.loads(request.content); requests.append((dict(request.headers),body))
            method=body['method']
            if method == 'initialize':data={'protocolVersion':'2025-06-18','capabilities':{},'serverInfo':{'name':'fixture','version':'1'}}
            elif method == 'notifications/initialized':return httpx.Response(202)
            elif method == 'tools/list':
                cursor=body['params'].get('cursor')
                data={'tools':[{'name':'future' if cursor else 'ping','inputSchema':{'type':'object'}}]}
                if not cursor:data['nextCursor']='page2'
            else:data=result
            return httpx.Response(200,json={'jsonrpc':'2.0','id':body.get('id'),'result':data},headers={'mcp-session-id':'session'})
        registry=object.__new__(MCPRegistry)
        svc={'id':'zagent_qgis','namespace':'qgis','name':'QGIS','url':'http://127.0.0.1:18850/mcp','internal_auth':False}
        registry.states={'zagent_qgis':UpstreamState(svc)};registry.tool_index={}
        registry.clients={'zagent_qgis':httpx.AsyncClient(transport=httpx.MockTransport(handler))}
        self.addAsyncCleanup(registry.close)
        with patch('router.registry.internal_token',side_effect=AssertionError('must not read private token')):
            status=await registry.refresh_service('zagent_qgis')
            self.assertTrue(status['ok'],status)
            self.assertEqual(set(registry.tool_index),{'qgis_ping','qgis_future'})
            ctx=SimpleNamespace(execution_context={'public_tool':'qgis_ping'},session_id='owner',request_id='req',
                trace_id='trace',task_id='task',profile_id='',idempotency_key='',resource_key='install',access_mode='write',priority=2)
            actual=await registry.invoke('zagent_qgis','ping',{'hello':'world'},ctx)
            for k,v in result.items():self.assertEqual(actual[k],v)
        for headers,body in requests:
            self.assertNotIn('x-zagent-internal-token',headers)
            self.assertNotIn('authorization',headers)
            if body['method']=='tools/call':
                self.assertEqual(body['params'],{'name':'ping','arguments':{'hello':'world'}})
        self.assertEqual(requests[-1][0]['mcp-protocol-version'],'2025-06-18')


    async def test_malformed_internal_auth_is_not_coerced(self):
        from router.config import validate_service
        config={'security':{'allowed_hosts':['127.0.0.1']}}
        for value in ('false',None,0,[]):
            service={'id':'zagent_qgis','namespace':'qgis','name':'QGIS',
                'url':'http://127.0.0.1:18850/mcp','internal_auth':value}
            with patch('router.config.load_tunnel_config',return_value=config):
                with self.assertRaises(ValueError):validate_service(service)

if __name__=='__main__':unittest.main()

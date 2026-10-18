import assert from 'node:assert/strict';
const base = 'http://127.0.0.1:8021';
let session;
async function rpc(id, method, params = {}) {
  const response = await fetch(base + '/mcp', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
      ...(session ? { 'Mcp-Session-Id': session, 'MCP-Protocol-Version': '2025-11-25' } : {}) },
    body: JSON.stringify({ jsonrpc: '2.0', id, method, params }), signal: AbortSignal.timeout(10000) });
  assert.equal(response.status, 200);
  session = response.headers.get('mcp-session-id') || session;
  const raw = await response.text();
  const data = response.headers.get('content-type')?.includes('text/event-stream')
    ? JSON.parse(raw.split('\n').find(line => line.startsWith('data:')).slice(5)) : JSON.parse(raw);
  assert.ok(!data.error, JSON.stringify(data.error)); return data.result;
}
const health = await (await fetch(base + '/health')).json();
assert.equal(health.service, 'Zagent Web');
await rpc(1, 'initialize', { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'bridge-smoke', version: '1.0' } });
const list = await rpc(2, 'tools/list');
for (const name of ['web_bridge_status', 'web_bridge_revoke', 'web_bridge_disconnect', 'web_bridge_tabs', 'web_bridge_select_tab']) assert.ok(list.tools.some(t => t.name === name));
const status = await rpc(3, 'tools/call', { name: 'web_bridge_status', arguments: {} });
assert.ok(!status.isError);
const forbidden = await fetch(base + '/bridge/status', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: 'https://untrusted.invalid' }, body: '{}' });
assert.equal(forbidden.status, 403);
console.log(JSON.stringify({ ok: true, tools: list.tools.length, nativeAttached: health.nativeAttached, ownershipPreserved: health.ownsBrowserProcess === false,
  bridgeStatus: JSON.parse(status.content[0].text), untrustedOriginRejected: true }, null, 2));

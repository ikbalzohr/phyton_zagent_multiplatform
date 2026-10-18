import test from 'node:test';
import assert from 'node:assert/strict';
import { verifyExecutionContext, BrowserResourceOwner, internalTransport, authenticateInternalToken } from '../src/server/executionContext.js';

function invocation() {
  process.env.ZAGENT_INTERNAL_TOKEN = 'k'.repeat(32);
  process.env.ZAGENT_DEVICE_ID = 'device';
  return {_meta: {'zagent.execution_context': {
    context_version:1, principal_id:'p', workspace_id:'w', device_id:'device',
    operation_id:'op', request_id:'r', trace_id:'t', deadline: Date.now()/1000+30,
    effective_access:'read', effective_resources:[{resource_id:'browser',kind:'browser'}]
  }}};
}

test('public metadata cannot authorize an invocation', () => {
  const extra = invocation();
  assert.throws(() => verifyExecutionContext('web_get_url', {}, extra));
  assert.ok(authenticateInternalToken('k'.repeat(32)));
  assert.equal(authenticateInternalToken('wrong'), false);
  internalTransport.run(true, () => {
    assert.equal(verifyExecutionContext('web_get_url', {}, extra).workspace_id, 'w');
    const invalid = structuredClone(extra);
    invalid._meta['zagent.execution_context'].device_id = 'other';
    assert.throws(() => verifyExecutionContext('web_get_url', {}, invalid));
    invalid._meta['zagent.execution_context'].device_id = 'device';
    invalid._meta['zagent.execution_context'].deadline = 0;
    assert.throws(() => verifyExecutionContext('web_get_url', {}, invalid));
  });
});

test('single native browser cannot silently rebind to another workspace', () => {
  const owner = new BrowserResourceOwner();
  internalTransport.run(true, () => {
    const ctx = verifyExecutionContext('web_get_url', {}, invocation());
    owner.claim(ctx);
    owner.claim({...ctx, request_id:'reconnected'});
    assert.throws(() => owner.claim({...ctx, workspace_id:'other'}));
    assert.throws(() => owner.claim({...ctx, effective_resources:[{resource_id:'other',kind:'browser'}]}));
  });
});

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { bridge } from '../src/bridge/Bridge.js';
import { installBridgeGate, targetFor, resolveTargets, authorizedTabs, selectTab } from '../src/bridge/gate.js';
import { browserManager as B } from '../src/browser/BrowserManager.js';
import { registerAllTools } from '../src/tools/index.js';

test('all registered tools pass through gate; exact target mapping and revocation enforced', async () => {
  // Redirect the singleton into a disposable fixture, never the production config.
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'zagent-gate-'));
  const originalPath = bridge.configFile;
  Object.defineProperty(bridge, 'configFile', { value: path.join(dir, 'bridge.json'), configurable: true });
  const callbacks = new Map<string, (...args: any[]) => any>();
  const server = { registerTool: (name: string, _config: unknown, callback: any) => callbacks.set(name, callback) };
  installBridgeGate(server as any); registerAllTools(server as any);
  const page = (id: string, windowId: number, url: string) => ({
    isClosed: () => false, url: () => url, title: async () => id,
    bringToFront: async () => {},
    context: () => ({ newCDPSession: async () => ({
      send: async (method: string) => method === 'Target.getTargetInfo' ? { targetInfo: { targetId: id } } : { windowId }, detach: async () => {}
    }) })
  });
  const a = page('A', 1, 'https://example.com'), b = page('B', 1, 'https://example.com');
  (B as any).nativeAttached = true; B.browser = { isConnected: () => true } as any;
  B.context = { pages: () => [a, b] } as any; B.page = a as any;
  try {
    await fs.writeFile(bridge.configFile, JSON.stringify({ required: true, pairingHash: createHash('sha256').update('gate-code').digest('hex'), pairingExpiresAt: Date.now() + 300000 }));
    assert.equal(callbacks.size, 151);
    for (const name of ['web_get_url', 'web_new_tab', 'web_switch_tab', 'web_browser_start', 'web_run_steps', 'web_workflow', 'web_evaluate', 'web_native_chrome_tabs']) {
      const callback = callbacks.get(name); if (callback) await assert.rejects(callback({}));
    }
    const pairState = bridge.requestPair(60, {
      directory: 'Profile 14',
      name: 'HARRY',
      userName: 'harry.indrah3@gmail.com',
      gaiaId: null
    });
    await bridge.acceptPairRequest(
      pairState.pairingPending!.id,
      'chrome-extension://' + 'a'.repeat(32),
      {
        instanceId: 'gate-profile-instance-0001',
        email: 'harry.indrah3@gmail.com',
        gaiaId: ''
      }
    );
    bridge.grant('tab', [await targetFor(a as any)], 900);
    assert.deepEqual(await resolveTargets(['A']), [{ id: 'A', windowId: 1, origin: 'https://example.com' }]);
    await assert.rejects(resolveTargets(['missing']));
    assert.equal((await authorizedTabs()).length, 1);
    await assert.rejects(selectTab('B'));
    await selectTab('A');
    assert.ok(await callbacks.get('web_get_url')!({}));
    B.page = b as any; await assert.rejects(callbacks.get('web_get_url')!({})); B.page = a as any;
    for (const [name, callback] of callbacks) {
      if (/workflow|evaluate|cookie|session|run_steps|network|storage|browser_start|new_tab|switch_tab/.test(name)) await assert.rejects(callback({}));
    }
    await callbacks.get('web_bridge_revoke')!({}); await assert.rejects(callbacks.get('web_get_url')!({}));
    assert.equal(await bridge.refresh(), true);
    await fs.writeFile(bridge.configFile, JSON.stringify({ required: false }));
    assert.ok(await callbacks.get('web_get_url')!({}));
  } finally {
    bridge.revoke(true); B.browser = null; B.page = null; B.context = null;
    Object.defineProperty(bridge, 'configFile', { value: originalPath, configurable: true });
    await fs.rm(dir, { recursive: true, force: true });
  }
});

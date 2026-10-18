import test from "node:test";
import assert from "node:assert/strict";
import { NativeAttachCoordinator } from "../src/browser/NativeAttachCoordinator.js";
import { browserManager } from "../src/browser/BrowserManager.js";
import { nativeChrome } from "../src/browser/NativeChromeManager.js";
import { bridge } from "../src/bridge/Bridge.js";

test("native attach coordinator waits for trusted bridge then attaches to CDP", async () => {
  const originalSettings = browserManager.settings;
  const originalIsNativeAttached = browserManager.isNativeAttached;
  const originalDiscoverEndpoint = nativeChrome.discoverEndpoint;
  const originalAttach = nativeChrome.attach;
  const originalRefresh = bridge.refresh;
  const originalStatus = bridge.status;

  let attached = false;
  let attachCalls = 0;
  let connected = false;

  try {
    (browserManager as any).settings = { runtimeMode: "native_attach", nativeAutoAttach: true };
    (browserManager as any).isNativeAttached = () => attached;
    (nativeChrome as any).discoverEndpoint = async () => "ws://127.0.0.1:9222/devtools/browser/test";
    (nativeChrome as any).attach = async () => {
      attachCalls += 1;
      attached = true;
      return { nativeAttached: true };
    };
    (bridge as any).refresh = async () => true;
    (bridge as any).status = () => ({
      required: true,
      connected,
      profileBound: true,
      profileBinding: { directory: "Profile 14", name: "HARRY" },
    });

    const coordinator = new NativeAttachCoordinator();

    const waiting = await coordinator.ensureAttached({ requireBridgeConnected: true });
    assert.equal(waiting.attached, false);
    assert.equal(waiting.reason, "bridge-not-connected");
    assert.equal(attachCalls, 0);

    connected = true;
    const result = await coordinator.ensureAttached({ requireBridgeConnected: true, strict: true });
    assert.equal(result.attached, true);
    assert.equal(result.reason, "attached");
    assert.equal(result.endpoint, "ws://127.0.0.1:9222/devtools/browser/test");
    assert.equal(attachCalls, 1);

    const again = await coordinator.ensureAttached({ requireBridgeConnected: true, strict: true });
    assert.equal(again.reason, "already-attached");
    assert.equal(attachCalls, 1);
  } finally {
    (browserManager as any).settings = originalSettings;
    (browserManager as any).isNativeAttached = originalIsNativeAttached;
    (nativeChrome as any).discoverEndpoint = originalDiscoverEndpoint;
    (nativeChrome as any).attach = originalAttach;
    (bridge as any).refresh = originalRefresh;
    (bridge as any).status = originalStatus;
  }
});

test("native attach coordinator fails closed when trusted bridge has no CDP endpoint", async () => {
  const originalSettings = browserManager.settings;
  const originalIsNativeAttached = browserManager.isNativeAttached;
  const originalDiscoverEndpoint = nativeChrome.discoverEndpoint;
  const originalRefresh = bridge.refresh;
  const originalStatus = bridge.status;

  try {
    (browserManager as any).settings = { runtimeMode: "native_attach", nativeAutoAttach: true };
    (browserManager as any).isNativeAttached = () => false;
    (nativeChrome as any).discoverEndpoint = async () => null;
    (bridge as any).refresh = async () => true;
    (bridge as any).status = () => ({
      required: true,
      connected: true,
      profileBound: true,
      profileBinding: { directory: "Profile 14", name: "HARRY" },
    });

    const coordinator = new NativeAttachCoordinator();
    await assert.rejects(
      coordinator.ensureAttached({ requireBridgeConnected: true, strict: true }),
      /no local Chrome CDP endpoint/i
    );
  } finally {
    (browserManager as any).settings = originalSettings;
    (browserManager as any).isNativeAttached = originalIsNativeAttached;
    (nativeChrome as any).discoverEndpoint = originalDiscoverEndpoint;
    (bridge as any).refresh = originalRefresh;
    (bridge as any).status = originalStatus;
  }
});

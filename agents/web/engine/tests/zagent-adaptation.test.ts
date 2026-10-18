import test from "node:test";
import assert from "node:assert/strict";
import { registerBridgeTools } from "../src/tools/bridge.js";
import { bridge } from "../src/bridge/Bridge.js";
import { targetFor } from "../src/bridge/gate.js";
import { nativeChrome } from "../src/browser/NativeChromeManager.js";
import { browserManager as B } from "../src/browser/BrowserManager.js";
import { validateNavigableUrl } from "../src/utils/security.js";

test("blank/new-tab targets are eligible for bridge authorization", async () => {
  const previousBrowser = B.browser;
  const previousNativeAttached = (B as any).nativeAttached;
  (B as any).nativeAttached = true;
  B.browser = { isConnected: () => true } as any;

  const page = {
    isClosed: () => false,
    url: () => "about:blank",
    context: () => ({
      newCDPSession: async () => ({
        send: async (method: string) =>
          method === "Target.getTargetInfo"
            ? { targetInfo: { targetId: "blank-1" } }
            : { windowId: 7 },
        detach: async () => {},
      }),
    }),
  };

  try {
    assert.deepEqual(
      await targetFor(page as any),
      { id: "blank-1", windowId: 7, origin: "zagent://blank" },
    );
  } finally {
    B.browser = previousBrowser;
    (B as any).nativeAttached = previousNativeAttached;
  }
});

test("bridge-authorized navigation bypasses static host allowlist but keeps protocol restriction", () => {
  const settings = {
    allowedHosts: ["example.com"],
    allowExternalHosts: false,
  } as any;

  assert.throws(
    () => validateNavigableUrl("https://google.com/", settings),
    /not allowed/i,
  );
  assert.equal(
    validateNavigableUrl(
      "https://google.com/",
      settings,
      { bypassHostAllowlist: true },
    ),
    "https://google.com/",
  );
  assert.throws(
    () => validateNavigableUrl(
      "file:///C:/Windows/win.ini",
      settings,
      { bypassHostAllowlist: true },
    ),
    /http\/https/i,
  );
});

test("pair returns immediately when multiple running Chrome profiles are plausible", async () => {
  const callbacks = new Map<string, (...args: any[]) => any>();
  registerBridgeTools({
    registerTool: (name: string, _config: unknown, callback: any) =>
      callbacks.set(name, callback),
  } as any);

  const saved = {
    refresh: bridge.refresh,
    status: bridge.status,
    observed: bridge.observedExtensionProfiles,
    profiles: nativeChrome.profiles,
    statusChrome: nativeChrome.status,
    running: nativeChrome.runningProfileDirectories,
    bridgeProfiles: nativeChrome.profilesWithZagentBridge,
    hint: nativeChrome.activeProfileHint,
  };

  (bridge as any).refresh = async () => true;
  (bridge as any).status = () => ({
    required: true,
    connected: false,
    authorized: false,
    profileBinding: null,
  });
  (bridge as any).observedExtensionProfiles = () => [];
  (nativeChrome as any).profiles = async () => [
    {
      directory: "Profile 1",
      name: "One",
      userName: "one@example.com",
      gaiaName: null,
      gaiaId: null,
      activeTime: 2,
    },
    {
      directory: "Profile 2",
      name: "Two",
      userName: "two@example.com",
      gaiaName: null,
      gaiaId: null,
      activeTime: 1,
    },
  ];
  (nativeChrome as any).status = async () => ({
    installed: true,
    running: true,
    processCount: 2,
  });
  (nativeChrome as any).runningProfileDirectories = async () => [
    "Profile 1",
    "Profile 2",
  ];
  (nativeChrome as any).profilesWithZagentBridge = async () => [];
  (nativeChrome as any).activeProfileHint = async () => ({
    lastUsed: "Profile 1",
    lastActiveProfiles: ["Profile 1", "Profile 2"],
    safeProfile: null,
    reason: "multiple-active-profiles",
  });

  try {
    const started = Date.now();
    const result = await callbacks.get("web_bridge_pair")!({
      expiresInSeconds: 180,
    });
    const elapsed = Date.now() - started;
    const payload = JSON.parse(result.content[0].text);

    assert.equal(payload.outcome, "profile_selection_required");
    assert.equal(payload.candidates.length, 2);
    assert.ok(elapsed < 1000, "ambiguous pair should not wait for pairing timeout");
  } finally {
    (bridge as any).refresh = saved.refresh;
    (bridge as any).status = saved.status;
    (bridge as any).observedExtensionProfiles = saved.observed;
    (nativeChrome as any).profiles = saved.profiles;
    (nativeChrome as any).status = saved.statusChrome;
    (nativeChrome as any).runningProfileDirectories = saved.running;
    (nativeChrome as any).profilesWithZagentBridge = saved.bridgeProfiles;
    (nativeChrome as any).activeProfileHint = saved.hint;
  }
});


test("closed profile with installed Bridge is opened before pairing even when another Chrome profile is running", async () => {
  const callbacks = new Map<string, (...args: any[]) => any>();
  registerBridgeTools({
    registerTool: (name: string, _config: unknown, callback: any) =>
      callbacks.set(name, callback),
  } as any);

  const profile1 = {
    directory: "Profile 1",
    name: "Other",
    userName: "other@example.com",
    gaiaName: null,
    gaiaId: "1",
    activeTime: 10,
  };
  const harry = {
    directory: "Profile 14",
    name: "HARRY",
    userName: "harry@example.com",
    gaiaName: "HARRY",
    gaiaId: "14",
    activeTime: 5,
  };

  const saved = {
    refresh: bridge.refresh,
    status: bridge.status,
    observed: bridge.observedExtensionProfiles,
    requestPair: bridge.requestPair,
    waitPair: bridge.waitForPairRequest,
    profiles: nativeChrome.profiles,
    running: nativeChrome.runningProfileDirectories,
    bridgeProfiles: nativeChrome.profilesWithZagentBridge,
    launch: nativeChrome.launchProfile,
  };

  let launchedProfile: string | null = null;
  let requestedProfile: any = null;

  (bridge as any).refresh = async () => true;
  (bridge as any).status = () => ({
    required: true,
    connected: false,
    authorized: false,
    profileBinding: null,
    pairingPending: null,
    reconnectAvailable: false,
  });
  (bridge as any).observedExtensionProfiles = () => [];
  (bridge as any).requestPair = (_seconds: number, profile: any) => {
    requestedProfile = profile;
    return { pairingPending: { id: "pair-test", profile } };
  };
  (bridge as any).waitForPairRequest = async () => ({
    outcome: "timed_out",
    waitedMs: 0,
  });

  (nativeChrome as any).profiles = async () => [profile1, harry];
  (nativeChrome as any).runningProfileDirectories = async () => [
    "Profile 1",
  ];
  (nativeChrome as any).profilesWithZagentBridge = async () => [
    {
      profile: harry,
      extensionIds: ["zagent-bridge"],
      extensionPaths: ["D:/Zagent/extension"],
      running: false,
    },
  ];
  (nativeChrome as any).launchProfile = async (selector: string) => {
    launchedProfile = selector;
    return { ok: true };
  };

  try {
    const result = await callbacks.get("web_bridge_pair")!({
      expiresInSeconds: 30,
    });
    const payload = JSON.parse(result.content[0].text);

    assert.equal(launchedProfile, "Profile 14");
    assert.equal(requestedProfile, null);
    assert.equal(payload.outcome, "extension_heartbeat_required");
    assert.equal(payload.pairingPending, null);
    assert.equal(payload.selectedProfile.directory, "Profile 14");
    assert.equal(payload.selectionSource, "installed-bridge-profile");
    assert.equal(payload.launchedChrome, true);
    // Mock runtime omits Web port; strict resolver intentionally returns unknown.
    assert.equal(payload.expectedBridgeEndpoint, "");
    assert.equal(payload.bridgeEnvironment, "DEVELOPMENT");
  } finally {
    (bridge as any).refresh = saved.refresh;
    (bridge as any).status = saved.status;
    (bridge as any).observedExtensionProfiles = saved.observed;
    (bridge as any).requestPair = saved.requestPair;
    (bridge as any).waitForPairRequest = saved.waitPair;
    (nativeChrome as any).profiles = saved.profiles;
    (nativeChrome as any).runningProfileDirectories = saved.running;
    (nativeChrome as any).profilesWithZagentBridge = saved.bridgeProfiles;
    (nativeChrome as any).launchProfile = saved.launch;
  }
});

test("pair request becomes actionable only after matching Bridge heartbeat is observed", async () => {
  const callbacks = new Map<string, (...args: any[]) => any>();
  registerBridgeTools({
    registerTool: (name: string, _config: unknown, callback: any) =>
      callbacks.set(name, callback),
  } as any);

  const harry = {
    directory: "Profile 14",
    name: "HARRY",
    userName: "harry@example.com",
    gaiaName: "HARRY",
    gaiaId: "14",
    activeTime: 5,
  };

  const saved = {
    refresh: bridge.refresh,
    status: bridge.status,
    observed: bridge.observedExtensionProfiles,
    requestPair: bridge.requestPair,
    waitPair: bridge.waitForPairRequest,
    profiles: nativeChrome.profiles,
    running: nativeChrome.runningProfileDirectories,
    bridgeProfiles: nativeChrome.profilesWithZagentBridge,
  };

  let requestedProfile: any = null;

  (bridge as any).refresh = async () => true;
  (bridge as any).status = () => ({
    required: true,
    connected: false,
    authorized: false,
    profileBinding: null,
    pairingPending: null,
    reconnectAvailable: false,
  });
  (bridge as any).observedExtensionProfiles = () => [{
    origin: "chrome-extension://bridge",
    email: "harry@example.com",
    gaiaId: "14",
    instanceFingerprint: "heartbeat-14",
    lastSeen: Date.now(),
  }];
  (bridge as any).requestPair = (_seconds: number, profile: any) => {
    requestedProfile = profile;
    return { pairingPending: { id: "pair-heartbeat", profile } };
  };
  (bridge as any).waitForPairRequest = async () => ({
    outcome: "timed_out",
    timedOut: true,
    waitedMs: 0,
  });

  (nativeChrome as any).profiles = async () => [harry];
  (nativeChrome as any).runningProfileDirectories = async () => ["Profile 14"];
  (nativeChrome as any).profilesWithZagentBridge = async () => [{
    profile: harry,
    extensionIds: ["zagent-bridge"],
    extensionPaths: ["D:/Zagent/extension"],
    running: true,
  }];

  try {
    const result = await callbacks.get("web_bridge_pair")!({
      expiresInSeconds: 30,
    });
    const payload = JSON.parse(result.content[0].text);

    assert.equal(requestedProfile.directory, "Profile 14");
    assert.equal(payload.selectedProfile.directory, "Profile 14");
    assert.equal(payload.selectionSource, "fresh-extension-heartbeat");
    assert.equal(payload.launchedChrome, false);
    assert.equal(payload.outcome, "timed_out");
  } finally {
    (bridge as any).refresh = saved.refresh;
    (bridge as any).status = saved.status;
    (bridge as any).observedExtensionProfiles = saved.observed;
    (bridge as any).requestPair = saved.requestPair;
    (bridge as any).waitForPairRequest = saved.waitPair;
    (nativeChrome as any).profiles = saved.profiles;
    (nativeChrome as any).runningProfileDirectories = saved.running;
    (nativeChrome as any).profilesWithZagentBridge = saved.bridgeProfiles;
  }
});

test("multiple profiles with installed Bridge return immediately without opening or waiting", async () => {
  const callbacks = new Map<string, (...args: any[]) => any>();
  registerBridgeTools({
    registerTool: (name: string, _config: unknown, callback: any) =>
      callbacks.set(name, callback),
  } as any);

  const one = {
    directory: "Profile 14",
    name: "HARRY",
    userName: "harry@example.com",
    gaiaName: "HARRY",
    gaiaId: "14",
    activeTime: 5,
  };
  const two = {
    directory: "Profile 15",
    name: "SECOND",
    userName: "second@example.com",
    gaiaName: "SECOND",
    gaiaId: "15",
    activeTime: 4,
  };

  const saved = {
    refresh: bridge.refresh,
    status: bridge.status,
    observed: bridge.observedExtensionProfiles,
    profiles: nativeChrome.profiles,
    running: nativeChrome.runningProfileDirectories,
    bridgeProfiles: nativeChrome.profilesWithZagentBridge,
    launch: nativeChrome.launchProfile,
  };

  let launchCount = 0;
  (bridge as any).refresh = async () => true;
  (bridge as any).status = () => ({
    required: true,
    connected: false,
    authorized: false,
    profileBinding: null,
    pairingPending: null,
  });
  (bridge as any).observedExtensionProfiles = () => [];
  (nativeChrome as any).profiles = async () => [one, two];
  (nativeChrome as any).runningProfileDirectories = async () => [];
  (nativeChrome as any).profilesWithZagentBridge = async () => [
    {
      profile: one,
      extensionIds: ["bridge-one"],
      extensionPaths: ["D:/Bridge/one"],
      running: false,
    },
    {
      profile: two,
      extensionIds: ["bridge-two"],
      extensionPaths: ["D:/Bridge/two"],
      running: false,
    },
  ];
  (nativeChrome as any).launchProfile = async () => {
    launchCount += 1;
    return { ok: true };
  };

  try {
    const started = Date.now();
    const result = await callbacks.get("web_bridge_pair")!({
      expiresInSeconds: 180,
    });
    const payload = JSON.parse(result.content[0].text);

    assert.equal(payload.outcome, "profile_selection_required");
    assert.equal(payload.reason, "multiple-installed-bridge-profiles");
    assert.equal(payload.candidates.length, 2);
    assert.equal(launchCount, 0);
    assert.ok(Date.now() - started < 1000);
  } finally {
    (bridge as any).refresh = saved.refresh;
    (bridge as any).status = saved.status;
    (bridge as any).observedExtensionProfiles = saved.observed;
    (nativeChrome as any).profiles = saved.profiles;
    (nativeChrome as any).runningProfileDirectories = saved.running;
    (nativeChrome as any).profilesWithZagentBridge = saved.bridgeProfiles;
    (nativeChrome as any).launchProfile = saved.launch;
  }
});

test("disconnect tool detaches native automation before clearing bridge trust", async () => {
  const callbacks = new Map<string, (...args: any[]) => any>();
  registerBridgeTools({
    registerTool: (name: string, _config: unknown, callback: any) =>
      callbacks.set(name, callback),
  } as any);

  const savedDetach = nativeChrome.detach;
  const savedDisconnect = bridge.disconnectTrusted;
  const savedNativeAttached = B.isNativeAttached;
  const calls: string[] = [];

  (nativeChrome as any).detach = async () => {
    calls.push("detach");
    return { ok: true, detached: true };
  };
  (bridge as any).disconnectTrusted = async () => {
    calls.push("disconnect");
    return { required: true, connected: false, authorized: false };
  };
  (B as any).isNativeAttached = () => false;

  try {
    const result = await callbacks.get("web_bridge_disconnect")!({});
    const payload = JSON.parse(result.content[0].text);
    assert.deepEqual(calls, ["detach", "disconnect"]);
    assert.equal(payload.connected, false);
    assert.equal(payload.nativeAttached, false);
  } finally {
    (nativeChrome as any).detach = savedDetach;
    (bridge as any).disconnectTrusted = savedDisconnect;
    (B as any).isNativeAttached = savedNativeAttached;
  }
});

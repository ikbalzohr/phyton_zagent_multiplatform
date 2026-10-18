import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("../extension/background.js", import.meta.url), "utf8");

const developmentBridgeConfig = {
  schemaVersion: 2,
  configured: true,
  environment: "DEVELOPMENT",
  defaultBase: "http://127.0.0.3:19030/bridge/",
  legacyBases: [
    "http://127.0.0.3:18830/bridge/",
    "http://127.0.0.1:18830/bridge/",
    "http://127.0.0.1:8021/bridge/"
  ]
};

function bridgeConfigResponse() {
  return {
    ok: true,
    status: 200,
    json: async () => developmentBridgeConfig
  };
}

function area(store) {
  return {
    get: async keys => {
      if (typeof keys === "string") return { [keys]: store[keys] };
      if (Array.isArray(keys)) return Object.fromEntries(keys.map(k => [k, store[k]]));
      return { ...store };
    },
    set: async obj => Object.assign(store, obj),
    remove: async key => {
      for (const k of Array.isArray(key) ? key : [key]) delete store[k];
    }
  };
}

test("MV3 worker sends a stable per-profile instance identity and account email", async () => {
  const session = {};
  const local = {};
  let listener;
  let alarm;
  let pendingPair = {
    id: "pair-1",
    expiresAt: Date.now() + 60000,
    profile: {
      directory: "Profile 14",
      name: "HARRY",
      userName: "harry.indrah3@gmail.com"
    }
  };
  let authorizationPending = null;
  const calls = [];

  const chrome = {
    runtime: {
      id: "a".repeat(32),
      getURL: p => "chrome-extension://" + "a".repeat(32) + "/" + p,
      onMessage: { addListener: fn => listener = fn },
      onStartup: { addListener() {} }
    },
    storage: {
      session: { ...area(session), setAccessLevel() {} },
      local: area(local)
    },
    identity: {
      getProfileUserInfo: async () => ({
        email: "harry.indrah3@gmail.com",
        id: "106327648390670158488"
      })
    },
    action: {
      setBadgeText: async () => {},
      setBadgeBackgroundColor: async () => {}
    },
    alarms: {
      create: async () => {},
      onAlarm: { addListener: fn => alarm = fn }
    },
    windows: {
      onCreated: { addListener() {} },
      onRemoved: { addListener() {} },
      getAll: async () => [{
        id: 10,
        type: "normal",
        focused: true,
        tabs: [{
          id: 1,
          url: "https://example.com",
          active: true,
          incognito: false
        }]
      }]
    },
    tabs: {
      onCreated: { addListener() {} },
      onRemoved: { addListener() {} },
      onUpdated: { addListener() {} },
      query: async () => {
        throw new Error("Legacy lastFocusedWindow selection must not be used.");
      }
    },
    debugger: {
      getTargets: async () => [{ type: "page", tabId: 1, id: "CDP-A" }]
    }
  };

  const fetch = async (url, opts = {}) => {
    if (url.endsWith("/bridge-config.json")) return bridgeConfigResponse();
    calls.push({ url, ...opts });
    const body = JSON.parse(opts.body || "{}");
    assert.equal(body.profileIdentity.email, "harry.indrah3@gmail.com");
    assert.equal(body.profileIdentity.gaiaId, "106327648390670158488");
    assert.equal(body.profileIdentity.instanceId, "11111111-2222-4333-8444-555555555555");

    if (url.endsWith("/handshake")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          paired: Boolean(local.reconnectSecret),
          pendingPair,
          pendingPairForDifferentProfile: false,
          profileMismatch: false,
          localProfile: {
            email: "harry.indrah3@gmail.com",
            instanceFingerprint: "fingerprint"
          },
          reconnectRequestedAt: null,
          required: true
        })
      };
    }
    if (url.endsWith("/pair-accept")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          token: "paired-token",
          reconnectSecret: "new-reconnect-secret",
          connected: true,
          authorized: false,
          profileBinding: pendingPair.profile
        })
      };
    }
    if (url.endsWith("/reconnect")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          token: "fresh-token",
          connected: true,
          authorized: false,
          profileBinding: pendingPair?.profile ?? null
        })
      };
    }
    if (url.endsWith("/status")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          connected: true,
          authorized: false,
          profileBinding: pendingPair?.profile ?? null,
          authorizationPending
        })
      };
    }
    if (url.endsWith("/lease")) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          connected: true,
          authorized: true,
          profileBinding: pendingPair?.profile ?? null,
          lease: { scope: "window", targets: [{ id: "CDP-A" }], expiresAt: Date.now() + 300000 }
        })
      };
    }
    if (url.endsWith("/revoke")) {
      return { ok: true, status: 200, json: async () => ({ connected: true, authorized: false }) };
    }
    if (url.endsWith("/disconnect")) {
      return { ok: true, status: 200, json: async () => ({ connected: false, authorized: false, profileBound: false }) };
    }
    throw new Error("Unexpected route " + url);
  };

  const crypto = { randomUUID: () => "11111111-2222-4333-8444-555555555555" };
  const settle = () => new Promise(r => setTimeout(r, 20));
  vm.runInNewContext(source, { chrome, fetch, AbortSignal, console, setTimeout, crypto });
  await settle();

  assert.equal(local.profileInstanceId, "11111111-2222-4333-8444-555555555555");
  assert.equal(local.zagentBridgeBase, "http://127.0.0.3:19030/bridge/");
  assert.equal(local.zagentBridgeEnvironment, "DEVELOPMENT");

  const send = message => new Promise(resolve =>
    listener(message, { id: chrome.runtime.id, url: chrome.runtime.getURL("popup.html") }, resolve)
  );

  const paired = await send({ action: "pair-request" });
  assert.equal(paired.connected, true);
  assert.equal(local.reconnectSecret, "new-reconnect-secret");
  assert.equal(session.token, "paired-token");

  pendingPair = null;
  authorizationPending = {
    id: "auth-1",
    scope: "window",
    seconds: 900,
    allowNavigation: true,
    allowNewTabs: true
  };
  await send({ action: "approve-request" });
  const leaseCall = calls.filter(c => c.url.endsWith("/lease")).at(-1);
  assert.equal(JSON.parse(leaseCall.body).requestId, "auth-1");

  await send({ action: "revoke" });
  assert.equal(local.reconnectSecret, "new-reconnect-secret");

  await send({ action: "disconnect" });
  assert.equal(local.reconnectSecret, undefined);
  assert.equal(session.token, undefined);
  assert.equal(local.profileInstanceId, "11111111-2222-4333-8444-555555555555");

  alarm();
  await settle();
});

test("profile mismatch is surfaced and does not expose a pairing button for another profile", async () => {
  const session = {};
  const local = { profileInstanceId: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee" };
  let listener;

  const chrome = {
    runtime: {
      id: "a".repeat(32),
      getURL: p => "chrome-extension://" + "a".repeat(32) + "/" + p,
      onMessage: { addListener: fn => listener = fn },
      onStartup: { addListener() {} }
    },
    storage: {
      session: { ...area(session), setAccessLevel() {} },
      local: area(local)
    },
    identity: {
      getProfileUserInfo: async () => ({
        email: "other.profile@gmail.com",
        id: "other"
      })
    },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
    alarms: { create: async () => {}, onAlarm: { addListener() {} } },
    windows: {
      onCreated: { addListener() {} }, onRemoved: { addListener() {} },
      getAll: async () => []
    },
    tabs: {
      query: async () => [], onCreated: { addListener() {} },
      onRemoved: { addListener() {} }, onUpdated: { addListener() {} }
    },
    debugger: { getTargets: async () => [] }
  };

  const fetch = async (url, opts = {}) => {
    if (url.endsWith("/bridge-config.json")) return bridgeConfigResponse();
    if (!url.endsWith("/handshake")) throw new Error("Unexpected route");
    return {
      ok: true,
      status: 200,
      json: async () => ({
        paired: false,
        profileMismatch: true,
        pendingPair: null,
        pendingPairForDifferentProfile: true,
        boundProfile: { name: "HARRY", directory: "Profile 14", userName: "harry.indrah3@gmail.com" },
        localProfile: { email: "other.profile@gmail.com" },
        required: true
      })
    };
  };

  vm.runInNewContext(source, {
    chrome,
    fetch,
    AbortSignal,
    console,
    setTimeout,
    crypto: { randomUUID: () => "unused-uuid-0000-0000-000000000000" }
  });

  await new Promise(r => setTimeout(r, 20));
  const send = message => new Promise(resolve =>
    listener(message, { id: chrome.runtime.id, url: chrome.runtime.getURL("popup.html") }, resolve)
  );
  const state = await send({ action: "status" });
  assert.equal(state.profileMismatch, true);
  assert.equal(state.pendingPair, null);
  assert.match(state.error, /trusted pairing belongs to HARRY/i);
});

const BRIDGE_CONFIG_FILE = "bridge-config.json";
let bridgeConfigPromise = null;

function normalizeBridgeBase(value) {
  let raw = String(value || "").trim();
  if (!raw.endsWith("/")) raw += "/";
  const match = /^http:\/\/(127\.0\.0\.1|127\.0\.0\.3|localhost):(\d{1,5})\/bridge\/$/i.exec(raw);
  const port = match ? Number(match[2]) : 0;
  if (!match || port < 1 || port > 65535) {
    throw new Error("Zagent Bridge endpoint must be a local loopback HTTP URL ending in /bridge/.");
  }
  return raw;
}

async function bridgeConfig() {
  if (!bridgeConfigPromise) {
    bridgeConfigPromise = fetch(chrome.runtime.getURL(BRIDGE_CONFIG_FILE), { cache: "no-store" })
      .then(async response => {
        if (!response.ok) throw new Error(`Bridge config returned ${response.status}`);
        const config = await response.json();
        const environment = String(config?.environment || "").trim().toUpperCase();
        if (!["DEVELOPMENT", "PRODUCTION"].includes(environment)) {
          throw new Error("Zagent Bridge environment must be DEVELOPMENT or PRODUCTION.");
        }
        if (config?.configured !== true) {
          throw new Error("Zagent Bridge is not configured for this installation yet. Run Zagent Setup/Repair or restart Zagent Manager.");
        }
        const defaultBase = normalizeBridgeBase(config?.defaultBase);
        const legacyBases = new Set(
          Array.isArray(config?.legacyBases)
            ? config.legacyBases.map(normalizeBridgeBase)
            : []
        );
        if (legacyBases.has(defaultBase)) {
          throw new Error("Zagent Bridge default endpoint cannot also be classified as legacy.");
        }
        return { environment, defaultBase, legacyBases };
      });
  }
  return bridgeConfigPromise;
}

async function bridgeBase() {
  const config = await bridgeConfig();
  const { zagentBridgeBase } = await chrome.storage.local.get("zagentBridgeBase");
  let raw = normalizeBridgeBase(zagentBridgeBase || config.defaultBase);
  if (config.legacyBases.has(raw)) {
    raw = config.defaultBase;
  }
  if (zagentBridgeBase !== raw) {
    await chrome.storage.local.set({
      zagentBridgeBase: raw,
      zagentBridgeEnvironment: config.environment
    });
  }
  return raw;
}

let controlTail = Promise.resolve();
let statusInFlight = null;

async function profileIdentity() {
  const stored = await chrome.storage.local.get("profileInstanceId");
  let instanceId = stored.profileInstanceId;
  if (!/^[A-Za-z0-9-]{16,128}$/.test(instanceId || "")) {
    instanceId = crypto.randomUUID();
    await chrome.storage.local.set({ profileInstanceId: instanceId });
  }

  let info = { email: "", id: "" };
  try {
    info = await chrome.identity.getProfileUserInfo({ accountStatus: "ANY" });
  } catch {}

  return {
    instanceId,
    email: String(info?.email || "").trim().toLowerCase(),
    gaiaId: String(info?.id || "").trim()
  };
}

async function request(route, body = {}, token) {
  const identity = await profileIdentity();
  const base = await bridgeBase();
  const response = await fetch(base + route, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ ...body, profileIdentity: identity }),
    signal: AbortSignal.timeout(15000),
    cache: "no-store",
    credentials: "omit",
    redirect: "error"
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || `Bridge returned ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

async function badge(state) {
  const text = state?.authorized ? "ON" : state?.connected ? "LOCK" : state?.pendingPair ? "PAIR" : "OFF";
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({
    color: state?.authorized ? "#16866c" : state?.pendingPair ? "#9a6700" : "#6b7280"
  });
}

async function save(state) {
  await chrome.storage.session.set({ state });
  await badge(state);
  return state;
}

async function reconnectIfPossible() {
  const { reconnectSecret } = await chrome.storage.local.get("reconnectSecret");
  if (!reconnectSecret) return null;
  const data = await request("reconnect", { secret: reconnectSecret });
  const token = data.token;
  if (!token) throw new Error("Reconnect did not return a session token");
  await chrome.storage.session.set({ token });
  delete data.token;
  return { token, state: data };
}

async function currentToken() {
  const { token } = await chrome.storage.session.get("token");
  if (token) return token;
  const reconnected = await reconnectIfPossible();
  return reconnected?.token || null;
}

async function authenticatedRequest(route, body = {}) {
  let token = await currentToken();
  if (!token) throw new Error("Pair this exact Chrome profile with Zagent Web to begin.");
  try {
    return await request(route, body, token);
  } catch (error) {
    if (error?.status !== 403) throw error;
    await chrome.storage.session.remove("token");
    const reconnected = await reconnectIfPossible();
    token = reconnected?.token || null;
    if (!token) throw error;
    return request(route, body, token);
  }
}

async function handshake() {
  return request("handshake", {});
}

async function pairFromPending(requestId, persistentConsent = false) {
  let id = String(requestId || "").trim();
  if (!id) {
    const hand = await handshake();
    if (hand.profileMismatch && !hand.pendingPair?.id) {
      throw new Error(`This Chrome profile does not match the trusted binding for ${hand.boundProfile?.name || "another profile"}.`);
    }
    if (!hand.pendingPair?.id) {
      if (hand.pendingPairForDifferentProfile) throw new Error("The current pairing request targets a different Chrome profile.");
      throw new Error("No active pairing request from Zagent Web for this Chrome profile.");
    }
    id = hand.pendingPair.id;
  }

  const data = await request("pair-accept", { requestId: id, ...(persistentConsent ? { consentMode: "persistent-all-tabs-v1" } : {}) });
  const token = data.token;
  const reconnectSecret = data.reconnectSecret;
  if (!token || !reconnectSecret) throw new Error("Pairing response incomplete");
  await chrome.storage.local.set({ reconnectSecret });
  await chrome.storage.session.set({ token });
  await chrome.storage.local.remove("pendingStop");
  delete data.token;
  delete data.reconnectSecret;
  if (data.lease?.persistent) {
    try {
      const targetIds = await selectedTargets("all");
      await authenticatedRequest("targets-sync", { targetIds });
    } catch (error) {
      data.warning = "Izin tersimpan; daftar tab belum sinkron: " + error.message;
    }
  }
  return data;
}

async function selectedTargets(scope) {
  if (!["tab", "window", "all"].includes(scope)) throw new Error("Choose a scope");

  const isEligibleTab = t => {
    if (t.incognito) return false;
    const url = String(t.url || "");
    return /^https?:\/\//.test(url) ||
      url === "about:blank" ||
      url.startsWith("chrome://newtab");
  };

  let tabs = [];

  if (scope === "all") {
    const windows = await chrome.windows.getAll({
      populate: true,
      windowTypes: ["normal"]
    });
    tabs = windows.flatMap(w => (w.tabs || []).filter(isEligibleTab));
  } else {
    const windows = await chrome.windows.getAll({
      populate: true,
      windowTypes: ["normal"]
    });

    const candidates = windows
      .map(w => ({
        window: w,
        tabs: (w.tabs || []).filter(isEligibleTab)
      }))
      .filter(x => x.tabs.length > 0);

    const preferred =
      candidates.find(x => x.window.focused) ||
      candidates.find(x => x.tabs.some(t => t.active)) ||
      candidates[0];

    if (!preferred) {
      throw new Error("No normal Chrome window with an eligible tab is available.");
    }

    if (scope === "tab") {
      const active =
        preferred.tabs.find(t => t.active) ||
        preferred.tabs[0];
      tabs = active ? [active] : [];
    } else {
      tabs = preferred.tabs;
    }
  }

  const ids = new Set(tabs.map(t => t.id));
  const targets = (await chrome.debugger.getTargets()).filter(
    t => t.type === "page" && ids.has(t.tabId)
  );

  if (scope !== "all" && (!targets.length || targets.length !== tabs.length)) {
    throw new Error("Some selected tabs have no CDP identity. Choose another scope or retry.");
  }

  return targets.map(t => t.id);
}

async function grantLease({ scope, seconds, allowNavigation = false, allowNewTabs = false, requestId }) {
  const targetIds = await selectedTargets(scope);
  const data = await authenticatedRequest("lease", {
    scope,
    seconds,
    targetIds,
    allowNavigation,
    allowNewTabs,
    ...(requestId ? { requestId } : {})
  });
  if (data.lease?.expiresAt) {
    await chrome.alarms.create("expiry", { when: data.lease.expiresAt });
  } else {
    await chrome.alarms.clear("expiry");
  }
  return data;
}

async function currentStatus() {
  const hand = await handshake().catch(() => null);
  if (!hand) throw new Error("Zagent Web bridge is offline.");

  const { reconnectSecret } = await chrome.storage.local.get("reconnectSecret");
  let { token } = await chrome.storage.session.get("token");

  if (hand.profileMismatch) {
    await chrome.storage.session.remove("token");
    return save({
      connected: false,
      authorized: false,
      paired: false,
      profileMismatch: true,
      boundProfile: hand.boundProfile || null,
      localProfile: hand.localProfile || null,
      pendingPair: hand.pendingPair || null,
      pendingPairForDifferentProfile: Boolean(hand.pendingPairForDifferentProfile),
      required: Boolean(hand.required),
      error: `Trusted pairing belongs to ${hand.boundProfile?.name || "another Chrome profile"}.`
    });
  }

  if (reconnectSecret && hand.paired && (!token || hand.reconnectRequestedAt)) {
    try {
      const reconnected = await reconnectIfPossible();
      token = reconnected?.token || token;
    } catch {}
  }

  if (!token) {
    return save({
      connected: false,
      authorized: false,
      pendingPair: hand.pendingPair || null,
      pendingPairForDifferentProfile: Boolean(hand.pendingPairForDifferentProfile),
      paired: Boolean(hand.paired),
      boundProfile: hand.boundProfile || null,
      localProfile: hand.localProfile || null,
      required: Boolean(hand.required),
      reconnectAvailable: Boolean(reconnectSecret && hand.paired)
    });
  }

  try {
    let data = await authenticatedRequest("status");
    if (data.authorized && data.lease?.persistent) {
      try {
        data = await authenticatedRequest("targets-sync", {
          targetIds: await selectedTargets("all")
        });
      } catch (error) {
        data.warning = "Menunggu sinkronisasi tab profil ini: " + error.message;
      }
    }
    return save({
      ...data,
      pendingPair: hand.pendingPair || null,
      pendingPairForDifferentProfile: Boolean(hand.pendingPairForDifferentProfile),
      localProfile: hand.localProfile || null
    });
  } catch (error) {
    return save({
      connected: false,
      authorized: false,
      pendingPair: hand.pendingPair || null,
      pendingPairForDifferentProfile: Boolean(hand.pendingPairForDifferentProfile),
      paired: Boolean(hand.paired),
      boundProfile: hand.boundProfile || null,
      localProfile: hand.localProfile || null,
      error: String(error.message)
    });
  }
}

async function act(message) {
  if (message.action === "approve") {
    const hand = await handshake();
    if (hand.pendingPair?.id) return save(await pairFromPending(hand.pendingPair.id, true));
    const current = await currentStatus();
    if (current.authorized && current.lease?.persistent) return current;
    if (current.connected && !current.profileMismatch) {
      const upgraded = await authenticatedRequest("consent-upgrade");
      try {
        await authenticatedRequest("targets-sync", {
          targetIds: await selectedTargets("all")
        });
      } catch (error) {
        upgraded.warning = "Izin tersimpan; sinkronisasi tab tertunda: " + error.message;
      }
      return save(upgraded);
    }
    throw new Error("Menunggu satu permintaan akses Zagent untuk profil Chrome ini.");
  }
  if (message.action === "pair-request") {
    return save(await pairFromPending(message.requestId));
  }

  if (message.action === "pair") {
    const data = await request("pair", { code: message.code });
    const token = data.token;
    const reconnectSecret = data.reconnectSecret;
    if (!token || !reconnectSecret) throw new Error("Pairing response incomplete");
    await chrome.storage.local.set({ reconnectSecret });
    await chrome.storage.session.set({ token });
    await chrome.storage.local.remove("pendingStop");
    delete data.token;
    delete data.reconnectSecret;
    return save(data);
  }

  const { pendingStop } = await chrome.storage.local.get("pendingStop");
  if (pendingStop) {
    await authenticatedRequest(pendingStop);
    await chrome.storage.local.remove("pendingStop");
    if (pendingStop === "disconnect") {
      await chrome.storage.session.remove("token");
      await chrome.storage.local.remove("reconnectSecret");
      return save({ connected: false, authorized: false });
    }
  }

  if (message.action === "revoke" || message.action === "disconnect") {
    await chrome.storage.local.set({ pendingStop: message.action });
    const data = await authenticatedRequest(message.action);
    await chrome.storage.local.remove("pendingStop");
    if (message.action === "disconnect") {
      await chrome.storage.session.remove("token");
      await chrome.storage.local.remove("reconnectSecret");
    }
    return save(data);
  }

  if (message.action === "approve-request") {
    if (message.requestId) {
      return save(await grantLease({
        scope: message.scope,
        seconds: message.seconds,
        allowNavigation: Boolean(message.allowNavigation),
        allowNewTabs: Boolean(message.allowNewTabs),
        requestId: message.requestId
      }));
    }
    const status = await authenticatedRequest("status");
    const pending = status.authorizationPending;
    if (!pending?.id) throw new Error("No active authorization request from Zagent Web.");
    return save(await grantLease({
      scope: pending.scope,
      seconds: pending.seconds,
      allowNavigation: Boolean(pending.allowNavigation),
      allowNewTabs: Boolean(pending.allowNewTabs),
      requestId: pending.id
    }));
  }

  if (message.action === "grant") {
    return save(await grantLease({
      scope: message.scope,
      seconds: message.seconds,
      allowNavigation: Boolean(message.allowNavigation),
      allowNewTabs: Boolean(message.allowNewTabs)
    }));
  }

  if (message.action !== "status") throw new Error("Unknown action");
  return currentStatus();
}

async function recoverActionError(error) {
  const { pendingStop } = await chrome.storage.local.get("pendingStop");
  const hand = await handshake().catch(() => null);
  return save({
    connected: false,
    authorized: false,
    pendingPair: hand?.pendingPair || null,
    pendingPairForDifferentProfile: Boolean(hand?.pendingPairForDifferentProfile),
    profileMismatch: Boolean(hand?.profileMismatch),
    boundProfile: hand?.boundProfile || null,
    localProfile: hand?.localProfile || null,
    error: String(error.message),
    pendingStop: Boolean(pendingStop),
    warning: pendingStop
      ? "Stop not confirmed. Retrying; server blocks access after at most 90 seconds without heartbeat."
      : undefined
  });
}

function enqueue(message) {
  if (message.action === "status") {
    if (statusInFlight) return statusInFlight;
    statusInFlight = act(message)
      .catch(recoverActionError)
      .finally(() => { statusInFlight = null; });
    return statusInFlight;
  }

  const job = controlTail
    .then(() => act(message))
    .catch(recoverActionError);
  controlTail = job.then(() => undefined, () => undefined);
  return job;
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL("popup.html")) return false;
  enqueue(message).then(respond);
  return true;
});

chrome.alarms.onAlarm.addListener(() => { void enqueue({ action: "status" }); });
chrome.runtime.onStartup.addListener(() => { void enqueue({ action: "status" }); });
// New tabs/windows in this extension profile acquire access under the
// previously approved durable consent, without another user prompt.
let syncTimer;
function scheduleTargetSync() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => { void enqueue({ action: "status" }); }, 600);
}
chrome.tabs.onCreated.addListener(scheduleTargetSync);
chrome.tabs.onRemoved.addListener(scheduleTargetSync);
chrome.tabs.onUpdated.addListener(scheduleTargetSync);
chrome.windows.onCreated.addListener(scheduleTargetSync);
chrome.windows.onRemoved.addListener(scheduleTargetSync);
chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
chrome.alarms.create("heartbeat", { periodInMinutes: 0.5 });
void enqueue({ action: "status" });
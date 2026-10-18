import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { createServer, request } from "node:http";
import { Bridge } from "../src/bridge/Bridge.js";

const origin = "chrome-extension://" + "a".repeat(32);
const target = { id: "A", windowId: 1, origin: "https://example.com" };
const profile = {
  directory: "Profile 14",
  name: "HARRY",
  userName: "harry.indrah3@gmail.com",
  gaiaId: "106327648390670158488",
};
const identity = {
  instanceId: "harry-profile-instance-0001",
  email: "harry.indrah3@gmail.com",
  gaiaId: "106327648390670158488",
};
const otherIdentity = {
  instanceId: "ban-profile-instance-0000001",
  email: "buolanekatambangnawasena@gmail.com",
  gaiaId: "other-gaia-id",
};

async function fixture() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "zagent-bridge-"));
  const file = path.join(dir, "bridge.json");
  let now = Date.now();
  await fs.writeFile(file, JSON.stringify({
    required: true,
    pairingHash: createHash("sha256").update("secret").digest("hex"),
    pairingExpiresAt: now + 300000,
  }));
  const bridge = new Bridge(file, () => now);
  return {
    bridge,
    file,
    advance: (ms: number) => { now += ms; },
    clean: () => fs.rm(dir, { recursive: true, force: true }),
  };
}

test("profile-bound pairing, reconnect, expiry and revoke lifecycle", async () => {
  const f = await fixture();
  try {
    const b = f.bridge;
    const requestState = b.requestPair(60, profile);
    const pairId = requestState.pairingPending?.id;
    assert.equal(typeof pairId, "string");

    await assert.rejects(b.acceptPairRequest(pairId!, origin, otherIdentity), /profile mismatch/i);
    const paired = await b.acceptPairRequest(pairId!, origin, identity);
    const token = paired.token;
    const reconnectSecret = paired.reconnectSecret;

    assert.equal(b.status().profileBound, true);
    assert.equal(b.status().profileBinding?.name, "HARRY");
    assert.equal(b.status().profileBinding?.userName, "harry.indrah3@gmail.com");
    assert.equal(b.status().profileBinding?.verifiedBy, "chrome_identity_email+profile_instance");
    assert.equal(b.status().reconnectAvailable, true);

    assert.throws(() => b.authenticate(token, origin, otherIdentity), /does not belong/i);
    b.authenticate(token, origin, identity);

    b.grant("tab", [target], 900);
    b.assertTarget(target);
    for (const changed of [
      { ...target, id: "B" },
      { ...target, windowId: 2 },
      { ...target, origin: "https://other.test" },
    ]) assert.throws(() => b.assertTarget(changed));

    f.advance(900000);
    assert.throws(() => b.assertTarget(target));

    b.authenticate(token, origin, identity);
    b.grant("window", [target, { ...target, id: "B" }], 900);
    assert.throws(() => b.grant("window", [target, { ...target, id: "C", windowId: 2 }], 900));
    assert.throws(() => b.grant("tab", [target, { ...target, id: "B" }], 900));

    const restarted = new Bridge(f.file);
    assert.equal(await restarted.refresh(), true);
    assert.equal(restarted.status().authorized, false);
    assert.equal(restarted.status().profileBinding?.name, "HARRY");
    await assert.rejects(restarted.reconnect(reconnectSecret, origin, otherIdentity), /different Chrome profile/i);

    const reconnected = await restarted.reconnect(reconnectSecret, origin, identity);
    assert.equal(reconnected.connected, true);
    restarted.authenticate(reconnected.token, origin, identity);

    const disconnected = await restarted.disconnectTrusted();
    assert.equal(disconnected.connected, false);
    assert.equal(disconnected.profileBound, false);
    assert.equal(disconnected.reconnectAvailable, false);
    await assert.rejects(restarted.reconnect(reconnectSecret, origin, identity));
  } finally {
    await f.clean();
  }
});

test("unlimited authorization lease has no expiry and revokes explicitly", async () => {
  const f = await fixture();
  try {
    const b = f.bridge;
    const pairState = b.requestPair(60, profile);
    const paired = await b.acceptPairRequest(
      pairState.pairingPending!.id,
      origin,
      identity,
    );

    b.authenticate(paired.token, origin, identity);
    const granted = b.grant("tab", [target], 0);

    assert.equal(granted.authorized, true);
    assert.equal(granted.lease?.expiresAt, null);
    b.assertTarget(target);

    const revoked = b.revoke(false);
    assert.equal(revoked.authorized, false);
    assert.equal(revoked.lease, null);
  } finally {
    await f.clean();
  }
});

test("handshake hides a HARRY pairing request from a different Chrome profile", async () => {
  const f = await fixture();
  try {
    const b = f.bridge;
    b.requestPair(60, profile);

    const right = b.handshake(origin, identity);
    assert.equal(right.pendingPair?.profile.name, "HARRY");
    assert.equal(right.pendingPairForDifferentProfile, false);

    const wrong = b.handshake(origin, otherIdentity);
    assert.equal(wrong.pendingPair, null);
    assert.equal(wrong.pendingPairForDifferentProfile, true);
  } finally {
    await f.clean();
  }
});

test("HTTP bridge requires profile identity and blocks cross-profile reconnect", async () => {
  const f = await fixture();
  const b = f.bridge;
  const server = createServer((req, res) => void b.handle(
    req,
    res,
    async ids => {
      if (ids.length !== 1 || ids[0] !== "A") throw new Error("Unknown target");
      return [target];
    },
    () => true,
  ));
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as any).port;

  const call = (
    route: string,
    body: any = {},
    headers: Record<string, string> = {},
    method = "POST",
    profileIdentity = identity,
  ) => new Promise<any>((resolve, reject) => {
    const req = request({
      hostname: "127.0.0.1",
      port,
      path: "/bridge/" + route,
      method,
      headers: { Origin: origin, "Content-Type": "application/json", ...headers },
    }, res => {
      let data = "";
      res.on("data", chunk => data += chunk);
      res.on("end", () => resolve({
        code: res.statusCode,
        data: data ? JSON.parse(data) : null,
        headers: res.headers,
      }));
    });
    req.on("error", reject);
    const payload = typeof body === "string"
      ? body
      : JSON.stringify({ ...body, profileIdentity });
    req.end(method === "OPTIONS" ? undefined : payload);
  });

  try {
    assert.equal((await call("pair", {}, { Origin: "https://evil.test" })).code, 403);
    assert.equal((await call("pair", {}, { Host: "evil.test:" + port })).code, 403);
    assert.equal((await call("pair", {}, {}, "OPTIONS")).code, 204);
    assert.equal((await call("pair", {}, { "Content-Type": "text/plain" })).code, 415);
    assert.equal((await call("handshake", { profileIdentity: undefined }, {}, "POST", {} as any)).code, 403);

    b.requestPair(60, profile);
    const hand = await call("handshake");
    assert.equal(hand.code, 200);
    assert.equal(hand.data.pendingPair.profile.name, "HARRY");

    const paired = await call("pair-accept", { requestId: hand.data.pendingPair.id });
    assert.equal(paired.code, 200);
    assert.equal(typeof paired.data.reconnectSecret, "string");
    assert.equal(paired.data.profileBinding.name, "HARRY");
    const auth = { Authorization: "Bearer " + paired.data.token };

    assert.equal((await call("status", {}, auth)).data.nativeAttached, true);
    assert.equal((await call("status", {}, auth, "POST", otherIdentity)).code, 403);

    const grant = await call("lease", { scope: "tab", seconds: 900, targetIds: ["A"] }, auth);
    assert.equal(grant.code, 200);
    assert.equal(grant.data.authorized, true);

    const wrongReconnect = await call(
      "reconnect",
      { secret: paired.data.reconnectSecret },
      {},
      "POST",
      otherIdentity,
    );
    assert.equal(wrongReconnect.code, 403);

    const reconnected = await call("reconnect", { secret: paired.data.reconnectSecret });
    assert.equal(reconnected.code, 200);
    const auth2 = { Authorization: "Bearer " + reconnected.data.token };
    assert.equal((await call("status", {}, auth2)).code, 200);

    assert.equal((await call("disconnect", {}, auth2)).data.profileBound, false);
  } finally {
    await new Promise<void>(r => server.close(() => r()));
    await f.clean();
  }
});

test("authorization requests remain explicit after profile binding", async () => {
  const f = await fixture();
  try {
    const b = f.bridge;
    const pairState = b.requestPair(60, profile);
    const paired = await b.acceptPairRequest(pairState.pairingPending!.id, origin, identity);
    assert.equal(paired.connected, true);

    const requested = b.requestAuthorization("window", 900, true, true, 60);
    const auth = requested.authorizationPending!;
    assert.equal(auth.scope, "window");

    const granted = b.grant("window", [target], 900, { requestId: auth.id });
    assert.equal(granted.authorized, true);
    assert.equal(granted.lease?.allowNavigation, true);
    assert.equal(granted.lease?.allowNewTabs, true);

    const changedOrigin = { ...target, origin: "https://mail.google.com" };
    b.assertNavigation(target, changedOrigin.origin);
    b.commitNavigation(target, changedOrigin.origin);
    b.assertTarget(changedOrigin);
    b.assertNewTab(changedOrigin);
    b.enrollNewTarget(changedOrigin, { id: "B", windowId: 1, origin: "https://accounts.google.com" });
    assert.equal(b.status().lease?.targets.length, 2);
  } finally {
    await f.clean();
  }
});

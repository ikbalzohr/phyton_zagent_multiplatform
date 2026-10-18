import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Bridge } from "../src/bridge/Bridge.js";

const origin = "chrome-extension://" + "a".repeat(32);
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
const target = { id: "A", windowId: 1, origin: "https://example.com" };

async function fixture() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "zagent-bridge-wait-"));
  const file = path.join(dir, "bridge.json");
  await fs.writeFile(file, JSON.stringify({ required: true }));
  const bridge = new Bridge(file);
  return {
    bridge,
    clean: () => fs.rm(dir, { recursive: true, force: true }),
  };
}

test("pair wait completes immediately after user accepts, without a second chat turn", async () => {
  const f = await fixture();
  try {
    const requested = f.bridge.requestPair(30, profile);
    const id = requested.pairingPending!.id;
    const accept = new Promise<void>((resolve, reject) => {
      setTimeout(() => {
        void f.bridge.acceptPairRequest(id, origin, identity).then(() => resolve(), reject);
      }, 40);
    });

    const result = await f.bridge.waitForPairRequest(id, 1);
    await accept;
    assert.equal(result.ok, true);
    assert.equal(result.outcome, "paired");
    assert.equal(result.timedOut, false);
    assert.equal(result.profileBound, true);
    assert.equal(result.connected, true);
  } finally {
    await f.clean();
  }
});

test("pair wait timeout cancels pending request and returns a normal successful result", async () => {
  const f = await fixture();
  try {
    const requested = f.bridge.requestPair(30, profile);
    const id = requested.pairingPending!.id;
    const result = await f.bridge.waitForPairRequest(id, 0.05);
    assert.equal(result.ok, true);
    assert.equal(result.outcome, "timed_out");
    assert.equal(result.timedOut, true);
    assert.equal(result.cancelled, true);
    assert.equal(result.pairingPending, null);
  } finally {
    await f.clean();
  }
});

test("authorization wait completes after approval without a second chat turn", async () => {
  const f = await fixture();
  try {
    const pair = f.bridge.requestPair(30, profile);
    await f.bridge.acceptPairRequest(pair.pairingPending!.id, origin, identity);

    const requested = f.bridge.requestAuthorization("window", 900, true, true, 30);
    const id = requested.authorizationPending!.id;
    const approve = new Promise<void>((resolve, reject) => {
      setTimeout(() => {
        try {
          f.bridge.grant("window", [target], 900, { requestId: id });
          resolve();
        } catch (error) {
          reject(error);
        }
      }, 40);
    });

    const result = await f.bridge.waitForAuthorizationRequest(id, 1);
    await approve;
    assert.equal(result.ok, true);
    assert.equal(result.outcome, "approved");
    assert.equal(result.timedOut, false);
    assert.equal(result.authorized, true);
    assert.equal(result.authorizationPending, null);
  } finally {
    await f.clean();
  }
});

test("authorization wait timeout cancels request and returns Worked-style normal result", async () => {
  const f = await fixture();
  try {
    const pair = f.bridge.requestPair(30, profile);
    await f.bridge.acceptPairRequest(pair.pairingPending!.id, origin, identity);

    const requested = f.bridge.requestAuthorization("window", 900, true, true, 30);
    const id = requested.authorizationPending!.id;
    const result = await f.bridge.waitForAuthorizationRequest(id, 0.05);
    assert.equal(result.ok, true);
    assert.equal(result.outcome, "timed_out");
    assert.equal(result.timedOut, true);
    assert.equal(result.cancelled, true);
    assert.equal(result.authorizationPending, null);
    assert.equal(result.authorized, false);
  } finally {
    await f.clean();
  }
});

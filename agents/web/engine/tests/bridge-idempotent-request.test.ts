import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Bridge } from "../src/bridge/Bridge.js";

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
const origin = "chrome-extension://" + "a".repeat(32);

async function fixture() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "zagent-idempotent-"));
  const file = path.join(dir, "bridge.json");
  await fs.writeFile(file, JSON.stringify({ required: true }));
  return {
    bridge: new Bridge(file),
    clean: () => fs.rm(dir, { recursive: true, force: true }),
  };
}

test("duplicate pair request for same profile reuses the same request id", async () => {
  const f = await fixture();
  try {
    const first = f.bridge.requestPair(180, profile);
    const second = f.bridge.requestPair(180, profile);
    assert.equal(first.pairingPending?.id, second.pairingPending?.id);
  } finally {
    await f.clean();
  }
});

test("pair request for a different profile cannot replace an active request", async () => {
  const f = await fixture();
  try {
    const first = f.bridge.requestPair(180, profile);
    assert.throws(() => f.bridge.requestPair(180, {
      directory: "Profile 13",
      name: "BAN",
      userName: "buolanekatambangnawasena@gmail.com",
      gaiaId: "ban-gaia",
    }), /already active/i);
    assert.equal(f.bridge.pairStatus().pairingPending?.id, first.pairingPending?.id);
  } finally {
    await f.clean();
  }
});

test("duplicate authorization request reuses the same request id", async () => {
  const f = await fixture();
  try {
    const pair = f.bridge.requestPair(180, profile);
    await f.bridge.acceptPairRequest(pair.pairingPending!.id, origin, identity);
    const first = f.bridge.requestAuthorization("window", 900, true, true, 180);
    const second = f.bridge.requestAuthorization("window", 900, true, true, 180);
    assert.equal(first.authorizationPending?.id, second.authorizationPending?.id);
  } finally {
    await f.clean();
  }
});

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Bridge } from "../src/bridge/Bridge.js";

const origin = "chrome-extension://" + "a".repeat(32);
const profile = { directory: "Profile 14", name: "HARRY", userName: "harry@example.test", gaiaId: "g14" };
const identity = { instanceId: "harry-local-instance-123456", email: "harry@example.test", gaiaId: "g14" };
const other = { instanceId: "fazrin-local-instance-123456", email: "fazrin@example.test", gaiaId: "g03" };
const targetA = { id: "target-a", windowId: 10, origin: "https://example.org" };
const targetB = { id: "target-b", windowId: 11, origin: "https://youtube.com" };

async function fixture() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "zagent-persistent-"));
  const file = path.join(dir, "bridge.json");
  await fs.writeFile(file, JSON.stringify({ required: true }));
  const bridge = new Bridge(file);
  const pending = bridge.requestPair(60, profile);
  const id = pending.pairingPending!.id;
  return { bridge, id, file, clean: () => fs.rm(dir, {recursive:true,force:true}) };
}

test("explicit extension Approve creates permanent single-profile all-tab grant", async () => {
  const f = await fixture();
  try {
    const b = f.bridge;
    const approved = await b.acceptPairRequest(f.id, origin, identity, "persistent-all-tabs-v1");
    assert.equal(approved.connected, true);
    assert.equal(approved.authorized, true);
    assert.equal(approved.lease?.persistent, true);
    assert.equal(approved.lease?.scope, "all");
    assert.equal(approved.lease?.expiresAt, null);
    assert.equal(approved.persistentConsent, true);
    assert.equal(approved.profileBinding?.directory, "Profile 14");
    assert.equal(approved.approvedTabCount, 0);
    assert.throws(() => b.assertTarget(targetA), /authorization/i);
    assert.throws(() => b.syncTargets(["bad target with spaces"]), /invalid/i);
    b.syncTargets(["target-a", "target-b"]);
    b.assertTarget(targetA);
    b.assertTarget(targetB);
    assert.throws(() => b.assertTarget({ ...targetA, id: "other-profile-tab" }), /authorization/i);
    b.assertNavigation(targetA, "https://google.com");
    b.commitNavigation(targetA, "https://google.com");
    b.assertNewTab(targetA);
    b.enrollNewTarget(targetA, {id:"target-c",windowId:12,origin:"https://example.com"});
    assert.throws(() => b.assertTarget({id:"target-c",windowId:12,origin:"https://example.com"}));
    b.syncTargets(["target-b"]);
    assert.throws(() => b.assertTarget(targetA));
    b.assertTarget(targetB);
  } finally { await f.clean(); }
});

test("old Pair does not silently grant persistent access; explicit upgrade is required", async () => {
  const f = await fixture();
  try {
    const b = f.bridge;
    const pair = await b.acceptPairRequest(f.id, origin, identity);
    assert.equal(pair.persistentConsent, false);
    assert.equal(pair.authorized, false);
    await assert.rejects(async () => b.syncTargets(["target-a"]), /approval/i);
    const upgraded = await b.upgradeConsent();
    assert.equal(upgraded.authorized, true);
    assert.equal(upgraded.lease?.persistent, true);
    b.syncTargets(["target-a"]);
    b.assertTarget(targetA);
  } finally { await f.clean(); }
});

test("reconnect restores persistent consent, but requires exact extension instance", async () => {
  const f = await fixture();
  try {
    const b = f.bridge;
    const paired = await b.acceptPairRequest(f.id, origin, identity, "persistent-all-tabs-v1");
    b.syncTargets(["target-a"]);
    const resumed = new Bridge(f.file);
    await resumed.refresh();
    assert.equal(resumed.status().authorized, false);
    await assert.rejects(() => resumed.reconnect(paired.reconnectSecret, origin, other), /different Chrome profile/i);
    const reconnected = await resumed.reconnect(paired.reconnectSecret, origin, identity);
    assert.equal(reconnected.authorized, true);
    assert.equal(reconnected.lease?.persistent, true);
    assert.throws(() => resumed.assertTarget(targetA), /authorization/i);
    resumed.syncTargets(["target-b"]);
    resumed.assertTarget(targetB);
    const rev = resumed.revoke();
    assert.equal(rev.authorized, true, "temporary revoke does not erase durable user consent");
    const off = await resumed.disconnectTrusted();
    assert.equal(off.connected, false);
    assert.equal(off.authorized, false);
    assert.equal(off.persistentConsent, false);
    assert.equal(off.profileBound, false);
    assert.equal(off.approvedTabCount, 0);
    assert.equal(off.reconnectAvailable, false);
    await assert.rejects(() => resumed.reconnect(paired.reconnectSecret, origin, identity));
  } finally { await f.clean(); }
});

test("extension has no legacy Pair/Authorize button; only Approve/Disconnect UI", async () => {
  const ext = new URL("../extension/", import.meta.url);
  const html = await fs.readFile(new URL("popup.html", ext), "utf8");
  const script = await fs.readFile(new URL("background.js", ext), "utf8");
  assert.match(html, /id="approve"/);
  assert.match(html, /id="disconnect"/);
  assert.doesNotMatch(html, /id="pair"|id="authorize"/);
  assert.match(script, /persistent-all-tabs-v1/);
  assert.match(script, /targets-sync/);
  assert.match(script, /chrome\.tabs\.onCreated/);
});

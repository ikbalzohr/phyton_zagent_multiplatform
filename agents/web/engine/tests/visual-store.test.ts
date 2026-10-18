import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { VisualArtifactStore } from "../src/visual/VisualArtifactStore.js";

test("visual artifact store preserves provenance, latest/list, and retention", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "zagent-visual-"));
  const source = path.join(root, "source.png");
  const oldDeviceId = process.env.ZAGENT_DEVICE_ID;
  const oldDeviceName = process.env.ZAGENT_DEVICE_NAME;
  try {
    process.env.ZAGENT_DEVICE_ID = "device-test-123";
    process.env.ZAGENT_DEVICE_NAME = "Visual Test Device";
    await fs.writeFile(source, Buffer.from("zagent-visual-test"));

    const store = new VisualArtifactStore(path.join(root, "store"));
    const first = await store.publish({
      path: source,
      source: "web",
      kind: "test-snapshot",
      sessionId: "session-test-1",
      requestId: "request-test-1",
      traceId: "trace-test-1",
      metadata: { purpose: "regression" },
    });

    assert.equal(first.provenance.deviceId, "device-test-123");
    assert.equal(first.provenance.deviceName, "Visual Test Device");
    assert.equal(first.provenance.sessionId, "session-test-1");
    assert.equal(first.provenance.requestId, "request-test-1");
    assert.equal(first.provenance.traceId, "trace-test-1");
    assert.equal(first.source, "web");
    assert.equal(first.kind, "test-snapshot");
    assert.match(first.sha256, /^[a-f0-9]{64}$/);
    assert.equal(await fs.readFile(first.artifactPath, "utf8"), "zagent-visual-test");

    const latest = await store.latest();
    assert.equal(latest?.id, first.id);
    assert.equal((await store.list({ source: "web", limit: 10 })).length, 1);

    const second = await store.publish({
      path: source,
      source: "arcmap",
      kind: "layout-snapshot",
      sessionId: "session-test-2",
    });

    assert.equal((await store.latest())?.id, second.id);
    assert.equal((await store.latest("web"))?.id, first.id);

    const pruned = await store.prune({ maxArtifacts: 1 });
    assert.equal(pruned.removed, 1);
    assert.equal(pruned.retained, 1);
    assert.equal((await store.list({ limit: 10 })).length, 1);
    assert.equal((await store.latest())?.id, second.id);
  } finally {
    if (oldDeviceId === undefined) delete process.env.ZAGENT_DEVICE_ID;
    else process.env.ZAGENT_DEVICE_ID = oldDeviceId;
    if (oldDeviceName === undefined) delete process.env.ZAGENT_DEVICE_NAME;
    else process.env.ZAGENT_DEVICE_NAME = oldDeviceName;
    await fs.rm(root, { recursive: true, force: true });
  }
});

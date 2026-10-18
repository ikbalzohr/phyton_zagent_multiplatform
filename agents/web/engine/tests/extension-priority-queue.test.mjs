import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

test("Chrome Bridge control actions are not serialized behind status polling", async () => {
  const source = await fs.readFile(new URL("../extension/background.js", import.meta.url), "utf8");
  assert.match(source, /let controlTail = Promise\.resolve\(\);/);
  assert.match(source, /let statusInFlight = null;/);
  assert.match(source, /if \(message\.action === "status"\)/);
  assert.match(source, /if \(statusInFlight\) return statusInFlight;/);
  assert.match(source, /const job = controlTail/);
  assert.doesNotMatch(source, /let tail = Promise\.resolve\(\);/);
});

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

test("Chrome Bridge popup uses only Approve and Disconnect, auto-polls every 1500ms", async () => {
  const js = await fs.readFile(new URL("../extension/popup.js", import.meta.url), "utf8");
  const html = await fs.readFile(new URL("../extension/popup.html", import.meta.url), "utf8");
  assert.match(js, /async function poll\(\)/);
  assert.match(js, /chrome\.runtime\.sendMessage\(\{ action: "status" \}\)/);
  assert.match(js, /setInterval\(\(\) => void poll\(\), 1500\)/);
  assert.match(html, /id="approve"/);
  assert.match(html, /id="disconnect"/);
  assert.doesNotMatch(html, /id="pair"|id="authorize"/);
  assert.match(js, /lease\?\.persistent/);
});

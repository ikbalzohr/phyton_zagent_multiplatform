import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

test("pair-accept HTTP path bypasses general bridge serial queue", async () => {
  const source = await fs.readFile(new URL("../src/bridge/Bridge.ts", import.meta.url), "utf8");
  assert.match(
    source,
    /route === "\/bridge\/pair-accept"[\s\S]{0,600}reply\(200, await this\.acceptPairRequest\(/,
  );
  assert.doesNotMatch(
    source,
    /route === "\/bridge\/pair-accept"[\s\S]{0,600}this\.serial\(\(\) => this\.acceptPairRequest/,
  );
  assert.match(source, /pair_accept_body_parsed/);
});

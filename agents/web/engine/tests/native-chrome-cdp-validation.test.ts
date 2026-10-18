import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import fs from "node:fs/promises";
import { NativeChromeManager } from "../src/browser/NativeChromeManager.js";

test("Chrome launcher does not inject legacy remote-debugging flags into the default profile", async () => {
  const source = await fs.readFile(new URL("../src/browser/NativeChromeManager.ts", import.meta.url), "utf8");
  const launchStart = source.indexOf("async launchProfile(");
  const launchEnd = source.indexOf("async launchStatus()", launchStart);
  const launchSource = source.slice(launchStart, launchEnd);
  assert.doesNotMatch(launchSource, /["'`]--remote-debugging-port/);
  assert.doesNotMatch(launchSource, /["'`]--remote-debugging-address/);
  assert.match(launchSource, /--profile-directory=/);
});

test("Chrome 144+ permission proxy accepts the trusted DevToolsActivePort WebSocket without /json/version", async () => {
  const server = createServer((_req, res) => {
    res.writeHead(404);
    res.end();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    const manager = new NativeChromeManager();
    (manager as any).remoteDebuggingUserEnabled = async () => true;
    const endpoint = `ws://127.0.0.1:${port}/devtools/browser/permission-proxy-id`;
    assert.equal(await (manager as any).validatedPermissionProxyEndpoint(endpoint), endpoint);

    (manager as any).remoteDebuggingUserEnabled = async () => false;
    assert.equal(await (manager as any).validatedPermissionProxyEndpoint(endpoint), null);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

test("CDP discovery only accepts standard endpoints that expose a real /json/version debugger URL", async () => {
  const server = createServer((req, res) => {
    if (req.url === "/json/version") {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        Browser: "Chrome/Test",
        "Protocol-Version": "1.3",
        webSocketDebuggerUrl: `ws://127.0.0.1:${port}/devtools/browser/test-browser-id`,
      }));
      return;
    }
    res.writeHead(404);
    res.end();
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    const port = typeof address === "object" && address ? address.port : 0;
    const manager = new NativeChromeManager();
    const valid = await (manager as any).validatedDevToolsEndpoint(`http://127.0.0.1:${port}`);
    assert.equal(valid, `ws://127.0.0.1:${port}/devtools/browser/test-browser-id`);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }

  const manager = new NativeChromeManager();
  const invalid = await (manager as any).validatedDevToolsEndpoint("http://127.0.0.1:1");
  assert.equal(invalid, null);
});

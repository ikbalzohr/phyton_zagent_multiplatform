import { createServer } from "node:http";
import { authenticateInternalToken, internalTransport } from "./server/executionContext.js";
import {
  hostHeaderValidation,
  originValidation,
  toNodeHandler,
} from "@modelcontextprotocol/node";
import { createMcpHandler } from "@modelcontextprotocol/server";
import { browserManager } from "./browser/BrowserManager.js";
import { browserSessions } from "./browser/SessionManager.js";
import { nativeAttachCoordinator } from "./browser/NativeAttachCoordinator.js";
import { nativeChrome } from "./browser/NativeChromeManager.js";
import { buildMcpServer } from "./server/createMcpServer.js";
import { bridge } from './bridge/Bridge.js';
import { resolveTargets } from './bridge/gate.js';

await browserManager.init();
if (browserManager.settings.runtimeMode !== "native_attach" && browserManager.settings.autoStartBrowser) {
  await browserManager.start().catch((error) => {
    console.error("[Zagent Web] Managed browser autostart failed:", error instanceof Error ? error.message : String(error));
  });
}

const handler = createMcpHandler(buildMcpServer);
const nodeHandler = toNodeHandler(handler);

const host = browserManager.settings.host;
if (!['localhost', '127.0.0.1', '127.0.0.3', '::1'].includes(host)) throw new Error('Web backend must bind private loopback');
const port = browserManager.settings.port;

const allowedLoopbackHosts = Array.from(
  new Set(["localhost", "127.0.0.1", host, "[::1]"]),
);
const validateHost = hostHeaderValidation(allowedLoopbackHosts);
const validateOrigin = originValidation(allowedLoopbackHosts);

const httpServer = createServer((req, res) => {
  const pathname = new URL(req.url ?? "/", `http://${req.headers.host ?? "127.0.0.1"}`).pathname;

  if (pathname.startsWith('/bridge/')) {
    void bridge.handle(
      req,
      res,
      resolveTargets,
      () => browserManager.isNativeAttached(),
      () => nativeChrome.detach(),
    );
    return;
  }

  if (pathname === "/health") {
    if (!validateHost(req, res) || !validateOrigin(req, res)) return;
    void bridge.refresh().then(async (required) => required
      ? {
          ok: true,
          service: 'Zagent Web',
          version: '1.0.0',
          nativeAttached: browserManager.isNativeAttached(),
          bridgeRequired: true,
          autoAttach: nativeAttachCoordinator.status(),
        }
      : browserManager.status()).then((status) => {
      res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(status, null, 2));
    }).catch((error) => {
      res.writeHead(500, { "content-type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }));
    });
    return;
  }

  if (pathname !== "/mcp") {
    res.writeHead(404, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: false, error: "Not found", mcp: "/mcp", health: "/health" }));
    return;
  }

  if (!validateHost(req, res) || !validateOrigin(req, res)) return;
  if (!authenticateInternalToken(req.headers['x-zagent-internal-token'])) {
    res.writeHead(401, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ok:false, error:'AUTHENTICATED_INTERNAL_CHANNEL_REQUIRED'}));
    return;
  }
  internalTransport.run(true, () => { void nodeHandler(req, res); });
});

httpServer.listen(port, host, () => {
  if (browserManager.settings.runtimeMode === "native_attach" && browserManager.settings.nativeAutoAttach) {
    nativeAttachCoordinator.start();
  }
  console.log("");
  console.log("╔════════════════════════════════════════════════════╗");
  console.log("║                    ZAGENT WEB                   ║");
  console.log("║       TypeScript + Node.js + Playwright + MCP    ║");
  console.log("╚════════════════════════════════════════════════════╝");
  console.log(`MCP    : http://${host}:${port}/mcp`);
  console.log(`Health : http://${host}:${port}/health`);
  console.log(`Node   : ${process.version}`);
  console.log(`Browser: ${browserManager.settings.browser}`);
  console.log(`Mode   : ${browserManager.settings.runtimeMode ?? "managed"}`);
  console.log("");
});

async function shutdown(signal: string) {
  console.log(`[Zagent Web] ${signal} received, shutting down...`);
  nativeAttachCoordinator.stop();
  await browserSessions.closeAll(true).catch(() => undefined);
  await browserManager.stop().catch(() => undefined);
  await handler.close().catch(() => undefined);
  httpServer.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 5000).unref();
}

process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));
import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";
import { redactHeaders } from "../utils/security.js";

export function registerNetworkTools(server: McpServer): void {
  server.registerTool("web_console_logs", {
    description: "Return captured browser console messages and page errors."
  }, async () => mcpText({ console: B.consoleEvents, pageErrors: B.pageErrors }));

  server.registerTool("web_console_errors", {
    description: "Return browser console errors and uncaught page errors."
  }, async () => mcpText({
    console: B.consoleEvents.filter((x) => x.type === "error"),
    pageErrors: B.pageErrors,
  }));

  server.registerTool("web_console_clear", {
    description: "Clear in-memory console and page-error logs."
  }, async () => {
    B.consoleEvents.splice(0);
    B.pageErrors.splice(0);
    return mcpText({ ok: true });
  });

  server.registerTool("web_network_requests", {
    description: "Return captured request/response metadata."
  }, async () => mcpText(B.networkEvents));

  server.registerTool("web_network_errors", {
    description: "Return failed/error HTTP responses (status >= 400)."
  }, async () => mcpText(B.networkEvents.filter((x) => x.kind === "response" && (x.status ?? 0) >= 400)));

  server.registerTool("web_network_request_detail", {
    description: "Return a captured request by id, including headers and post data.",
    inputSchema: z.object({ id: z.string().min(1) }),
  }, async ({ id }) => {
    const req = B.requestRefs.get(id);
    if (!req) throw new Error(`Request id '${id}' not found.`);
    return mcpText({
      id,
      url: req.url(),
      method: req.method(),
      resourceType: req.resourceType(),
      headers: redactHeaders(req.headers(), B.settings.redactHeaders),
      postData: req.postData(),
      frameUrl: req.frame().url(),
    });
  });

  server.registerTool("web_network_response", {
    description: "Return response metadata and optionally a bounded body by response id.",
    inputSchema: z.object({
      id: z.string().min(1),
      includeBody: z.boolean().default(true),
      maxBytes: z.number().int().min(1).max(5_000_000).default(1_000_000),
    }),
  }, async ({ id, includeBody, maxBytes }) => {
    const res = B.responseRefs.get(id);
    if (!res) throw new Error(`Response id '${id}' not found.`);
    const out: Record<string, unknown> = {
      id,
      url: res.url(),
      status: res.status(),
      statusText: res.statusText(),
      ok: res.ok(),
      headers: redactHeaders(res.headers(), B.settings.redactHeaders),
    };
    if (includeBody) {
      const buf = await res.body().catch(() => null);
      if (buf) {
        const clipped = buf.subarray(0, maxBytes);
        const type = res.headers()["content-type"] ?? "";
        out.bodyTruncated = buf.length > maxBytes;
        out.bodyBytes = buf.length;
        if (/json|text|javascript|xml|html|css/i.test(type)) {
          out.body = clipped.toString("utf8");
        } else {
          out.bodyBase64 = clipped.toString("base64");
        }
      }
    }
    return mcpText(out);
  });

  server.registerTool("web_network_find", {
    description: "Search captured network events by URL substring.",
    inputSchema: z.object({ urlContains: z.string().min(1) }),
  }, async ({ urlContains }) => mcpText(
    B.networkEvents.filter((x) => x.url.toLowerCase().includes(urlContains.toLowerCase())),
  ));

  server.registerTool("web_network_clear", {
    description: "Clear in-memory network logs and request/response references."
  }, async () => {
    B.networkEvents.splice(0);
    B.requestRefs.clear();
    B.responseRefs.clear();
    return mcpText({ ok: true });
  });

  server.registerTool("web_network_block", {
    description: "Block requests matching a Playwright URL pattern.",
    inputSchema: z.object({ pattern: z.string().min(1) }),
  }, async ({ pattern }) => {
    await B.ensure();
    if (!B.settings.enableNetworkInterception) throw new Error("Network interception is disabled.");
    await B.context!.route(pattern, async (route) => route.abort());
    return mcpText({ ok: true, pattern, action: "abort" });
  });

  server.registerTool("web_network_mock", {
    description: "Mock matching requests with a static response.",
    inputSchema: z.object({
      pattern: z.string().min(1),
      status: z.number().int().min(100).max(599).default(200),
      body: z.string().default(""),
      contentType: z.string().default("application/json"),
    }),
  }, async ({ pattern, status, body, contentType }) => {
    await B.ensure();
    if (!B.settings.enableNetworkInterception) throw new Error("Network interception is disabled.");
    await B.context!.route(pattern, async (route) => {
      await route.fulfill({
        status,
        body,
        headers: { "content-type": contentType },
      });
    });
    return mcpText({ ok: true, pattern, action: "fulfill", status, contentType });
  });

  server.registerTool("web_network_routes_clear", {
    description: "Remove all network interception routes."
  }, async () => {
    await B.ensure();
    await B.context!.unrouteAll({ behavior: "wait" });
    return mcpText({ ok: true });
  });
}

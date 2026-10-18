import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";

export function registerRuntimeTools(server: McpServer): void {
  server.registerTool("web_ping", {
    description: "Health check Zagent Web and browser runtime."
  }, async () => mcpText(await B.status()));

  server.registerTool("web_runtime_info", {
    description: "Return Zagent Web runtime, version, settings summary, and browser status."
  }, async () => mcpText({
    version: "2.0.0",
    runtime: "Node.js + TypeScript",
    engine: "Playwright",
    node: process.version,
    settings: {
      host: B.settings?.host,
      port: B.settings?.port,
      browser: B.settings?.browser,
      headless: B.settings?.headless,
      runtimeMode: B.settings?.runtimeMode,
      nativeAutoAttach: B.settings?.nativeAutoAttach,
      nativeAttachOnDemand: B.settings?.nativeAttachOnDemand,
      allowedHosts: B.settings?.allowedHosts,
      allowExternalHosts: B.settings?.allowExternalHosts,
    },
    status: await B.status(),
  }));

  server.registerTool("web_browser_start", {
    description: "Start Google Chrome through the managed Playwright Chrome path. Native Chrome attach remains the default v2 mode.",
    inputSchema: z.object({
      browser: z.literal("chrome").optional(),
      headless: z.boolean().optional(),
    }),
  }, async ({ browser, headless }) => mcpText(await B.start(browser, headless)));

  server.registerTool("web_browser_stop", {
    description: "Stop a managed runtime or safely detach an external/native Chrome runtime without closing Chrome."
  }, async () => mcpText(await B.stop()));

  server.registerTool("web_status", {
    description: "Return current browser/page status."
  }, async () => mcpText(await B.status()));
}

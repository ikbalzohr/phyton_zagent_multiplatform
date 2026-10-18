import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";

export function registerNavigationTools(server: McpServer): void {
  server.registerTool("web_open", {
    description: "Open an approved URL or named target in the active page.",
    inputSchema: z.object({
      urlOrTarget: z.string().min(1),
      waitUntil: z.enum(["load", "domcontentloaded", "networkidle", "commit"]).default("domcontentloaded"),
    }),
  }, async ({ urlOrTarget, waitUntil }) => mcpText(await B.open(urlOrTarget, waitUntil)));

  server.registerTool("web_close", {
    description: "Close the active page. If no pages remain, create a blank page."
  }, async () => {
    await B.ensure();
    await B.page!.close();
    const pages = B.context!.pages();
    if (pages.length) B.page = pages.at(-1)!;
    else {
      B.page = await B.context!.newPage();
    }
    return mcpText(await B.status());
  });

  server.registerTool("web_reload", {
    description: "Reload the active page.",
    inputSchema: z.object({
      waitUntil: z.enum(["load", "domcontentloaded", "networkidle", "commit"]).default("domcontentloaded"),
    }),
  }, async ({ waitUntil }) => {
    await B.ensure();
    const response = await B.page!.reload({ waitUntil });
    B.record("reload", { waitUntil });
    return mcpText({ url: B.page!.url(), status: response?.status() ?? null });
  });

  server.registerTool("web_back", {
    description: "Navigate browser history backward."
  }, async () => {
    await B.ensure();
    const response = await B.page!.goBack({ waitUntil: "domcontentloaded" });
    return mcpText({ url: B.page!.url(), status: response?.status() ?? null });
  });

  server.registerTool("web_forward", {
    description: "Navigate browser history forward."
  }, async () => {
    await B.ensure();
    const response = await B.page!.goForward({ waitUntil: "domcontentloaded" });
    return mcpText({ url: B.page!.url(), status: response?.status() ?? null });
  });

  server.registerTool("web_get_url", {
    description: "Return the active page URL."
  }, async () => {
    await B.ensure();
    return mcpText(B.page!.url());
  });

  server.registerTool("web_get_title", {
    description: "Return the active page title."
  }, async () => {
    await B.ensure();
    return mcpText(await B.page!.title());
  });

  server.registerTool("web_get_page_state", {
    description: "Return current URL, title, viewport, page count, and loading state."
  }, async () => {
    await B.ensure();
    return mcpText({
      url: B.page!.url(),
      title: await B.page!.title(),
      viewport: B.page!.viewportSize(),
      pages: B.context!.pages().length,
      closed: B.page!.isClosed(),
    });
  });
}

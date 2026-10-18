import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { nativeChrome } from "../browser/NativeChromeManager.js";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";

export function registerNativeChromeTools(server: McpServer): void {
  server.registerTool("web_chrome_profiles", {
    description: "List real installed Google Chrome profiles from Chrome Local State, including profile directory and display name."
  }, async () => mcpText(await nativeChrome.profiles()));

  server.registerTool("web_chrome_launch_profile", {
    description: "Launch the real installed Google Chrome using a specific existing profile selected during workspace provisioning, preserving profile-directory arguments with spaces.",
    inputSchema: z.object({
      profile: z.string().min(1),
      url: z.string().optional(),
      newWindow: z.boolean().default(true),
    }),
  }, async ({ profile, url, newWindow }) => mcpText(await nativeChrome.launchProfile(profile, { url, newWindow })));

  server.registerTool("web_chrome_launch_status", {
    description: "Return real Chrome launcher status, detected profiles, last requested profile launch, running profile arguments, and native attachment status."
  }, async () => mcpText(await nativeChrome.launchStatus()));

  server.registerTool("web_native_chrome_detect", {
    description: "Detect the real installed Google Chrome and whether it is available for native CDP attachment."
  }, async () => mcpText(await nativeChrome.status()));

  server.registerTool("web_native_chrome_status", {
    description: "Return native Google Chrome installation, process, remote-debugging, and attachment status."
  }, async () => mcpText(await nativeChrome.status()));

  server.registerTool("web_native_chrome_attach", {
    description: "Attach Zagent Web to the real already-running Google Chrome through CDP without owning or closing the Chrome process.",
    inputSchema: z.object({ endpoint: z.string().url().optional() }),
  }, async ({ endpoint }) => mcpText(await nativeChrome.attach(endpoint)));

  server.registerTool("web_native_chrome_detach", {
    description: "Logically detach Zagent Web from the real Chrome without closing Chrome, its profile, or existing user tabs."
  }, async () => mcpText(await nativeChrome.detach()));

  server.registerTool("web_native_chrome_tabs", {
    description: "List tabs from the currently attached real Google Chrome."
  }, async () => {
    await B.ensure();
    return mcpText({
      nativeAttached: B.isNativeAttached(),
      tabs: B.context?.pages().map((page, index) => ({ index, url: page.url(), title: null })) ?? [],
    });
  });
}

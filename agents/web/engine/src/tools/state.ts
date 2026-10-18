import fs from "node:fs/promises";
import type { BrowserContext, BrowserContextOptions } from "playwright-core";
import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";

export function registerStateTools(server: McpServer): void {
  server.registerTool("web_set_viewport", {
    description: "Set active page viewport size.",
    inputSchema: z.object({
      width: z.number().int().min(100).max(10000),
      height: z.number().int().min(100).max(10000),
    }),
  }, async ({ width, height }) => {
    await B.ensure();
    await B.page!.setViewportSize({ width, height });
    return mcpText(B.page!.viewportSize());
  });

  server.registerTool("web_get_viewport", {
    description: "Return current page viewport size."
  }, async () => {
    await B.ensure();
    return mcpText(B.page!.viewportSize());
  });

  server.registerTool("web_set_device", {
    description: "Recreate the browser context using a Playwright device descriptor.",
    inputSchema: z.object({ deviceName: z.string().min(1) }),
  }, async ({ deviceName }) => {
    await B.ensure();
    const descriptor = B.deviceDescriptor(deviceName);
    const { defaultBrowserType: _ignored, ...contextOptions } = descriptor as typeof descriptor & { defaultBrowserType?: string };
    await B.recreateContext(contextOptions as BrowserContextOptions, true);
    return mcpText({ deviceName, viewport: B.page!.viewportSize(), url: B.page!.url() });
  });

  server.registerTool("web_device_list", {
    description: "List built-in Playwright device emulation names."
  }, async () => {
    const { devices } = await import("playwright-core");
    return mcpText(Object.keys(devices).sort());
  });

  server.registerTool("web_cookies_get", {
    description: "Return cookies from the active browser context.",
    inputSchema: z.object({ urls: z.array(z.string()).optional() }),
  }, async ({ urls }) => {
    await B.ensure();
    return mcpText(await B.context!.cookies(urls ?? []));
  });

  server.registerTool("web_cookies_set", {
    description: "Add or update cookies in the active browser context.",
    inputSchema: z.object({
      cookies: z.array(z.object({
        name: z.string(),
        value: z.string(),
        url: z.string().optional(),
        domain: z.string().optional(),
        path: z.string().optional(),
        expires: z.number().optional(),
        httpOnly: z.boolean().optional(),
        secure: z.boolean().optional(),
        sameSite: z.enum(["Strict", "Lax", "None"]).optional(),
      })).min(1),
    }),
  }, async ({ cookies }) => {
    await B.ensure();
    await B.context!.addCookies(cookies as Parameters<BrowserContext["addCookies"]>[0]);
    return mcpText({ ok: true, count: cookies.length });
  });

  server.registerTool("web_cookies_clear", {
    description: "Clear cookies from the active browser context."
  }, async () => {
    await B.ensure();
    await B.context!.clearCookies();
    return mcpText({ ok: true });
  });

  server.registerTool("web_storage_get", {
    description: "Read localStorage or sessionStorage for the active page origin.",
    inputSchema: z.object({ kind: z.enum(["local", "session"]).default("local") }),
  }, async ({ kind }) => {
    await B.ensure();
    const value = await B.page!.evaluate((k) => {
      const store = k === "local" ? localStorage : sessionStorage;
      return Object.fromEntries(Array.from({ length: store.length }, (_, i) => {
        const key = store.key(i)!;
        return [key, store.getItem(key)];
      }));
    }, kind);
    return mcpText(value);
  });

  server.registerTool("web_storage_set", {
    description: "Set one localStorage or sessionStorage item.",
    inputSchema: z.object({
      kind: z.enum(["local", "session"]).default("local"),
      key: z.string(),
      value: z.string(),
    }),
  }, async ({ kind, key, value }) => {
    await B.ensure();
    await B.page!.evaluate(({ kind, key, value }) => {
      (kind === "local" ? localStorage : sessionStorage).setItem(key, value);
    }, { kind, key, value });
    return mcpText({ ok: true });
  });

  server.registerTool("web_storage_clear", {
    description: "Clear localStorage or sessionStorage for the active page origin.",
    inputSchema: z.object({ kind: z.enum(["local", "session"]).default("local") }),
  }, async ({ kind }) => {
    await B.ensure();
    await B.page!.evaluate((k) => (k === "local" ? localStorage : sessionStorage).clear(), kind);
    return mcpText({ ok: true });
  });

  server.registerTool("web_storage_state_save", {
    description: "Persist Playwright storage state (cookies/localStorage) to a local JSON file.",
    inputSchema: z.object({ path: z.string().min(1) }),
  }, async ({ path }) => {
    await B.ensure();
    const output = B.abs(path);
    await B.context!.storageState({ path: output });
    return mcpText({ path: output });
  });

  server.registerTool("web_storage_state_load", {
    description: "Recreate context using a previously saved Playwright storage-state JSON file.",
    inputSchema: z.object({ path: z.string().min(1) }),
  }, async ({ path }) => {
    await B.ensure();
    const file = B.abs(path);
    await fs.access(file);
    await B.recreateContext({ storageState: file }, true);
    return mcpText({ ok: true, path: file, url: B.page!.url() });
  });

  server.registerTool("web_set_geolocation", {
    description: "Set browser-context geolocation.",
    inputSchema: z.object({
      latitude: z.number().min(-90).max(90),
      longitude: z.number().min(-180).max(180),
      accuracy: z.number().min(0).default(50),
    }),
  }, async ({ latitude, longitude, accuracy }) => {
    await B.ensure();
    await B.context!.setGeolocation({ latitude, longitude, accuracy });
    return mcpText({ ok: true });
  });

  server.registerTool("web_grant_permissions", {
    description: "Grant browser permissions, optionally scoped to an origin.",
    inputSchema: z.object({
      permissions: z.array(z.string()).min(1),
      origin: z.string().optional(),
    }),
  }, async ({ permissions, origin }) => {
    await B.ensure();
    await B.context!.grantPermissions(permissions, { origin });
    return mcpText({ ok: true, permissions, origin: origin ?? null });
  });

  server.registerTool("web_clear_permissions", {
    description: "Clear browser-context permissions."
  }, async () => {
    await B.ensure();
    await B.context!.clearPermissions();
    return mcpText({ ok: true });
  });
}

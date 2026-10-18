import fs from "node:fs/promises";
import path from "node:path";
import type { McpServer } from "@modelcontextprotocol/server";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";

async function shot(name: string | undefined, fullPage: boolean, selector?: string) {
  await B.ensure();
  const filename = (name?.trim() || `shot_${Date.now()}.png`).replace(/[\\/:*?"<>|]/g, "_");
  const finalName = filename.toLowerCase().endsWith(".png") ? filename : filename + ".png";
  const output = path.join(B.abs(B.settings.screenshotsDir), finalName);
  if (selector) await B.page!.locator(selector).first().screenshot({ path: output });
  else await B.page!.screenshot({ path: output, fullPage });
  return { path: output, fullPage, selector: selector ?? null };
}

export function registerInspectionTools(server: McpServer): void {
  server.registerTool("web_get_html", {
    description: "Return outer HTML for a selector, or the full page HTML if selector is omitted.",
    inputSchema: z.object({ selector: z.string().optional() }),
  }, async ({ selector }) => {
    await B.ensure();
    if (selector) {
      return mcpText(await B.page!.locator(selector).first().evaluate((el) => (el as HTMLElement).outerHTML));
    }
    return mcpText(await B.page!.content());
  });

  server.registerTool("web_screenshot", {
    description: "Capture a viewport screenshot.",
    inputSchema: z.object({ name: z.string().optional() }),
  }, async ({ name }) => mcpText(await shot(name, false)));

  server.registerTool("web_screenshot_full_page", {
    description: "Capture a full-page screenshot.",
    inputSchema: z.object({ name: z.string().optional() }),
  }, async ({ name }) => mcpText(await shot(name, true)));

  server.registerTool("web_screenshot_element", {
    description: "Capture a screenshot of one element matched by selector.",
    inputSchema: z.object({ selector: z.string().min(1), name: z.string().optional() }),
  }, async ({ selector, name }) => mcpText(await shot(name, false, selector)));

  server.registerTool("web_inspect", {
    description: "Inspect one element: text, attributes, state, and bounding box.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    const loc = B.page!.locator(selector).first();
    return mcpText({
      selector,
      count: await B.page!.locator(selector).count(),
      text: await loc.innerText().catch(() => ""),
      html: await loc.evaluate((el) => (el as HTMLElement).outerHTML).catch(() => ""),
      id: await loc.getAttribute("id"),
      class: await loc.getAttribute("class"),
      role: await loc.getAttribute("role"),
      ariaLabel: await loc.getAttribute("aria-label"),
      name: await loc.getAttribute("name"),
      type: await loc.getAttribute("type"),
      value: await loc.inputValue().catch(() => null),
      visible: await loc.isVisible().catch(() => false),
      enabled: await loc.isEnabled().catch(() => false),
      editable: await loc.isEditable().catch(() => false),
      checked: await loc.isChecked().catch(() => null),
      bounds: await loc.boundingBox(),
    });
  });

  server.registerTool("web_get_text", {
    description: "Read text from a selector.",
    inputSchema: z.object({ selector: z.string().default("body") }),
  }, async ({ selector }) => {
    await B.ensure();
    return mcpText(await B.page!.locator(selector).first().innerText());
  });

  server.registerTool("web_get_elements", {
    description: "Return a bounded list of matching elements with useful attributes.",
    inputSchema: z.object({
      selector: z.string().default("*"),
      limit: z.number().int().min(1).max(1000).default(100),
    }),
  }, async ({ selector, limit }) => {
    await B.ensure();
    const locator = B.page!.locator(selector);
    const count = Math.min(await locator.count(), limit);
    const items: unknown[] = [];
    for (let i = 0; i < count; i++) {
      const el = locator.nth(i);
      items.push({
        index: i,
        text: (await el.innerText().catch(() => "")).slice(0, 500),
        id: await el.getAttribute("id"),
        class: await el.getAttribute("class"),
        role: await el.getAttribute("role"),
        ariaLabel: await el.getAttribute("aria-label"),
        name: await el.getAttribute("name"),
        type: await el.getAttribute("type"),
        visible: await el.isVisible().catch(() => false),
      });
    }
    return mcpText({ selector, total: await locator.count(), returned: items.length, items });
  });

  server.registerTool("web_get_element", {
    description: "Alias-style single-element inspection with a concise result.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    const el = B.page!.locator(selector).first();
    return mcpText({
      selector,
      text: await el.innerText().catch(() => ""),
      visible: await el.isVisible().catch(() => false),
      bounds: await el.boundingBox(),
    });
  });

  server.registerTool("web_get_attribute", {
    description: "Read one element attribute.",
    inputSchema: z.object({ selector: z.string().min(1), name: z.string().min(1) }),
  }, async ({ selector, name }) => {
    await B.ensure();
    return mcpText({ selector, name, value: await B.page!.locator(selector).first().getAttribute(name) });
  });

  server.registerTool("web_get_bounds", {
    description: "Return element bounding box in CSS pixels.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    return mcpText(await B.page!.locator(selector).first().boundingBox());
  });

  server.registerTool("web_get_accessibility_tree", {
    description: "Return a Playwright ARIA snapshot for the page or a subtree.",
    inputSchema: z.object({ selector: z.string().default("body") }),
  }, async ({ selector }) => {
    await B.ensure();
    const loc = B.page!.locator(selector).first() as any;
    if (typeof loc.ariaSnapshot === "function") {
      return mcpText(await loc.ariaSnapshot());
    }
    return mcpText({
      warning: "ariaSnapshot unavailable in this runtime",
      text: await B.page!.locator(selector).first().innerText().catch(() => ""),
    });
  });

  server.registerTool("web_find", {
    description: "Find visible text and return match count and texts.",
    inputSchema: z.object({ text: z.string().min(1), exact: z.boolean().default(false) }),
  }, async ({ text, exact }) => {
    await B.ensure();
    const loc = B.page!.getByText(text, { exact });
    return mcpText({ count: await loc.count(), texts: (await loc.allInnerTexts()).slice(0, 100) });
  });

  server.registerTool("web_find_text", {
    description: "Find text using Playwright text semantics.",
    inputSchema: z.object({ text: z.string().min(1), exact: z.boolean().default(false) }),
  }, async ({ text, exact }) => {
    await B.ensure();
    const loc = B.page!.getByText(text, { exact });
    return mcpText({ count: await loc.count(), texts: (await loc.allInnerTexts()).slice(0, 100) });
  });

  server.registerTool("web_find_role", {
    description: "Find elements by accessibility role and optional accessible name.",
    inputSchema: z.object({ role: z.string().min(1), name: z.string().optional() }),
  }, async ({ role, name }) => {
    await B.ensure();
    const loc = B.page!.getByRole(role as any, name ? { name } : undefined);
    return mcpText({ count: await loc.count(), texts: (await loc.allInnerTexts()).slice(0, 100) });
  });

  server.registerTool("web_visual_compare", {
    description: "Pixel-compare two PNG screenshots and optionally write a diff image.",
    inputSchema: z.object({
      before: z.string().min(1),
      after: z.string().min(1),
      diffName: z.string().optional(),
      threshold: z.number().min(0).max(1).default(0.1),
    }),
  }, async ({ before, after, diffName, threshold }) => {
    const a = PNG.sync.read(await fs.readFile(B.abs(before)));
    const b = PNG.sync.read(await fs.readFile(B.abs(after)));
    if (a.width !== b.width || a.height !== b.height) {
      return mcpText({ sameSize: false, before: { width: a.width, height: a.height }, after: { width: b.width, height: b.height } });
    }
    const diff = new PNG({ width: a.width, height: a.height });
    const changedPixels = pixelmatch(a.data, b.data, diff.data, a.width, a.height, { threshold });
    const totalPixels = a.width * a.height;
    let diffPath: string | null = null;
    if (diffName) {
      const name = diffName.toLowerCase().endsWith(".png") ? diffName : diffName + ".png";
      diffPath = path.join(B.abs(B.settings.screenshotsDir), name);
      await fs.writeFile(diffPath, PNG.sync.write(diff));
    }
    return mcpText({
      sameSize: true,
      changed: changedPixels > 0,
      changedPixels,
      totalPixels,
      changeRatio: totalPixels ? changedPixels / totalPixels : 0,
      diffPath,
    });
  });
}

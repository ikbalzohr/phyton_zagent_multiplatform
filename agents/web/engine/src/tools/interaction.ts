import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";

export function registerInteractionTools(server: McpServer): void {
  server.registerTool("web_click", {
    description: "Click an element matched by selector.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().click();
    B.record("click", { selector });
    return mcpText({ ok: true });
  });

  server.registerTool("web_double_click", {
    description: "Double-click an element.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().dblclick();
    B.record("double_click", { selector });
    return mcpText({ ok: true });
  });

  server.registerTool("web_right_click", {
    description: "Right-click an element.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().click({ button: "right" });
    B.record("right_click", { selector });
    return mcpText({ ok: true });
  });

  server.registerTool("web_hover", {
    description: "Hover over an element.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().hover();
    B.record("hover", { selector });
    return mcpText({ ok: true });
  });

  server.registerTool("web_drag_drop", {
    description: "Drag from source selector and drop on target selector.",
    inputSchema: z.object({ source: z.string().min(1), target: z.string().min(1) }),
  }, async ({ source, target }) => {
    await B.ensure();
    await B.page!.dragAndDrop(source, target);
    B.record("drag_drop", { source, target });
    return mcpText({ ok: true });
  });

  server.registerTool("web_type", {
    description: "Type text sequentially into an element, preserving existing value.",
    inputSchema: z.object({
      selector: z.string().min(1),
      text: z.string(),
      delayMs: z.number().int().min(0).max(5000).default(0),
    }),
  }, async ({ selector, text, delayMs }) => {
    await B.ensure();
    await B.page!.locator(selector).first().pressSequentially(text, { delay: delayMs });
    B.record("type", { selector, text, delayMs });
    return mcpText({ ok: true });
  });

  server.registerTool("web_fill", {
    description: "Replace the current value of an input/textarea/contenteditable field.",
    inputSchema: z.object({ selector: z.string().min(1), value: z.string() }),
  }, async ({ selector, value }) => {
    await B.ensure();
    await B.page!.locator(selector).first().fill(value);
    B.record("fill", { selector, value });
    return mcpText({ ok: true });
  });

  server.registerTool("web_clear", {
    description: "Clear an editable field.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().clear();
    B.record("clear", { selector });
    return mcpText({ ok: true });
  });

  server.registerTool("web_focus", {
    description: "Focus an element.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().focus();
    return mcpText({ ok: true });
  });

  server.registerTool("web_press", {
    description: "Press a keyboard key on an element.",
    inputSchema: z.object({ selector: z.string().min(1), key: z.string().min(1) }),
  }, async ({ selector, key }) => {
    await B.ensure();
    await B.page!.locator(selector).first().press(key);
    B.record("press", { selector, key });
    return mcpText({ ok: true });
  });

  server.registerTool("web_keyboard_press", {
    description: "Press a keyboard key at page level.",
    inputSchema: z.object({ key: z.string().min(1) }),
  }, async ({ key }) => {
    await B.ensure();
    await B.page!.keyboard.press(key);
    B.record("keyboard_press", { key });
    return mcpText({ ok: true });
  });

  server.registerTool("web_select", {
    description: "Select an option by value.",
    inputSchema: z.object({ selector: z.string().min(1), value: z.string() }),
  }, async ({ selector, value }) => {
    await B.ensure();
    const selected = await B.page!.locator(selector).first().selectOption({ value });
    B.record("select", { selector, value });
    return mcpText({ selected });
  });

  server.registerTool("web_check", {
    description: "Check a checkbox or radio control.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().check();
    B.record("check", { selector });
    return mcpText({ ok: true });
  });

  server.registerTool("web_uncheck", {
    description: "Uncheck a checkbox.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().uncheck();
    B.record("uncheck", { selector });
    return mcpText({ ok: true });
  });

  server.registerTool("web_scroll", {
    description: "Scroll the page by mouse-wheel deltas.",
    inputSchema: z.object({
      deltaX: z.number().default(0),
      deltaY: z.number().default(600),
    }),
  }, async ({ deltaX, deltaY }) => {
    await B.ensure();
    await B.page!.mouse.wheel(deltaX, deltaY);
    B.record("scroll", { deltaX, deltaY });
    return mcpText({ ok: true });
  });

  server.registerTool("web_scroll_into_view", {
    description: "Scroll an element into view if needed.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    await B.page!.locator(selector).first().scrollIntoViewIfNeeded();
    return mcpText({ ok: true });
  });

  server.registerTool("web_upload_file", {
    description: "Set one or more local files on a file input.",
    inputSchema: z.object({
      selector: z.string().min(1),
      paths: z.array(z.string().min(1)).min(1),
    }),
  }, async ({ selector, paths }) => {
    await B.ensure();
    await B.page!.locator(selector).first().setInputFiles(paths);
    B.record("upload_file", { selector, paths });
    return mcpText({ ok: true, paths });
  });

  server.registerTool("web_download", {
    description: "Click a selector and wait for the resulting browser download.",
    inputSchema: z.object({
      selector: z.string().min(1),
      timeoutMs: z.number().int().min(100).max(120000).default(30000),
    }),
  }, async ({ selector, timeoutMs }) => {
    await B.ensure();
    const downloadPromise = B.page!.waitForEvent("download", { timeout: timeoutMs });
    await B.page!.locator(selector).first().click();
    const download = await downloadPromise;
    const output = B.abs(`${B.settings.downloadsDir}/${download.suggestedFilename()}`);
    await download.saveAs(output);
    const item = {
      filename: download.suggestedFilename(),
      path: output,
      url: download.url(),
      timestamp: Date.now(),
    };
    B.downloads.push(item);
    return mcpText(item);
  });

  server.registerTool("web_downloads", {
    description: "List downloads observed by the active browser session."
  }, async () => mcpText(B.downloads));
}

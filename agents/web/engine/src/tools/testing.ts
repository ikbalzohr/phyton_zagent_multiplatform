import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";

export function registerTestingTools(server: McpServer): void {
  server.registerTool("web_wait", {
    description: "Wait for a fixed number of milliseconds.",
    inputSchema: z.object({ milliseconds: z.number().int().min(0).max(120000) }),
  }, async ({ milliseconds }) => {
    await B.ensure();
    await B.page!.waitForTimeout(milliseconds);
    return mcpText({ ok: true, milliseconds });
  });

  server.registerTool("web_wait_for_element", {
    description: "Wait for an element state.",
    inputSchema: z.object({
      selector: z.string().min(1),
      state: z.enum(["attached", "detached", "visible", "hidden"]).default("visible"),
      timeoutMs: z.number().int().min(1).max(120000).default(10000),
    }),
  }, async ({ selector, state, timeoutMs }) => {
    await B.ensure();
    await B.page!.locator(selector).first().waitFor({ state, timeout: timeoutMs });
    return mcpText({ ok: true, selector, state });
  });

  server.registerTool("web_wait_for_text", {
    description: "Wait for text to become visible.",
    inputSchema: z.object({
      text: z.string().min(1),
      exact: z.boolean().default(false),
      timeoutMs: z.number().int().min(1).max(120000).default(10000),
    }),
  }, async ({ text, exact, timeoutMs }) => {
    await B.ensure();
    await B.page!.getByText(text, { exact }).first().waitFor({ state: "visible", timeout: timeoutMs });
    return mcpText({ ok: true, text });
  });

  server.registerTool("web_wait_for_url", {
    description: "Wait for active page URL to match a glob/regex-compatible string pattern.",
    inputSchema: z.object({
      pattern: z.string().min(1),
      timeoutMs: z.number().int().min(1).max(120000).default(10000),
    }),
  }, async ({ pattern, timeoutMs }) => {
    await B.ensure();
    await B.page!.waitForURL(pattern, { timeout: timeoutMs });
    return mcpText({ url: B.page!.url() });
  });

  server.registerTool("web_wait_for_network_idle", {
    description: "Wait until the page reaches Playwright networkidle state.",
    inputSchema: z.object({
      timeoutMs: z.number().int().min(1).max(120000).default(10000),
    }),
  }, async ({ timeoutMs }) => {
    await B.ensure();
    await B.page!.waitForLoadState("networkidle", { timeout: timeoutMs });
    return mcpText({ ok: true });
  });

  server.registerTool("web_assert_visible", {
    description: "Check whether an element is visible without throwing on a false assertion.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    return mcpText({ pass: await B.page!.locator(selector).first().isVisible().catch(() => false) });
  });

  server.registerTool("web_assert_text", {
    description: "Check whether an element text contains expected text.",
    inputSchema: z.object({
      selector: z.string().min(1),
      expected: z.string(),
      exact: z.boolean().default(false),
    }),
  }, async ({ selector, expected, exact }) => {
    await B.ensure();
    const actual = await B.page!.locator(selector).first().innerText();
    return mcpText({ pass: exact ? actual === expected : actual.includes(expected), actual, expected });
  });

  server.registerTool("web_assert_url", {
    description: "Check whether the active URL contains an expected value.",
    inputSchema: z.object({ expected: z.string().min(1) }),
  }, async ({ expected }) => {
    await B.ensure();
    const actual = B.page!.url();
    return mcpText({ pass: actual.includes(expected), actual, expected });
  });

  server.registerTool("web_assert_element", {
    description: "Check whether at least one element matches a selector.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    const count = await B.page!.locator(selector).count();
    return mcpText({ pass: count > 0, count });
  });

  server.registerTool("web_assert_enabled", {
    description: "Check whether an element is enabled.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    return mcpText({ pass: await B.page!.locator(selector).first().isEnabled().catch(() => false) });
  });

  server.registerTool("web_assert_checked", {
    description: "Check whether a checkbox/radio is checked.",
    inputSchema: z.object({ selector: z.string().min(1) }),
  }, async ({ selector }) => {
    await B.ensure();
    return mcpText({ pass: await B.page!.locator(selector).first().isChecked().catch(() => false) });
  });

  server.registerTool("web_evaluate_js", {
    description: "Power tool: evaluate JavaScript in the active page. Controlled by enableJavascriptEvaluation.",
    inputSchema: z.object({
      expression: z.string().min(1),
      arg: z.unknown().optional(),
    }),
  }, async ({ expression, arg }) => {
    await B.ensure();
    if (!B.settings.enableJavascriptEvaluation) throw new Error("JavaScript evaluation is disabled in config/settings.json.");
    const result = await B.page!.evaluate(({ expression, arg }) => {
      const fn = new Function("arg", `return (async () => { return (${expression}); })();`);
      return fn(arg);
    }, { expression, arg });
    return mcpText(result);
  });
}

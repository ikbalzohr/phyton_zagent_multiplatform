import fs from "node:fs/promises";
import path from "node:path";
import type { Locator } from "playwright-core";
import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager, BrowserManager } from "../browser/BrowserManager.js";
import { browserSessions } from "../browser/SessionManager.js";
import { RUNTIME_DIR } from "../config/paths.js";
import { mcpText } from "../utils/json.js";

const locatorSchema = z.object({
  selector: z.string().optional(),
  role: z.string().optional(),
  name: z.string().optional(),
  text: z.string().optional(),
  label: z.string().optional(),
  placeholder: z.string().optional(),
  exact: z.boolean().default(false),
});

const actionSchema = z.object({
  action: z.enum(["open","click","fill","type","press","wait","wait_text","assert_text","assert_url","screenshot","save_state"]),
  url: z.string().optional(),
  locator: locatorSchema.optional(),
  value: z.string().optional(),
  key: z.string().optional(),
  milliseconds: z.number().int().min(0).max(120000).optional(),
  expected: z.string().optional(),
  name: z.string().optional(),
});

type Action = z.infer<typeof actionSchema>;
type LocatorHint = z.infer<typeof locatorSchema>;

function safeId(value: string): string {
  const out = value.trim().replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 120);
  if (!out) throw new Error("workflowId is required.");
  return out;
}

async function smartLocator(B: BrowserManager, hint: LocatorHint | undefined): Promise<{ locator: Locator; strategy: string }> {
  await B.ensure();
  if (!hint) throw new Error("locator is required for this action.");
  const page = B.page!;
  const candidates: Array<{ locator: Locator; strategy: string }> = [];
  if (hint.selector) candidates.push({ locator: page.locator(hint.selector).first(), strategy: "selector" });
  if (hint.role) candidates.push({ locator: page.getByRole(hint.role as any, hint.name ? { name: hint.name, exact: hint.exact } : undefined).first(), strategy: "role" });
  if (hint.label) candidates.push({ locator: page.getByLabel(hint.label, { exact: hint.exact }).first(), strategy: "label" });
  if (hint.placeholder) candidates.push({ locator: page.getByPlaceholder(hint.placeholder, { exact: hint.exact }).first(), strategy: "placeholder" });
  if (hint.text) candidates.push({ locator: page.getByText(hint.text, { exact: hint.exact }).first(), strategy: "text" });
  if (hint.name && !hint.role) candidates.push({ locator: page.getByText(hint.name, { exact: hint.exact }).first(), strategy: "name-text" });

  const failures: string[] = [];
  for (const candidate of candidates) {
    try {
      if (await candidate.locator.count() > 0) return candidate;
    } catch (error) {
      failures.push(`${candidate.strategy}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  throw new Error(`Self-healing locator failed. Tried: ${candidates.map((x) => x.strategy).join(", ") || "none"}. ${failures.join(" | ")}`);
}

async function runAction(B: BrowserManager, action: Action): Promise<unknown> {
  switch (action.action) {
    case "open":
      if (!action.url) throw new Error("open requires url.");
      return B.open(action.url);
    case "click": {
      const found = await smartLocator(B, action.locator);
      await found.locator.click();
      return { ok: true, strategy: found.strategy };
    }
    case "fill": {
      const found = await smartLocator(B, action.locator);
      await found.locator.fill(action.value ?? "");
      return { ok: true, strategy: found.strategy };
    }
    case "type": {
      const found = await smartLocator(B, action.locator);
      await found.locator.pressSequentially(action.value ?? "");
      return { ok: true, strategy: found.strategy };
    }
    case "press": {
      const found = await smartLocator(B, action.locator);
      await found.locator.press(action.key ?? "Enter");
      return { ok: true, strategy: found.strategy };
    }
    case "wait":
      await B.ensure();
      await B.page!.waitForTimeout(action.milliseconds ?? 500);
      return { ok: true, milliseconds: action.milliseconds ?? 500 };
    case "wait_text":
      await B.ensure();
      if (!action.expected) throw new Error("wait_text requires expected.");
      await B.page!.getByText(action.expected).first().waitFor({ state: "visible", timeout: B.settings.actionTimeoutMs });
      return { ok: true, expected: action.expected };
    case "assert_text": {
      const found = await smartLocator(B, action.locator);
      const actual = await found.locator.innerText();
      const expected = action.expected ?? "";
      const pass = actual.includes(expected);
      if (!pass) throw new Error(`Assertion failed: text does not include '${expected}'.`);
      return { pass: true, actual, expected, strategy: found.strategy };
    }
    case "assert_url":
      await B.ensure();
      const actual = B.page!.url();
      const expected = action.expected ?? "";
      if (!actual.includes(expected)) throw new Error(`Assertion failed: URL '${actual}' does not include '${expected}'.`);
      return { pass: true, actual, expected };
    case "screenshot": {
      await B.ensure();
      const file = B.abs(`${B.settings.screenshotsDir}/${safeId(action.name || `workflow_${Date.now()}`)}.png`);
      await B.page!.screenshot({ path: file });
      return { ok: true, path: file };
    }
    case "save_state":
      await B.ensure();
      return { ok: true, storage: await B.context!.storageState() };
  }
}

function checkpointPath(workflowId: string): string {
  return path.join(RUNTIME_DIR, "workflows", `${safeId(workflowId)}.json`);
}

async function executeWorkflow(
  B: BrowserManager,
  workflowId: string,
  actions: Action[],
  startIndex = 0,
  sessionId?: string,
  stopOnError = true,
  priorResults: unknown[] = [],
): Promise<any> {
  const file = checkpointPath(workflowId);
  await fs.mkdir(path.dirname(file), { recursive: true });
  const results: unknown[] = [...priorResults];
  for (let index = startIndex; index < actions.length; index += 1) {
    const state = {
      version: "2.0.0",
      workflowId,
      sessionId: sessionId ?? null,
      status: "running",
      nextIndex: index,
      actions,
      results,
      updatedAt: Date.now(),
    };
    await fs.writeFile(file, JSON.stringify(state, null, 2), "utf8");
    const action = actions[index]!;
    try {
      const result = await runAction(B, action);
      results.push({ index, action: action.action, ok: true, result });
      await fs.writeFile(file, JSON.stringify({ ...state, nextIndex: index + 1, results, updatedAt: Date.now() }, null, 2), "utf8");
    } catch (error) {
      const failure = { index, action: action.action, ok: false, error: error instanceof Error ? error.message : String(error) };
      results.push(failure);
      await fs.writeFile(file, JSON.stringify({ ...state, status: "failed", nextIndex: index, results, updatedAt: Date.now() }, null, 2), "utf8");
      if (stopOnError) return { ok: false, workflowId, sessionId: sessionId ?? null, checkpoint: file, nextIndex: index, results };
    }
  }
  await fs.writeFile(file, JSON.stringify({
    version: "2.0.0", workflowId, sessionId: sessionId ?? null, status: "succeeded",
    nextIndex: actions.length, actions, results, updatedAt: Date.now(),
  }, null, 2), "utf8");
  return { ok: true, workflowId, sessionId: sessionId ?? null, checkpoint: file, nextIndex: actions.length, results };
}

async function managerFor(sessionId?: string): Promise<BrowserManager> {
  if (!sessionId) {
    await browserManager.ensure();
    return browserManager;
  }
  return (await browserSessions.open(sessionId)).manager;
}

export function registerOrchestrationTools(server: McpServer): void {
  server.registerTool("web_session_open", {
    description: "Open or restore a shared-browser session for multi-chat concurrency.",
    inputSchema: z.object({
      sessionId: z.string().min(1),
      browser: z.literal("chrome").optional(),
      headless: z.boolean().optional(),
      restoreState: z.boolean().default(true),
      isolationMode: z.enum(["auto","context","tabs"]).optional(),
    }),
  }, async ({ sessionId, browser, headless, restoreState, isolationMode }) =>
    mcpText(await browserSessions.open(sessionId, { browser, headless, restoreState, isolationMode }).then(async () => browserSessions.status(sessionId))));

  server.registerTool("web_session_list", {
    description: "List isolated Zagent Web browser sessions."
  }, async () => mcpText(await browserSessions.list()));

  server.registerTool("web_session_status", {
    description: "Return one isolated browser session status.",
    inputSchema: z.object({ sessionId: z.string().min(1) }),
  }, async ({ sessionId }) => mcpText(await browserSessions.status(sessionId)));

  server.registerTool("web_session_save", {
    description: "Persist cookies/localStorage for an isolated browser session.",
    inputSchema: z.object({ sessionId: z.string().min(1) }),
  }, async ({ sessionId }) => mcpText(await browserSessions.saveState(sessionId)));

  server.registerTool("web_session_close", {
    description: "Close one isolated browser session, optionally persisting state.",
    inputSchema: z.object({ sessionId: z.string().min(1), saveState: z.boolean().default(true) }),
  }, async ({ sessionId, saveState }) => mcpText(await browserSessions.close(sessionId, saveState)));

  server.registerTool("web_session_close_all", {
    description: "Close all isolated sessions.",
    inputSchema: z.object({ saveState: z.boolean().default(true) }),
  }, async ({ saveState }) => mcpText(await browserSessions.closeAll(saveState)));

  server.registerTool("web_browser_attach_cdp", {
    description: "Attach to an existing Google Chrome CDP endpoint. Prefer web_native_chrome_attach for the installed Chrome profile.",
    inputSchema: z.object({ endpoint: z.string().url().optional() }),
  }, async ({ endpoint }) => {
    const target = endpoint ?? browserManager.settings.cdpEndpoint;
    if (!target) throw new Error("No CDP endpoint supplied or configured.");
    return mcpText(await browserManager.attachCdp(target));
  });

  server.registerTool("web_act", {
    description: "Execute one high-level browser action with semantic self-healing locator fallbacks.",
    inputSchema: z.object({ sessionId: z.string().optional(), action: actionSchema }),
  }, async ({ sessionId, action }) => {
    if (sessionId) return mcpText(await browserSessions.runExclusive(sessionId, (B) => runAction(B, action)));
    return mcpText(await runAction(await managerFor(), action));
  });

  server.registerTool("web_workflow", {
    description: "Execute multiple browser actions in one round trip with checkpointing and optional isolated session.",
    inputSchema: z.object({
      workflowId: z.string().min(1),
      sessionId: z.string().optional(),
      actions: z.array(actionSchema).min(1).max(100),
      stopOnError: z.boolean().default(true),
    }),
  }, async ({ workflowId, sessionId, actions, stopOnError }) => {
    const result = sessionId
      ? await browserSessions.runExclusive(sessionId, (B) => executeWorkflow(B, workflowId, actions, 0, sessionId, stopOnError))
      : await executeWorkflow(await managerFor(), workflowId, actions, 0, undefined, stopOnError);
    if (result?.ok === false) throw new Error(`Workflow '${workflowId}' failed at step ${result.nextIndex}; checkpoint: ${result.checkpoint}`);
    return mcpText(result);
  });

  server.registerTool("web_workflow_resume", {
    description: "Resume a checkpointed workflow from its last unfinished step.",
    inputSchema: z.object({ workflowId: z.string().min(1), stopOnError: z.boolean().default(true) }),
  }, async ({ workflowId, stopOnError }) => {
    const file = checkpointPath(workflowId);
    const state = JSON.parse(await fs.readFile(file, "utf8")) as { sessionId?: string | null; nextIndex: number; actions: Action[]; status: string; results?: any[] };
    if (state.status === "succeeded") return mcpText({ ok: true, workflowId, alreadyComplete: true, checkpoint: file });
    const sessionId = state.sessionId ?? undefined;
    const priorResults = (state.results ?? []).filter((item) => item?.ok !== false && Number(item?.index) < state.nextIndex);
    const result = sessionId
      ? await browserSessions.runExclusive(sessionId, (B) => executeWorkflow(B, workflowId, state.actions, state.nextIndex, sessionId, stopOnError, priorResults))
      : await executeWorkflow(await managerFor(), workflowId, state.actions, state.nextIndex, undefined, stopOnError, priorResults);
    if (result?.ok === false) throw new Error(`Workflow '${workflowId}' resume failed at step ${result.nextIndex}; checkpoint: ${result.checkpoint}`);
    return mcpText(result);
  });
}
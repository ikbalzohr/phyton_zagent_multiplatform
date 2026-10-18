import fs from "node:fs/promises";
import path from "node:path";
import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { mcpText } from "../utils/json.js";
import { visualArtifactStore } from "../visual/VisualArtifactStore.js";

function safeName(name: string): string {
  return name.replace(/[\\/:*?"<>|]/g, "_");
}

export function registerAdvancedTools(server: McpServer): void {
  server.registerTool("web_trace_start", {
    description: "Start Playwright tracing with screenshots, snapshots, and sources."
  }, async () => {
    await B.ensure();
    await B.context!.tracing.start({ screenshots: true, snapshots: true, sources: true });
    return mcpText({ ok: true });
  });

  server.registerTool("web_trace_stop", {
    description: "Stop Playwright tracing and save a trace ZIP.",
    inputSchema: z.object({ name: z.string().optional() }),
  }, async ({ name }) => {
    await B.ensure();
    const filename = safeName(name?.trim() || `trace_${Date.now()}.zip`);
    const output = path.join(B.abs(B.settings.tracesDir), filename.endsWith(".zip") ? filename : filename + ".zip");
    await B.context!.tracing.stop({ path: output });
    return mcpText({ path: output });
  });

  server.registerTool("web_har_start", {
    description: "Recreate the context with HAR capture enabled while preserving the current URL.",
    inputSchema: z.object({ name: z.string().optional() }),
  }, async ({ name }) => {
    await B.ensure();
    const filename = safeName(name?.trim() || `session_${Date.now()}.har`);
    const output = path.join(B.abs(B.settings.harDir), filename.endsWith(".har") ? filename : filename + ".har");
    B.harPath = output;
    await B.recreateContext({ recordHar: { path: output, mode: "full", content: "embed" } }, true);
    return mcpText({ ok: true, path: output });
  });

  server.registerTool("web_har_stop", {
    description: "Stop HAR capture by closing the current context and reopening a normal context."
  }, async () => {
    await B.ensure();
    const harPath = B.harPath;
    await B.recreateContext({}, true);
    B.harPath = null;
    return mcpText({ ok: true, path: harPath });
  });

  server.registerTool("web_video_start", {
    description: "Recreate context with browser video recording enabled.",
    inputSchema: z.object({
      width: z.number().int().min(100).max(3840).optional(),
      height: z.number().int().min(100).max(2160).optional(),
    }),
  }, async ({ width, height }) => {
    await B.ensure();
    const dir = B.abs(B.settings.videosDir);
    await fs.mkdir(dir, { recursive: true });
    const size = width && height ? { width, height } : undefined;
    B.videoMode = true;
    await B.recreateContext({ recordVideo: { dir, size } }, true);
    return mcpText({ ok: true, dir, size: size ?? null });
  });

  server.registerTool("web_video_stop", {
    description: "Stop video recording, close the recording context, and return generated video paths."
  }, async () => {
    await B.ensure();
    const pages = B.context!.pages();
    const videos = pages.map((p) => p.video()).filter(Boolean);
    const currentUrl = B.page!.url();
    await B.context!.close();
    const paths: string[] = [];
    for (const video of videos) {
      if (!video) continue;
      const p = await video.path().catch(() => null);
      if (p) paths.push(p);
    }
    await B.createContext();
    if (currentUrl.startsWith("http://") || currentUrl.startsWith("https://")) {
      await B.page!.goto(currentUrl, { waitUntil: "domcontentloaded" });
    }
    B.videoMode = false;
    const visualArtifacts = [];
    for (const videoPath of paths) {
      visualArtifacts.push(await visualArtifactStore.publish({
        path: videoPath,
        source: "video",
        kind: "browser-video",
        metadata: { url: currentUrl },
      }));
    }
    return mcpText({ ok: true, paths, visualArtifacts });
  });

  server.registerTool("web_performance_metrics", {
    description: "Return navigation, paint, resource, and memory-style performance metrics available to the page."
  }, async () => {
    await B.ensure();
    const metrics = await B.page!.evaluate(() => {
      const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
      const paints = performance.getEntriesByType("paint").map((entry) => ({
        name: entry.name,
        startTime: entry.startTime,
        duration: entry.duration,
      }));
      const resources = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
      return {
        now: performance.now(),
        navigation: nav ? {
          type: nav.type,
          startTime: nav.startTime,
          domInteractive: nav.domInteractive,
          domContentLoadedEventEnd: nav.domContentLoadedEventEnd,
          loadEventEnd: nav.loadEventEnd,
          responseStart: nav.responseStart,
          responseEnd: nav.responseEnd,
          transferSize: nav.transferSize,
          encodedBodySize: nav.encodedBodySize,
          decodedBodySize: nav.decodedBodySize,
        } : null,
        paints,
        resourceCount: resources.length,
        resourceTransferBytes: resources.reduce((sum, r) => sum + (r.transferSize || 0), 0),
      };
    });
    return mcpText(metrics);
  });

  server.registerTool("web_audit", {
    description: "Run a lightweight UI/accessibility/debug audit for common issues."
  }, async () => {
    await B.ensure();
    const pageAudit = await B.page!.evaluate(() => {
      const images = Array.from(document.images);
      const buttons = Array.from(document.querySelectorAll("button"));
      const inputs = Array.from(document.querySelectorAll("input,select,textarea"));
      const all = Array.from(document.querySelectorAll<HTMLElement>("body *"));
      const overflow = all
        .filter((el) => el.scrollWidth > el.clientWidth + 2)
        .slice(0, 50)
        .map((el) => ({
          tag: el.tagName,
          id: el.id || null,
          className: String(el.className || ""),
          scrollWidth: el.scrollWidth,
          clientWidth: el.clientWidth,
        }));

      const unlabeledInputs = inputs.filter((el) => {
        const id = el.getAttribute("id");
        const hasForLabel = id ? Boolean(document.querySelector(`label[for="${CSS.escape(id)}"]`)) : false;
        return !hasForLabel && !el.getAttribute("aria-label") && !el.getAttribute("aria-labelledby") && !el.getAttribute("title");
      });

      return {
        title: document.title,
        h1Count: document.querySelectorAll("h1").length,
        missingImageAlt: images.filter((img) => !img.hasAttribute("alt")).length,
        unnamedButtons: buttons.filter((b) => !(b.innerText || b.getAttribute("aria-label") || b.getAttribute("title"))).length,
        unlabeledInputs: unlabeledInputs.length,
        horizontalOverflow: overflow,
        bodyScrollWidth: document.body.scrollWidth,
        viewportWidth: window.innerWidth,
      };
    });

    return mcpText({
      ...pageAudit,
      consoleErrors: B.consoleEvents.filter((x) => x.type === "error").length + B.pageErrors.length,
      networkErrors: B.networkEvents.filter((x) => x.kind === "response" && (x.status ?? 0) >= 400).length,
    });
  });

  server.registerTool("web_recording_start", {
    description: "Start recording Zagent Web actions for deterministic replay."
  }, async () => {
    B.actionSteps.splice(0);
    B.actionRecording = true;
    return mcpText({ ok: true });
  });

  server.registerTool("web_recording_stop", {
    description: "Stop action recording and save the steps as JSON.",
    inputSchema: z.object({ name: z.string().optional() }),
  }, async ({ name }) => {
    B.actionRecording = false;
    const filename = safeName(name?.trim() || `recording_${Date.now()}.json`);
    const output = path.join(B.abs(B.settings.recordingsDir), filename.endsWith(".json") ? filename : filename + ".json");
    await fs.writeFile(output, JSON.stringify(B.actionSteps, null, 2), "utf8");
    return mcpText({ path: output, steps: B.actionSteps.length });
  });

  server.registerTool("web_recording_replay", {
    description: "Replay a previously saved Zagent Web action recording.",
    inputSchema: z.object({
      path: z.string().min(1),
      stopOnError: z.boolean().default(true),
    }),
  }, async ({ path: recordingPath, stopOnError }) => {
    await B.ensure();
    const file = B.abs(recordingPath);
    const steps = JSON.parse(await fs.readFile(file, "utf8")) as Array<{ action: string; args: Record<string, unknown> }>;
    const results: unknown[] = [];
    for (const [index, step] of steps.entries()) {
      try {
        const a = step.args;
        switch (step.action) {
          case "open":
            await B.open(String(a.input), (a.waitUntil as any) ?? "domcontentloaded");
            break;
          case "click":
            await B.page!.locator(String(a.selector)).first().click();
            break;
          case "double_click":
            await B.page!.locator(String(a.selector)).first().dblclick();
            break;
          case "right_click":
            await B.page!.locator(String(a.selector)).first().click({ button: "right" });
            break;
          case "hover":
            await B.page!.locator(String(a.selector)).first().hover();
            break;
          case "fill":
            await B.page!.locator(String(a.selector)).first().fill(String(a.value ?? ""));
            break;
          case "clear":
            await B.page!.locator(String(a.selector)).first().clear();
            break;
          case "type":
            await B.page!.locator(String(a.selector)).first().pressSequentially(String(a.text ?? ""), { delay: Number(a.delayMs ?? 0) });
            break;
          case "press":
            await B.page!.locator(String(a.selector)).first().press(String(a.key));
            break;
          case "keyboard_press":
            await B.page!.keyboard.press(String(a.key));
            break;
          case "select":
            await B.page!.locator(String(a.selector)).first().selectOption({ value: String(a.value) });
            break;
          case "check":
            await B.page!.locator(String(a.selector)).first().check();
            break;
          case "uncheck":
            await B.page!.locator(String(a.selector)).first().uncheck();
            break;
          case "scroll":
            await B.page!.mouse.wheel(Number(a.deltaX ?? 0), Number(a.deltaY ?? 600));
            break;
          case "reload":
            await B.page!.reload({ waitUntil: "domcontentloaded" });
            break;
          default:
            throw new Error(`Unsupported recorded action '${step.action}'.`);
        }
        results.push({ index, action: step.action, ok: true });
      } catch (error) {
        const item = { index, action: step.action, ok: false, error: error instanceof Error ? error.message : String(error) };
        results.push(item);
        if (stopOnError) break;
      }
    }
    return mcpText({ file, total: steps.length, results });
  });

  server.registerTool("web_recording_export_test", {
    description: "Export the current recorded actions as a standalone Google Chrome TypeScript automation script.",
    inputSchema: z.object({ name: z.string().optional() }),
  }, async ({ name }) => {
    const filename = safeName(name?.trim() || `zagent_recording_${Date.now()}.spec.ts`);
    const output = path.join(B.abs(B.settings.recordingsDir), filename.endsWith(".ts") ? filename : filename + ".ts");
    const lines = [
      'import { chromium } from "playwright-core";',
      "",
      'const browser = await chromium.launch({ channel: "chrome", headless: false });',
      "const context = await browser.newContext();",
      "const page = await context.newPage();",
      "try {",
    ];
    for (const step of B.actionSteps) {
      const a = step.args;
      if (step.action === "open") lines.push(`  await page.goto(${JSON.stringify(String(a.input))});`);
      else if (step.action === "click") lines.push(`  await page.locator(${JSON.stringify(String(a.selector))}).first().click();`);
      else if (step.action === "fill") lines.push(`  await page.locator(${JSON.stringify(String(a.selector))}).first().fill(${JSON.stringify(String(a.value ?? ""))});`);
      else if (step.action === "press") lines.push(`  await page.locator(${JSON.stringify(String(a.selector))}).first().press(${JSON.stringify(String(a.key))});`);
      else if (step.action === "reload") lines.push("  await page.reload();");
      else lines.push(`  // TODO recorded action: ${step.action} ${JSON.stringify(a)}`);
    }
    lines.push("} finally {", "  await browser.close();", "}", "");
    await fs.writeFile(output, lines.join("\n"), "utf8");
    return mcpText({ path: output, steps: B.actionSteps.length });
  });

  server.registerTool("web_save_pdf", {
    description: "Save the active page as PDF when supported by the current browser.",
    inputSchema: z.object({
      name: z.string().optional(),
      format: z.enum(["A4", "Letter", "Legal"]).default("A4"),
      printBackground: z.boolean().default(true),
    }),
  }, async ({ name, format, printBackground }) => {
    await B.ensure();
    const filename = safeName(name?.trim() || `page_${Date.now()}.pdf`);
    const output = path.join(B.abs(B.settings.downloadsDir), filename.endsWith(".pdf") ? filename : filename + ".pdf");
    await B.page!.pdf({ path: output, format, printBackground });
    return mcpText({ path: output });
  });
}

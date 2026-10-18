import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";
import { registerVisualTools } from "../src/tools/visual.js";

const temp = await fs.mkdtemp(path.join(os.tmpdir(), "zagent-frame-smoke-"));
try {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    recordVideo: { dir: temp, size: { width: 320, height: 240 } },
  });
  const page = await context.newPage();
  await page.setContent("<html><body><h1>Zagent visual frame smoke</h1></body></html>");
  await page.waitForTimeout(700);
  const video = page.video();
  assert.ok(video);
  await context.close();
  await browser.close();
  const videoPath = await video!.path();

  const handlers = new Map<string, Function>();
  const fakeServer = {
    registerTool(name: string, _options: unknown, handler: Function) {
      handlers.set(name, handler);
    },
  };
  registerVisualTools(fakeServer as any);
  const handler = handlers.get("web_visual_frame_extract");
  assert.ok(handler);

  const result = await handler!({
    videoPath,
    atSeconds: 0.1,
    name: "frame-smoke",
    label: "frame-smoke",
    sessionId: "frame-smoke-session",
  });
  assert.ok(Array.isArray(result.content));
  assert.ok(result.content.some((item: any) =>
    item.type === "image" &&
    typeof item.data === "string" &&
    item.data.length > 0
  ));
  const text = result.content.find((item: any) => item.type === "text")?.text ?? "";
  assert.match(text, /frame-smoke-session/);
  console.log("VISUAL_FRAME_SMOKE_PASS", videoPath);
} finally {
  await fs.rm(temp, { recursive: true, force: true });
}

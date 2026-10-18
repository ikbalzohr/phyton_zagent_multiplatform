import fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import {
  visualArtifactStore as store,
  type VisualArtifactSource,
} from "../visual/VisualArtifactStore.js";
import { mcpText } from "../utils/json.js";

const execFileAsync = promisify(execFile);
const sourceSchema = z.enum(["web", "arcmap", "video", "file"]);

function safeName(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, "_");
}

async function mcpVisual(
  artifact: Awaited<ReturnType<typeof store.latest>> | null,
  envelope: Record<string, unknown> = {}
): Promise<any> {
  if (!artifact) return mcpText({ ...envelope, artifact: null });
  await store.validate(artifact);

  const details: Record<string, unknown> = {
    ...envelope,
    artifact,
  };
  const content: any[] = [{
    type: "text",
    text: JSON.stringify(details, null, 2),
  }];

  if (artifact.mimeType.startsWith("image/")) {
    const maxImageBytes = 12 * 1024 * 1024;
    if (artifact.bytes <= maxImageBytes) {
      content.push({
        type: "image",
        data: (await fs.readFile(artifact.artifactPath)).toString("base64"),
        mimeType: artifact.mimeType,
      });
    } else {
      details.imageOmittedReason =
        `Image is ${artifact.bytes} bytes; limit is ${maxImageBytes} bytes.`;
      content[0].text = JSON.stringify(details, null, 2);
    }
  }

  return { content };
}

async function capture(input: {
  name?: string;
  fullPage: boolean;
  selector?: string;
  label?: string;
  sessionId?: string;
}) {
  await B.ensure();
  await store.ensure();
  const name = safeName(input.name?.trim() || "snapshot");
  const output = store.stagingPath(name, ".png");
  if (input.selector) {
    await B.page!.locator(input.selector).first().screenshot({ path: output });
  } else {
    await B.page!.screenshot({ path: output, fullPage: input.fullPage });
  }
  try {
    return await store.publish({
      path: output,
      source: "web",
      kind: input.selector ? "element-screenshot" : input.fullPage ? "full-page-screenshot" : "viewport-screenshot",
      label: input.label,
      sessionId: input.sessionId,
      metadata: {
        url: B.page!.url(),
        title: await B.page!.title().catch(() => null),
        fullPage: input.fullPage,
        selector: input.selector ?? null,
      },
    });
  } finally {
    await fs.unlink(output).catch(() => undefined);
  }
}

async function fileExists(candidate: string): Promise<boolean> {
  try {
    await fs.access(candidate);
    return true;
  } catch {
    return false;
  }
}

async function resolveFfmpegPath(): Promise<string> {
  for (const configured of [
    process.env.ZAGENT_FFMPEG_PATH?.trim(),
    process.env.PLAYWRIGHT_FFMPEG_PATH?.trim(),
  ]) {
    if (configured) return configured;
  }

  const engineRoot =
    process.env.ZAGENT_WEB_ENGINE_ROOT?.trim() ||
    process.cwd();
  for (const candidate of [
    path.resolve(engineRoot, "..", "runtime", "ffmpeg", "ffmpeg.exe"),
    path.resolve(engineRoot, "..", "runtime", "ffmpeg", "ffmpeg-win64.exe"),
  ]) {
    if (await fileExists(candidate)) return candidate;
  }

  const playwrightRoot =
    process.env.PLAYWRIGHT_BROWSERS_PATH?.trim() ||
    (process.env.LOCALAPPDATA
      ? path.join(process.env.LOCALAPPDATA, "ms-playwright")
      : "");
  if (playwrightRoot) {
    try {
      const folders = (await fs.readdir(playwrightRoot))
        .filter((name) => name.startsWith("ffmpeg-"))
        .sort()
        .reverse();
      for (const folder of folders) {
        for (const binary of ["ffmpeg-win64.exe", "ffmpeg.exe"]) {
          const candidate = path.join(playwrightRoot, folder, binary);
          if (await fileExists(candidate)) return candidate;
        }
      }
    } catch {
      // Fall through to PATH.
    }
  }

  return "ffmpeg";
}

async function extractFrame(input: {
  videoPath: string;
  atSeconds: number;
  name?: string;
  label?: string;
  sessionId?: string;
}) {
  const video = B.abs(input.videoPath);
  await fs.stat(video);
  await store.ensure();
  const output = store.stagingPath(safeName(input.name?.trim() || "frame"), ".png");
  const ffmpeg = await resolveFfmpegPath();

  try {
    await execFileAsync(ffmpeg, [
      "-hide_banner",
      "-loglevel", "error",
      "-ss", String(input.atSeconds),
      "-i", video,
      "-frames:v", "1",
      "-y",
      output,
    ], {
      windowsHide: true,
      timeout: 60_000,
      maxBuffer: 1024 * 1024,
    });
  } catch (error) {
    throw new Error(
      "FFmpeg frame extraction failed. Configure ZAGENT_FFMPEG_PATH or install the Zagent Web FFmpeg runtime. " +
      String(error)
    );
  }

  try {
    return await store.publish({
      path: output,
      source: "video",
      kind: "video-frame",
      label: input.label,
      sessionId: input.sessionId,
      metadata: {
        videoPath: video,
        atSeconds: input.atSeconds,
      },
    });
  } finally {
    await fs.unlink(output).catch(() => undefined);
  }
}

export function registerVisualTools(server: McpServer): void {
  server.registerTool("web_visual_snapshot", {
    description: "Capture the current Chrome visual state and publish it to the shared Zagent Visual Artifact Store.",
    inputSchema: z.object({
      name: z.string().optional(),
      label: z.string().optional(),
      fullPage: z.boolean().default(false),
      selector: z.string().optional(),
      sessionId: z.string().optional(),
    }),
  }, async ({ name, label, fullPage, selector, sessionId }) =>
    mcpVisual(await capture({ name, label, fullPage, selector, sessionId })));

  server.registerTool("web_visual_latest", {
    description: "Return the newest shared visual artifact manifest, optionally filtered by source.",
    inputSchema: z.object({
      source: sourceSchema.optional(),
    }),
  }, async ({ source }) =>
    mcpVisual(
      await store.latest(source as VisualArtifactSource | undefined),
      { root: store.root }
    ));

  server.registerTool("web_visual_list", {
    description: "List recent shared visual artifacts without loading image/video bytes.",
    inputSchema: z.object({
      source: sourceSchema.optional(),
      limit: z.number().int().min(1).max(500).default(50),
    }),
  }, async ({ source, limit }) =>
    mcpText({
      root: store.root,
      artifacts: await store.list({
        source: source as VisualArtifactSource | undefined,
        limit,
      }),
    }));

  server.registerTool("web_visual_ingest", {
    description: "Publish an existing local image/video into the shared visual artifact store with device provenance.",
    inputSchema: z.object({
      path: z.string().min(1),
      source: sourceSchema.default("file"),
      kind: z.string().min(1).default("visual-artifact"),
      label: z.string().optional(),
      sessionId: z.string().optional(),
    }),
  }, async ({ path: inputPath, source, kind, label, sessionId }) =>
    mcpVisual(await store.publish({
      path: B.abs(inputPath),
      source: source as VisualArtifactSource,
      kind,
      label,
      sessionId,
    })));

  server.registerTool("web_visual_prune", {
    description: "Prune old shared visual artifacts by count and optional age.",
    inputSchema: z.object({
      maxArtifacts: z.number().int().min(1).max(5000).default(200),
      maxAgeHours: z.number().positive().max(24 * 365).optional(),
    }),
  }, async ({ maxArtifacts, maxAgeHours }) =>
    mcpText(await store.prune({ maxArtifacts, maxAgeHours })));

  server.registerTool("web_visual_frame_extract", {
    description: "Extract one PNG frame from a local Web video and publish it for model inspection.",
    inputSchema: z.object({
      videoPath: z.string().min(1),
      atSeconds: z.number().min(0),
      name: z.string().optional(),
      label: z.string().optional(),
      sessionId: z.string().optional(),
    }),
  }, async ({ videoPath, atSeconds, name, label, sessionId }) =>
    mcpVisual(await extractFrame({
      videoPath,
      atSeconds,
      name,
      label,
      sessionId,
    })));

  server.registerTool("web_visual_act_and_observe", {
    description: "Execute one scoped Chrome action chosen after visual reasoning, then publish and return the post-action visual observation.",
    inputSchema: z.object({
      action: z.enum(["click", "fill", "press", "hover", "scroll", "wait"]),
      selector: z.string().optional(),
      value: z.string().optional(),
      key: z.string().optional(),
      deltaX: z.number().default(0),
      deltaY: z.number().default(600),
      milliseconds: z.number().int().min(0).max(30_000).default(250),
      label: z.string().optional(),
      sessionId: z.string().optional(),
    }),
  }, async ({
    action,
    selector,
    value,
    key,
    deltaX,
    deltaY,
    milliseconds,
    label,
    sessionId,
  }) => {
    if ((action === "click" || action === "fill" || action === "hover") && !selector) {
      throw new Error("selector is required for " + action + ".");
    }
    if (action === "press" && !key) {
      throw new Error("key is required for press.");
    }

    await B.ensure();
    const before = await capture({
      name: "feedback_before",
      fullPage: false,
      label: label ? label + " · before" : "feedback-before",
      sessionId,
    });

    if (action === "click") {
      if (!selector) throw new Error("selector is required for click.");
      await B.page!.locator(selector).first().click();
    } else if (action === "fill") {
      if (!selector) throw new Error("selector is required for fill.");
      await B.page!.locator(selector).first().fill(value ?? "");
    } else if (action === "press") {
      if (!key) throw new Error("key is required for press.");
      if (selector) await B.page!.locator(selector).first().press(key);
      else await B.page!.keyboard.press(key);
    } else if (action === "hover") {
      if (!selector) throw new Error("selector is required for hover.");
      await B.page!.locator(selector).first().hover();
    } else if (action === "scroll") {
      await B.page!.mouse.wheel(deltaX, deltaY);
    } else {
      await B.page!.waitForTimeout(milliseconds);
    }

    if (action !== "wait" && milliseconds > 0) {
      await B.page!.waitForTimeout(milliseconds);
    }

    const after = await capture({
      name: "feedback_after",
      fullPage: false,
      label: label ? label + " · after" : "feedback-after",
      sessionId,
    });

    return mcpVisual(after, {
      loop: "observe-reason-act-observe",
      action,
      beforeArtifact: before,
    });
  });

  server.registerTool("web_visual_store_status", {
    description: "Return the shared visual artifact store path and current latest artifact.",
  }, async () => {
    await store.ensure();
    return mcpText({
      ok: true,
      root: store.root,
      latest: await store.latest(),
    });
  });
}

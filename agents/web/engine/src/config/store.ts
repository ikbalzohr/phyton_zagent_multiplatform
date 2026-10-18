import fs from "node:fs/promises";
import path from "node:path";
import { CONFIG_DIR, SETTINGS_FILE, TARGETS_FILE } from "./paths.js";
import type { WebTarget, ZagentWebSettings } from "../types/config.js";

async function readJson<T>(file: string): Promise<T> {
  return JSON.parse(await fs.readFile(file, "utf8")) as T;
}

async function writeJson(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = file + ".tmp";
  await fs.writeFile(tmp, JSON.stringify(value, null, 2), "utf8");
  await fs.rename(tmp, file);
}

export async function saveSettings(settings: ZagentWebSettings): Promise<void> {
  await writeJson(SETTINGS_FILE, settings);
}
export async function loadSettings(): Promise<ZagentWebSettings> {
  await fs.mkdir(CONFIG_DIR, { recursive: true });
  return readJson<ZagentWebSettings>(SETTINGS_FILE);
}

export async function loadTargets(): Promise<WebTarget[]> {
  try {
    const data = await readJson<{ targets: WebTarget[] }>(TARGETS_FILE);
    return data.targets ?? [];
  } catch {
    return [];
  }
}

export async function saveTargets(targets: WebTarget[]): Promise<void> {
  await writeJson(TARGETS_FILE, { targets });
}


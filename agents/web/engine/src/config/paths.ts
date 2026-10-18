import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function envPath(name: string, fallback: string): string {
  const value = process.env[name]?.trim();
  return path.resolve(value || fallback);
}

export const ENGINE_ROOT = envPath(
  "ZAGENT_WEB_ENGINE_ROOT",
  path.resolve(__dirname, "../..")
);
export const DATA_ROOT = envPath(
  "ZAGENT_WEB_DATA_ROOT",
  path.join(ENGINE_ROOT, "data")
);
export const CONFIG_DIR = envPath(
  "ZAGENT_WEB_CONFIG_DIR",
  path.join(DATA_ROOT, "config")
);
export const RUNTIME_DIR = envPath(
  "ZAGENT_WEB_RUNTIME_DIR",
  path.join(DATA_ROOT, "runtime")
);
export const ARTIFACTS_DIR = envPath(
  "ZAGENT_WEB_ARTIFACTS_DIR",
  path.join(DATA_ROOT, "artifacts")
);
export const LOG_DIR = envPath(
  "ZAGENT_WEB_LOG_DIR",
  path.join(DATA_ROOT, "logs")
);

export const ROOT = DATA_ROOT;
export const SETTINGS_FILE = path.join(CONFIG_DIR, "settings.json");
export const TARGETS_FILE = path.join(CONFIG_DIR, "targets.json");
export const BRIDGE_FILE = path.join(CONFIG_DIR, "bridge.json");

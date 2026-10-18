import { URL } from "node:url";
import type { ZagentWebSettings } from "../types/config.js";

export function validateNavigableUrl(
  raw: string,
  settings: ZagentWebSettings,
  options: { bypassHostAllowlist?: boolean } = {}
): string {
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("Zagent Web only allows http/https URLs.");
  }
  const host = url.hostname.toLowerCase();
  const allowed = new Set(settings.allowedHosts.map((x) => x.toLowerCase()));
  if (!options.bypassHostAllowlist &&
      !settings.allowExternalHosts &&
      !allowed.has(host)) {
    throw new Error(`Host '${host}' is not allowed. Add it to config/settings.json or the approved target registry.`);
  }
  return url.toString();
}

export function redactHeaders(
  headers: Record<string, string>,
  names: string[],
): Record<string, string> {
  const deny = new Set(names.map((x) => x.toLowerCase()));
  return Object.fromEntries(
    Object.entries(headers).map(([k, v]) => [k, deny.has(k.toLowerCase()) ? "[REDACTED]" : v]),
  );
}

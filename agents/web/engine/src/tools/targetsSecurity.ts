import fs from "node:fs/promises";
import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { SETTINGS_FILE } from "../config/paths.js";
import { loadSettings } from "../config/store.js";
import { mcpText } from "../utils/json.js";

async function saveSettingsPatch(mutator: (settings: Awaited<ReturnType<typeof loadSettings>>) => void) {
  const settings = await loadSettings();
  mutator(settings);
  const tmp = SETTINGS_FILE + ".tmp";
  await fs.writeFile(tmp, JSON.stringify(settings, null, 2), "utf8");
  await fs.rename(tmp, SETTINGS_FILE);
  B.settings = settings;
  return settings;
}

export function registerTargetSecurityTools(server: McpServer): void {
  server.registerTool("web_targets", {
    description: "List approved named web targets."
  }, async () => mcpText(await B.targets()));

  server.registerTool("web_target_add", {
    description: "Add or update an approved named web target.",
    inputSchema: z.object({
      name: z.string().min(1),
      url: z.string().url(),
      description: z.string().optional(),
      enabled: z.boolean().default(true),
    }),
  }, async ({ name, url, description, enabled }) => {
    return mcpText(await B.addTarget({ name, url, description, enabled }));
  });

  server.registerTool("web_target_remove", {
    description: "Remove a named web target.",
    inputSchema: z.object({ name: z.string().min(1) }),
  }, async ({ name }) => mcpText(await B.removeTarget(name)));

  server.registerTool("web_target_test", {
    description: "Open a named target and report navigation result.",
    inputSchema: z.object({ name: z.string().min(1) }),
  }, async ({ name }) => mcpText(await B.testTarget(name)));

  server.registerTool("web_security_status", {
    description: "Show Zagent Web navigation and power-tool security settings."
  }, async () => mcpText({
    allowedHosts: B.settings.allowedHosts,
    allowExternalHosts: B.settings.allowExternalHosts,
    javascriptEvaluation: B.settings.enableJavascriptEvaluation,
    networkInterception: B.settings.enableNetworkInterception,
    redactedHeaders: B.settings.redactHeaders,
  }));

  server.registerTool("web_allow_host_add", {
    description: "Add a hostname to the approved navigation allowlist.",
    inputSchema: z.object({ host: z.string().min(1) }),
  }, async ({ host }) => {
    const normalized = host.trim().toLowerCase();
    const settings = await saveSettingsPatch((s) => {
      if (!s.allowedHosts.map((x) => x.toLowerCase()).includes(normalized)) s.allowedHosts.push(normalized);
    });
    return mcpText({ ok: true, allowedHosts: settings.allowedHosts });
  });

  server.registerTool("web_allow_host_remove", {
    description: "Remove a hostname from the approved navigation allowlist.",
    inputSchema: z.object({ host: z.string().min(1) }),
  }, async ({ host }) => {
    const normalized = host.trim().toLowerCase();
    if (["localhost", "127.0.0.1", "::1"].includes(normalized)) {
      throw new Error("Core localhost hosts cannot be removed.");
    }
    const settings = await saveSettingsPatch((s) => {
      s.allowedHosts = s.allowedHosts.filter((x) => x.toLowerCase() !== normalized);
    });
    return mcpText({ ok: true, allowedHosts: settings.allowedHosts });
  });

  server.registerTool("web_external_hosts_set", {
    description: "Enable or disable navigation to hosts outside the allowlist.",
    inputSchema: z.object({ enabled: z.boolean() }),
  }, async ({ enabled }) => {
    const settings = await saveSettingsPatch((s) => {
      s.allowExternalHosts = enabled;
    });
    return mcpText({ ok: true, allowExternalHosts: settings.allowExternalHosts });
  });

  server.registerTool("web_js_eval_set", {
    description: "Enable or disable the web_evaluate_js power tool.",
    inputSchema: z.object({ enabled: z.boolean() }),
  }, async ({ enabled }) => {
    const settings = await saveSettingsPatch((s) => {
      s.enableJavascriptEvaluation = enabled;
    });
    return mcpText({ ok: true, enableJavascriptEvaluation: settings.enableJavascriptEvaluation });
  });
}

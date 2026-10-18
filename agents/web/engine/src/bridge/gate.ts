import type { McpServer } from "@modelcontextprotocol/server";
import { executionContext } from '../server/executionContext.js';
import type { Page } from "playwright-core";
import { browserManager as B } from "../browser/BrowserManager.js";
import { bridge, type Target } from "./Bridge.js";

export const PAGE_TOOLS = new Set(`web_open web_reload web_back web_forward web_get_url web_get_title web_get_page_state
web_click web_double_click web_right_click web_hover web_drag_drop web_fill web_clear web_focus
web_press web_keyboard_press web_select web_check web_uncheck web_scroll web_scroll_into_view
web_get_html web_screenshot web_screenshot_full_page web_screenshot_element web_inspect web_get_text
web_get_elements web_get_element web_get_attribute web_get_bounds web_get_accessibility_tree
web_find web_find_text web_find_role web_visual_snapshot web_visual_act_and_observe`.split(/\s+/));

const CONTROL_TOOLS = new Set([
  "web_ping", "web_browser_status", "web_runtime_info",
  "web_bridge_pair", "web_bridge_pair_status", "web_bridge_profile_binding", "web_bridge_authorize_request", "web_bridge_reconnect",
  "web_bridge_status", "web_bridge_revoke", "web_bridge_disconnect", "web_bridge_tabs", "web_bridge_select_tab",
  "web_native_chrome_attach", "web_native_chrome_detach",
  "web_chrome_profiles", "web_chrome_launch_profile", "web_chrome_launch_status",
  "web_tabs", "web_new_tab", "web_switch_tab", "web_close_tab",
  "web_visual_latest", "web_visual_list", "web_visual_store_status", "web_visual_prune"
]);

function bridgeOrigin(rawUrl: string): string {
  const raw = String(rawUrl || "").trim();
  if (!raw || raw === "about:blank") return "zagent://blank";
  if (raw.startsWith("chrome://newtab")) return "zagent://newtab";
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("Only HTTP(S), about:blank, or Chrome new-tab pages can be authorized");
  }
  return url.origin;
}

export async function targetFor(page: Page): Promise<Target> {
  if (!B.isNativeAttached() || page.isClosed()) throw new Error("Native Chrome target unavailable");
  const session = await page.context().newCDPSession(page);
  try {
    const { targetInfo } = await session.send("Target.getTargetInfo");
    const { windowId } = await session.send("Browser.getWindowForTarget", { targetId: targetInfo.targetId });
    return {
      id: targetInfo.targetId,
      windowId,
      origin: bridgeOrigin(page.url())
    };
  } finally {
    await session.detach();
  }
}

export async function resolveTargets(ids: string[]): Promise<Target[]> {
  const remaining = new Set(ids);
  const found: Target[] = [];
  for (const page of B.context?.pages() ?? []) {
    const target = await targetFor(page).catch(() => null);
    if (target && remaining.delete(target.id)) found.push(target);
  }
  if (remaining.size || !found.length) throw new Error("Selected tabs are not available in the attached Chrome");
  return found;
}

export async function authorizedTabs() {
  const tabs = [];
  for (const page of B.context?.pages() ?? []) {
    try {
      const target = await targetFor(page);
      bridge.assertTarget(target);
      tabs.push({ ...target, title: await page.title(), url: page.url(), active: B.page === page });
    } catch {}
  }
  return tabs;
}

export async function selectTab(id: string) {
  for (const page of B.context?.pages() ?? []) {
    const target = await targetFor(page).catch(() => null);
    if (target?.id === id) {
      bridge.assertTarget(target);
      B.page = page;
      await page.bringToFront();
      return { selected: id };
    }
  }
  throw new Error("Authorized tab not found");
}

export async function authorizeTool(name: string) {
  if (!await bridge.refresh()) return;
  if (CONTROL_TOOLS.has(name)) return;
  if (!PAGE_TOOLS.has(name)) throw new Error(`Tool ${name} is unavailable in bridge protection mode; use scoped page tools`);
  if (!B.page || B.page.isClosed()) throw new Error("Select an authorized tab with web_bridge_select_tab");
  bridge.assertTarget(await targetFor(B.page));
}

export function installBridgeGate(server: McpServer) {
  const register = server.registerTool.bind(server) as (...args: any[]) => any;
  (server as any).registerTool = (name: string, config: unknown, callback: (...args: any[]) => any) =>
    register(name, config, (...args: any[]) => {
      const invoke = async () => {
        const ctx = executionContext.getStore();
        if (ctx && Date.now()/1000 >= ctx.expires_at) throw new Error('CONTEXT_EXPIRED_WHILE_QUEUED');
        await authorizeTool(name);
        const required = await bridge.refresh();
        if (required && name === "web_native_chrome_attach" && args[0]?.endpoint) {
          throw new Error("Custom CDP endpoints are disabled under bridge protection");
        }
        if (required && ["web_native_chrome_attach", "web_native_chrome_detach"].includes(name)) bridge.revoke();
        const result = await callback(...args);
        if (required && PAGE_TOOLS.has(name)) await authorizeTool(name);
        if (required && ["web_native_chrome_attach", "web_native_chrome_detach"].includes(name)) {
          return {
            content: [{ type: "text", text: JSON.stringify({ nativeAttached: B.isNativeAttached(), authorizationRevoked: true }) }]
          };
        }
        return result;
      };
      if (["web_bridge_revoke", "web_bridge_disconnect", "web_bridge_status", "web_bridge_pair_status"].includes(name)) {
        return invoke();
      }
      return bridge.refresh().then(required => required ? bridge.serial(invoke) : invoke());
    });
}

import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { browserManager as B } from "../browser/BrowserManager.js";
import { bridge } from "../bridge/Bridge.js";
import { authorizedTabs, selectTab, targetFor } from "../bridge/gate.js";
import { mcpText } from "../utils/json.js";

async function protectedMode(): Promise<boolean> {
  return bridge.refresh();
}

async function tabList() {
  if (await protectedMode()) {
    if (!B.isNativeAttached()) throw new Error("Native Chrome is not attached.");
    return authorizedTabs();
  }
  await B.ensure();
  const pages = B.context!.pages();
  return Promise.all(pages.map(async (p, index) => ({
    index,
    active: p === B.page,
    url: p.url(),
    title: await p.title().catch(() => ""),
  })));
}

export function registerTabDialogTools(server: McpServer): void {
  server.registerTool("web_tabs", {
    description: "List browser tabs/pages. Under bridge protection, only authorized native Chrome tabs are returned."
  }, async () => mcpText(await tabList()));

  server.registerTool("web_new_tab", {
    description: "Open a new tab. Under bridge protection this requires a window/all lease with new-tab permission. Blank tabs are allowed; URL navigation is governed by the active bridge lease.",
    inputSchema: z.object({ urlOrTarget: z.string().optional() }),
  }, async ({ urlOrTarget }) => {
    if (await protectedMode()) {
      if (!B.isNativeAttached() || !B.context || !B.page) throw new Error("Attach native Chrome and select an authorized tab first.");
      const sourcePage = B.page;
      const sourceTarget = await targetFor(sourcePage);
      bridge.assertNewTab(sourceTarget);
      const url = urlOrTarget
        ? await B.resolveTarget(urlOrTarget, { bridgeAuthorized: true })
        : null;
      const page = await B.context.newPage();
      try {
        if (url) {
          await page.goto(url, { waitUntil: "domcontentloaded" });
        }
        B.page = page;
        const target = await targetFor(page);
        bridge.enrollNewTarget(sourceTarget, target);
        await page.bringToFront();
        return mcpText(await authorizedTabs());
      } catch (error) {
        await page.close().catch(() => undefined);
        B.page = sourcePage;
        throw error;
      }
    }

    await B.ensure();
    B.page = await B.context!.newPage();
    if (urlOrTarget) await B.open(urlOrTarget);
    return mcpText(await tabList());
  });

  server.registerTool("web_switch_tab", {
    description: "Switch the active tab by zero-based index. Under bridge protection, the index refers only to authorized tabs.",
    inputSchema: z.object({ index: z.number().int().min(0) }),
  }, async ({ index }) => {
    if (await protectedMode()) {
      const tabs = await authorizedTabs();
      const target = tabs[index];
      if (!target) throw new Error(`Authorized tab index ${index} does not exist.`);
      await selectTab(target.id);
      return mcpText(await authorizedTabs());
    }

    await B.ensure();
    const pages = B.context!.pages();
    if (!pages[index]) throw new Error(`Tab index ${index} does not exist.`);
    B.page = pages[index];
    await B.page.bringToFront();
    return mcpText(await tabList());
  });

  server.registerTool("web_close_tab", {
    description: "Close a tab by zero-based index. Under bridge protection, only an authorized tab may be closed.",
    inputSchema: z.object({ index: z.number().int().min(0) }),
  }, async ({ index }) => {
    if (await protectedMode()) {
      const tabs = await authorizedTabs();
      const selected = tabs[index];
      if (!selected) throw new Error(`Authorized tab index ${index} does not exist.`);
      await selectTab(selected.id);
      const page = B.page!;
      await page.close();
      bridge.removeTarget(selected.id);
      const remaining = await authorizedTabs();
      if (remaining[0]) await selectTab(remaining[0].id);
      else B.page = null;
      return mcpText(remaining);
    }

    await B.ensure();
    const pages = B.context!.pages();
    const target = pages[index];
    if (!target) throw new Error(`Tab index ${index} does not exist.`);
    await target.close();
    const remaining = B.context!.pages();
    if (remaining.length) B.page = remaining.at(-1)!;
    else B.page = await B.context!.newPage();
    return mcpText(await tabList());
  });

  server.registerTool("web_dialog_info", {
    description: "Return information about the most recent browser dialog."
  }, async () => mcpText(B.dialogs.at(-1) ?? null));

  server.registerTool("web_dialog_accept", {
    description: "Accept the currently open browser dialog.",
    inputSchema: z.object({ promptText: z.string().optional() }),
  }, async ({ promptText }) => {
    if (!B.activeDialog) throw new Error("No active browser dialog.");
    await B.activeDialog.accept(promptText);
    B.activeDialog = null;
    return mcpText({ ok: true });
  });

  server.registerTool("web_dialog_dismiss", {
    description: "Dismiss the currently open browser dialog."
  }, async () => {
    if (!B.activeDialog) throw new Error("No active browser dialog.");
    await B.activeDialog.dismiss();
    B.activeDialog = null;
    return mcpText({ ok: true });
  });
}

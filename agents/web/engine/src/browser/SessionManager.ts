import fs from "node:fs/promises";
import path from "node:path";
import type { BrowserContextOptions } from "playwright-core";
import { browserManager, BrowserManager } from "./BrowserManager.js";
import { RUNTIME_DIR } from "../config/paths.js";
import type { BrowserName, SessionIsolationMode } from "../types/config.js";

export interface SessionOpenOptions {
  browser?: BrowserName;
  headless?: boolean;
  restoreState?: boolean;
  isolationMode?: SessionIsolationMode;
}

type EffectiveMode = "context" | "tabs";

type SessionState = {
  id: string;
  manager: BrowserManager;
  mode: EffectiveMode;
  createdAt: number;
  lastUsedAt: number;
  storagePath: string;
};

function safeId(value: string): string {
  const out = value.trim().replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 120);
  if (!out) throw new Error("sessionId is required.");
  return out;
}

export class BrowserSessionManager {
  private readonly sessions = new Map<string, SessionState>();
  private readonly tails = new Map<string, Promise<void>>();

  private storagePath(sessionId: string): string {
    return path.join(RUNTIME_DIR, "sessions", `${safeId(sessionId)}.storage.json`);
  }

  private resolveMode(options: SessionOpenOptions): EffectiveMode {
    if (browserManager.isNativeAttached()) return "tabs";
    const requested = options.isolationMode ?? browserManager.settings.sessionIsolationMode ?? "auto";
    if (requested === "context") return "context";
    if (requested === "tabs") return "tabs";
    const effectiveHeadless = options.headless ?? browserManager.settings.headless;
    return effectiveHeadless ? "context" : "tabs";
  }

  private async ensureBaseRuntime(options: SessionOpenOptions): Promise<void> {
    if (!browserManager.settings) await browserManager.init();
    if (!browserManager.browser?.isConnected() && browserManager.settings.runtimeMode !== "native_attach") {
      await browserManager.start(options.browser, options.headless);
    }
    await browserManager.ensure();
    if (
      options.browser &&
      browserManager.browserName !== options.browser
    ) {
      throw new Error(
        "Shared runtime is already '" + browserManager.browserName + "'. Requested '" + options.browser + "'. Stop/restart the shared runtime to change browser."
      );
    }
  }

  async open(sessionId: string, options: SessionOpenOptions = {}): Promise<SessionState> {
    const id = safeId(sessionId);
    const existing = this.sessions.get(id);
    if (existing) {
      try {
        existing.lastUsedAt = Date.now();
        await existing.manager.ensure();
        return existing;
      } catch {
        await existing.manager.stop().catch(() => undefined);
        this.sessions.delete(id);
      }
    }

    await this.ensureBaseRuntime(options);
    const storagePath = this.storagePath(id);
    await fs.mkdir(path.dirname(storagePath), { recursive: true });
    const mode = this.resolveMode(options);
    const manager = new BrowserManager();

    if (mode === "tabs") {
      const page = await browserManager.context!.newPage();
      await manager.attachSharedContext(browserManager, browserManager.context!, false, page);
    } else {
      let storageState: BrowserContextOptions["storageState"] | undefined;
      if (options.restoreState !== false) {
        const hasState = await fs.access(storagePath).then(() => true).catch(() => false);
        if (hasState) storageState = storagePath;
      }

      const context = await browserManager.browser!.newContext({
        viewport: browserManager.settings.defaultViewport,
        acceptDownloads: true,
        storageState,
      });
      await manager.attachSharedContext(browserManager, context, true);
    }

    const state: SessionState = {
      id,
      manager,
      mode,
      createdAt: Date.now(),
      lastUsedAt: Date.now(),
      storagePath,
    };
    this.sessions.set(id, state);
    return state;
  }

  async get(sessionId: string): Promise<SessionState> {
    return this.open(sessionId);
  }

  async saveState(sessionId: string): Promise<unknown> {
    const state = await this.get(sessionId);
    await state.manager.ensure();
    await fs.mkdir(path.dirname(state.storagePath), { recursive: true });
    if (browserManager.isNativeAttached()) {
      return { ok: true, sessionId: state.id, mode: state.mode, stateSaved: false, reason: "native-chrome-uses-live-profile-state", sharedBrowser: true };
    }
    await state.manager.context!.storageState({ path: state.storagePath, indexedDB: true });
    state.lastUsedAt = Date.now();
    return {
      ok: true,
      sessionId: state.id,
      mode: state.mode,
      storagePath: state.storagePath,
      sharedBrowser: true,
    };
  }

  async close(sessionId: string, saveState = true): Promise<unknown> {
    const id = safeId(sessionId);
    const state = this.sessions.get(id);
    if (!state) return { ok: true, sessionId: id, closed: false, reason: "not-open" };
    if (saveState) {
      await this.saveState(id).catch(() => undefined);
    }
    await state.manager.stop();
    this.sessions.delete(id);
    this.tails.delete(id);
    return {
      ok: true,
      sessionId: id,
      closed: true,
      stateSaved: saveState,
      mode: state.mode,
      sharedBrowser: true,
    };
  }

  async closeAll(saveState = true): Promise<unknown> {
    const ids = [...this.sessions.keys()];
    const results = [];
    for (const id of ids) results.push(await this.close(id, saveState));
    return { ok: true, closed: results.length, results, sharedBrowserStillRunning: true };
  }

  async status(sessionId: string): Promise<unknown> {
    const id = safeId(sessionId);
    const state = this.sessions.get(id);
    if (!state) {
      return {
        ok: true,
        sessionId: id,
        open: false,
        storagePath: this.storagePath(id),
        sharedBrowser: true,
      };
    }
    return {
      ok: true,
      sessionId: id,
      open: true,
      mode: state.mode,
      sharedBrowser: true,
      createdAt: state.createdAt,
      lastUsedAt: state.lastUsedAt,
      storagePath: state.storagePath,
      browser: await state.manager.status(),
    };
  }

  async list(): Promise<unknown[]> {
    const out: unknown[] = [];
    for (const id of this.sessions.keys()) out.push(await this.status(id));
    return out;
  }

  async runExclusive<T>(sessionId: string, fn: (manager: BrowserManager) => Promise<T>): Promise<T> {
    const id = safeId(sessionId);
    const previous = this.tails.get(id) ?? Promise.resolve();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    this.tails.set(id, previous.then(() => gate));
    await previous;
    try {
      const state = await this.open(id);
      state.lastUsedAt = Date.now();
      return await fn(state.manager);
    } finally {
      release();
    }
  }
}

export const browserSessions = new BrowserSessionManager();

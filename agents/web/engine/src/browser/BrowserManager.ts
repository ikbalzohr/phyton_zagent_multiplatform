import fs from "node:fs/promises";
import path from "node:path";
import {
  chromium,
  devices,
  type Browser,
  type BrowserContext,
  type BrowserContextOptions,
  type ConsoleMessage,
  type Dialog,
  type Download,
  type Page,
  type Request,
  type Response,
} from "playwright-core";
import { DATA_ROOT } from "../config/paths.js";
import { loadSettings, loadTargets, saveTargets } from "../config/store.js";
import type { BrowserName, WebTarget, ZagentWebSettings } from "../types/config.js";
import { redactHeaders, validateNavigableUrl } from "../utils/security.js";

type NetworkRecord = {
  id: string;
  kind: "request" | "response";
  url: string;
  method?: string;
  status?: number;
  resourceType?: string;
  headers?: Record<string, string>;
  postData?: string | null;
  ok?: boolean;
  timestamp: number;
};

type ConsoleRecord = {
  type: string;
  text: string;
  location?: unknown;
  timestamp: number;
};

export class BrowserManager {
  settings!: ZagentWebSettings;
  browser: Browser | null = null;
  context: BrowserContext | null = null;
  page: Page | null = null;
  browserName: BrowserName = "chrome";
  startedAt: number | null = null;

  readonly consoleEvents: ConsoleRecord[] = [];
  readonly pageErrors: { message: string; timestamp: number }[] = [];
  readonly networkEvents: NetworkRecord[] = [];
  readonly downloads: { filename: string; path: string; url: string; timestamp: number }[] = [];
  readonly dialogs: { type: string; message: string; defaultValue: string; timestamp: number }[] = [];
  readonly requestRefs = new Map<string, Request>();
  readonly responseRefs = new Map<string, Response>();
  private eventId = 0;
  activeDialog: Dialog | null = null;
  actionRecording = false;
  actionSteps: { action: string; args: Record<string, unknown>; timestamp: number }[] = [];
  harPath: string | null = null;
  videoMode = false;
  private ownsBrowser = true;
  private ownsContext = true;
  private ownsPage = true;
  private externalAttachment = false;
  private nativeAttached = false;
  private externalEndpoint: string | null = null;
  private sharedRuntime = false;
  persistentProfile = false;
  profileDirectory: string | null = null;
  userDataDir: string | null = null;

  async init(): Promise<void> {
    this.settings = await loadSettings();
    this.browserName = this.settings.browser;
    for (const dir of [
      this.settings.screenshotsDir,
      this.settings.downloadsDir,
      this.settings.tracesDir,
      this.settings.harDir,
      this.settings.recordingsDir,
      this.settings.videosDir,
      this.settings.logsDir,
    ]) {
      await fs.mkdir(this.abs(dir), { recursive: true });
    }
  }

  abs(relativeOrAbsolute: string): string {
    return path.isAbsolute(relativeOrAbsolute)
      ? relativeOrAbsolute
      : path.resolve(DATA_ROOT, relativeOrAbsolute);
  }

  async start(name?: BrowserName, headless?: boolean): Promise<unknown> {
    if (!this.settings) await this.init();
    if (this.browser?.isConnected()) return this.status();

    this.browserName = "chrome";
    const launchHeadless = headless ?? this.settings.headless;
    this.ownsBrowser = true;
    this.ownsContext = true;
    this.ownsPage = true;
    this.sharedRuntime = false;
    this.externalAttachment = false;
    this.nativeAttached = false;
    this.externalEndpoint = null;
    this.persistentProfile = false;
    this.profileDirectory = null;
    this.userDataDir = null;

    this.browser = await chromium.launch({
      channel: "chrome",
      headless: launchHeadless,
      executablePath: this.settings.chromeExecutablePath?.trim() || undefined,
    });
    await this.createContext();

    this.browser.once("disconnected", () => {
      this.browser = null;
      this.context = null;
      this.page = null;
    });
    this.startedAt = Date.now();
    return this.status();
  }

  async attachCdp(endpoint: string, native = false): Promise<unknown> {
    if (!this.settings) await this.init();
    const url = endpoint.trim();
    if (!url) throw new Error("CDP endpoint is required.");
    await this.stop();
    this.browserName = "chrome";
    this.browser = await chromium.connectOverCDP(url);
    const contexts = this.browser.contexts();
    if (!contexts.length) throw new Error("Connected Chrome exposed no default browser context.");
    this.context = contexts[0]!;
    this.context.setDefaultTimeout(this.settings.actionTimeoutMs);
    this.context.setDefaultNavigationTimeout(this.settings.navigationTimeoutMs);
    const pages = this.context.pages();
    this.page = pages.at(-1) ?? null;
    if (!this.page) {
      this.page = await this.context.newPage();
      this.ownsPage = true;
    } else {
      this.ownsPage = false;
    }
    this.ownsBrowser = false;
    this.ownsContext = false;
    this.externalAttachment = true;
    this.nativeAttached = native;
    this.externalEndpoint = url;
    this.persistentProfile = false;
    this.profileDirectory = null;
    this.userDataDir = null;
    this.bindPage(this.page);
    this.startedAt = Date.now();
    return this.status();
  }

  isNativeAttached(): boolean {
    return this.nativeAttached && Boolean(this.browser?.isConnected());
  }

  isExternalAttachment(): boolean {
    return this.externalAttachment && Boolean(this.browser?.isConnected());
  }

  async detachExternal(): Promise<unknown> {
    if (!this.externalAttachment) return { ok: true, detached: false, reason: "not-external-attachment" };
    const endpoint = this.externalEndpoint;
    this.browser = null;
    this.context = null;
    this.page = null;
    this.activeDialog = null;
    this.externalAttachment = false;
    this.nativeAttached = false;
    this.externalEndpoint = null;
    this.ownsBrowser = true;
    this.ownsContext = true;
    this.ownsPage = true;
    this.sharedRuntime = false;
    return { ok: true, detached: true, endpoint, chromeLeftRunning: true };
  }

  async stop(): Promise<unknown> {
    if (this.externalAttachment && !this.ownsBrowser) {
      if (this.ownsPage && !this.ownsContext && this.page && !this.page.isClosed()) {
        await this.page.close().catch(() => undefined);
      }
      return this.detachExternal();
    }
    if (this.ownsPage && !this.ownsContext && this.page && !this.page.isClosed()) {
      await this.page.close().catch(() => undefined);
    }
    if (this.ownsContext) await this.context?.close().catch(() => undefined);
    if (this.ownsBrowser) await this.browser?.close().catch(() => undefined);
    this.browser = null;
    this.context = null;
    this.page = null;
    this.activeDialog = null;
    this.externalAttachment = false;
    this.nativeAttached = false;
    this.externalEndpoint = null;
    return { ok: true, stopped: true };
  }

  async ensure(): Promise<void> {
    if (!this.browser || !this.browser.isConnected()) {
      if (this.sharedRuntime) {
        throw new Error("Shared browser runtime is unavailable; reopen the session.");
      }
      if (this.settings?.runtimeMode === "native_attach") {
        if (this !== browserManager || this.settings?.nativeAttachOnDemand === false) {
          throw new Error("Native Chrome mode is active but Chrome is not attached. Use web_native_chrome_attach first.");
        }
        const { nativeChrome } = await import("./NativeChromeManager.js");
        await nativeChrome.attach();
      } else {
        if (this.settings?.autoRestartBrowser === false && this.startedAt) {
          throw new Error("Browser disconnected and autoRestartBrowser is disabled.");
        }
        await this.start();
      }
    }

    const { bridge } = await import('../bridge/Bridge.js');
    if (await bridge.refresh()) {
      if (!this.page || this.page.isClosed() || this !== browserManager) throw new Error('Select an authorized native tab');
      const { targetFor } = await import('../bridge/gate.js');
      bridge.assertTarget(await targetFor(this.page));
    }

    if (!this.context) {
      if (this.sharedRuntime) throw new Error("Shared browser context is unavailable; reopen the session.");
      await this.createContext();
    }
    if (!this.page || this.page.isClosed()) {
      this.page = await this.context!.newPage();
      this.bindPage(this.page);
    }
  }

  private configureContext(context: BrowserContext, trackNewPages: boolean): void {
    context.setDefaultTimeout(this.settings.actionTimeoutMs);
    context.setDefaultNavigationTimeout(this.settings.navigationTimeoutMs);
    if (trackNewPages) {
      context.on("page", (page) => {
        this.page = page;
        this.bindPage(page);
      });
    }
  }

  async createContext(extra: BrowserContextOptions = {}): Promise<void> {
    if (!this.browser) throw new Error("Browser is not started.");
    const base: BrowserContextOptions = {
      viewport: this.settings.defaultViewport,
      acceptDownloads: true,
      ...extra,
    };
    this.context = await this.browser.newContext(base);
    this.configureContext(this.context, true);
    this.page = await this.context.newPage();
    this.bindPage(this.page);
  }

  async attachSharedContext(
    base: BrowserManager,
    context: BrowserContext,
    ownsContext: boolean,
    page?: Page,
  ): Promise<void> {
    this.settings = base.settings;
    this.browser = base.browser;
    this.context = context;
    this.browserName = base.browserName;
    this.startedAt = base.startedAt;
    this.ownsBrowser = false;
    this.ownsContext = ownsContext;
    this.ownsPage = true;
    this.sharedRuntime = true;
    this.externalAttachment = base.externalAttachment;
    this.nativeAttached = base.nativeAttached;
    this.externalEndpoint = base.externalEndpoint;
    this.persistentProfile = false;
    this.profileDirectory = null;
    this.userDataDir = null;
    this.configureContext(context, ownsContext);
    this.page = page ?? context.pages().at(-1) ?? await context.newPage();
    this.bindPage(this.page);
  }

  async recreateContext(extra: BrowserContextOptions = {}, preserveUrl = true): Promise<void> {
    await this.ensure();
    if (this.externalAttachment) {
      throw new Error("Cannot recreate the real Chrome default context while native-attached. Use a tab session or managed fallback.");
    }
    const current = preserveUrl ? this.page!.url() : "about:blank";
    await this.context!.close();
    await this.createContext(extra);
    if (current.startsWith("http://") || current.startsWith("https://")) {
      await this.page!.goto(current, { waitUntil: "domcontentloaded" });
    }
  }

  private nextId(prefix: string): string {
    this.eventId += 1;
    return `${prefix}-${this.eventId}`;
  }

  private trimLogs(): void {
    if (this.consoleEvents.length > this.settings.maxConsoleEvents) {
      this.consoleEvents.splice(0, this.consoleEvents.length - this.settings.maxConsoleEvents);
    }
    if (this.pageErrors.length > this.settings.maxConsoleEvents) {
      this.pageErrors.splice(0, this.pageErrors.length - this.settings.maxConsoleEvents);
    }
    if (this.networkEvents.length > this.settings.maxNetworkEvents) {
      const removed = this.networkEvents.splice(0, this.networkEvents.length - this.settings.maxNetworkEvents);
      for (const event of removed) {
        if (event.kind === "request") this.requestRefs.delete(event.id);
        if (event.kind === "response") this.responseRefs.delete(event.id);
      }
    }
  }

  private bindPage(page: Page): void {
    page.on("console", (msg: ConsoleMessage) => {
      this.consoleEvents.push({
        type: msg.type(),
        text: msg.text(),
        location: msg.location(),
        timestamp: Date.now(),
      });
      this.trimLogs();
    });

    page.on("pageerror", (error) => {
      this.pageErrors.push({ message: String(error), timestamp: Date.now() });
      this.trimLogs();
    });

    page.on("request", (request: Request) => {
      const id = this.nextId("req");
      this.requestRefs.set(id, request);
      this.networkEvents.push({
        id,
        kind: "request",
        url: request.url(),
        method: request.method(),
        resourceType: request.resourceType(),
        headers: redactHeaders(request.headers(), this.settings.redactHeaders),
        postData: request.postData(),
        timestamp: Date.now(),
      });
      this.trimLogs();
    });

    page.on("response", (response: Response) => {
      const id = this.nextId("res");
      this.responseRefs.set(id, response);
      this.networkEvents.push({
        id,
        kind: "response",
        url: response.url(),
        status: response.status(),
        ok: response.ok(),
        headers: redactHeaders(response.headers(), this.settings.redactHeaders),
        timestamp: Date.now(),
      });
      this.trimLogs();
    });

    page.on("dialog", (dialog: Dialog) => {
      this.activeDialog = dialog;
      this.dialogs.push({
        type: dialog.type(),
        message: dialog.message(),
        defaultValue: dialog.defaultValue(),
        timestamp: Date.now(),
      });
    });

    page.on("download", async (download: Download) => {
      const target = path.join(this.abs(this.settings.downloadsDir), download.suggestedFilename());
      await download.saveAs(target).catch(() => undefined);
      this.downloads.push({
        filename: download.suggestedFilename(),
        path: target,
        url: download.url(),
        timestamp: Date.now(),
      });
    });
  }

  async status(): Promise<unknown> {
    return {
      ok: true,
      service: "Zagent Web",
      version: "1.0.0",
      engine: "Playwright",
      browserStarted: Boolean(this.browser?.isConnected()),
      browser: this.browserName,
      configuredRuntimeMode: this.settings?.runtimeMode ?? "managed",
      runtimeMode: this.externalAttachment ? (this.nativeAttached ? "native_attach" : "external_cdp") : (this.settings?.runtimeMode ?? "managed"),
      nativeAttached: this.isNativeAttached(),
      externalAttachment: this.externalAttachment,
      externalEndpoint: this.externalEndpoint,
      ownsBrowserProcess: this.ownsBrowser,
      autoRestartBrowser: this.settings?.autoRestartBrowser ?? true,
      persistentProfile: false,
      profileDirectory: null,
      profileDisplayName: null,
      userDataDir: null,
      sharedRuntime: this.sharedRuntime,
      pageCount: this.context?.pages().length ?? 0,
      activeUrl: this.page?.url() ?? null,
      activeTitle: this.page ? await this.page.title().catch(() => null) : null,
      startedAt: this.startedAt,
    };
  }

  async resolveTarget(
    input: string,
    options: { bridgeAuthorized?: boolean } = {}
  ): Promise<string> {
    const list = await loadTargets();
    const match = list.find((item) => item.enabled !== false && item.name.toLowerCase() === input.toLowerCase());
    return validateNavigableUrl(
      match?.url ?? input,
      this.settings,
      { bypassHostAllowlist: Boolean(options.bridgeAuthorized) }
    );
  }

  async open(input: string, waitUntil: "load" | "domcontentloaded" | "networkidle" | "commit" = "domcontentloaded") {
    await this.ensure();
    const { bridge } = await import('../bridge/Bridge.js');
    const protectedMode = await bridge.refresh();
    const url = await this.resolveTarget(input, {
      bridgeAuthorized: protectedMode && bridge.status().authorized,
    });
    let authorizedTarget: { id: string; windowId: number; origin: string } | null = null;
    if (protectedMode) {
      const { targetFor } = await import('../bridge/gate.js');
      authorizedTarget = await targetFor(this.page!);
      bridge.assertNavigation(authorizedTarget, new URL(url).origin);
    }
    const response = await this.page!.goto(url, { waitUntil });
    if (authorizedTarget) {
      const finalUrl = this.page!.url();
      const finalOrigin = new URL(finalUrl).origin;
      bridge.assertNavigation(authorizedTarget, finalOrigin);
      bridge.commitNavigation(authorizedTarget, finalOrigin);
    }
    this.record("open", { input, waitUntil });
    return {
      url: this.page!.url(),
      title: await this.page!.title(),
      status: response?.status() ?? null,
    };
  }

  record(action: string, args: Record<string, unknown>): void {
    if (this.actionRecording) {
      this.actionSteps.push({ action, args, timestamp: Date.now() });
    }
  }

  async targets(): Promise<WebTarget[]> {
    return loadTargets();
  }

  async addTarget(target: WebTarget): Promise<WebTarget> {
    const url = validateNavigableUrl(target.url, this.settings);
    const all = await loadTargets();
    const index = all.findIndex((x) => x.name.toLowerCase() === target.name.toLowerCase());
    const normalized: WebTarget = { ...target, url, enabled: target.enabled ?? true };
    if (index >= 0) all[index] = normalized;
    else all.push(normalized);
    await saveTargets(all);
    return normalized;
  }

  async removeTarget(name: string): Promise<unknown> {
    const all = await loadTargets();
    const next = all.filter((x) => x.name.toLowerCase() !== name.toLowerCase());
    await saveTargets(next);
    return { removed: all.length - next.length };
  }

  async testTarget(name: string): Promise<unknown> {
    const target = (await loadTargets()).find((x) => x.name.toLowerCase() === name.toLowerCase());
    if (!target) throw new Error(`Target '${name}' not found.`);
    return this.open(target.url);
  }

  deviceDescriptor(name: string) {
    const descriptor = devices[name];
    if (!descriptor) throw new Error(`Unknown Playwright device '${name}'.`);
    return descriptor;
  }
}

export const browserManager = new BrowserManager();
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import net from "node:net";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { browserManager } from "./BrowserManager.js";
import { validateNavigableUrl } from "../utils/security.js";

const execFileAsync = promisify(execFile);

export type ChromeProfile = {
  directory: string;
  name: string;
  userName: string | null;
  gaiaName: string | null;
  gaiaId: string | null;
  activeTime: number | null;
};

export type ChromeBridgeInstallation = {
  profile: ChromeProfile;
  extensionIds: string[];
  extensionPaths: string[];
  running: boolean;
};

export type ChromeLaunchRecord = {
  requestedProfile: string;
  profileDirectory: string;
  profileName: string;
  launchedAt: number;
  launchedPid: number | null;
  url: string;
  newWindow: boolean;
};

export type NativeChromeStatus = {
  installed: boolean;
  running: boolean;
  chromePath: string | null;
  chromeVersion: string | null;
  userDataDir: string;
  devToolsActivePortFile: string;
  devToolsActivePortExists: boolean;
  endpoint: string | null;
  attached: boolean;
  processCount: number;
};

export class NativeChromeManager {
  private readonly userDataDir = path.join(
    process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"),
    "Google", "Chrome", "User Data"
  );
  private lastLaunch: ChromeLaunchRecord | null = null;

  private candidatePaths(): string[] {
    return [
      path.join(process.env.PROGRAMFILES || "C:\\Program Files", "Google", "Chrome", "Application", "chrome.exe"),
      path.join(process.env["PROGRAMFILES(X86)"] || "C:\\Program Files (x86)", "Google", "Chrome", "Application", "chrome.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
    ];
  }

  async chromePath(): Promise<string | null> {
    for (const file of this.candidatePaths()) {
      if (file && await fs.access(file).then(() => true).catch(() => false)) return file;
    }
    return null;
  }

  async chromeVersion(chromePath: string | null): Promise<string | null> {
    if (!chromePath) return null;
    try {
      const escaped = chromePath.replace(/'/g, "''");
      const { stdout } = await execFileAsync(
        "powershell.exe",
        ["-NoProfile", "-Command", `(Get-Item '${escaped}').VersionInfo.ProductVersion`],
        { windowsHide: true }
      );
      return stdout.trim() || null;
    } catch {
      return null;
    }
  }

  async processCount(): Promise<number> {
    try {
      const { stdout } = await execFileAsync(
        "powershell.exe",
        ["-NoProfile", "-Command", "@(Get-Process chrome -ErrorAction SilentlyContinue).Count"],
        { windowsHide: true }
      );
      return Number(stdout.trim()) || 0;
    } catch {
      return 0;
    }
  }

  async profiles(): Promise<ChromeProfile[]> {
    const localState = path.join(this.userDataDir, "Local State");
    const raw = JSON.parse(await fs.readFile(localState, "utf8")) as any;
    const cache = raw?.profile?.info_cache ?? {};
    return Object.entries<any>(cache).map(([directory, item]) => ({
      directory,
      name: String(item?.name ?? directory),
      userName: item?.user_name ? String(item.user_name) : null,
      gaiaName: item?.gaia_name ? String(item.gaia_name) : null,
      gaiaId: item?.gaia_id ? String(item.gaia_id) : null,
      activeTime: Number.isFinite(Number(item?.active_time)) ? Number(item.active_time) : null,
    })).sort((a, b) => a.name.localeCompare(b.name));
  }

  async profilesWithZagentBridge(): Promise<ChromeBridgeInstallation[]> {
    const profiles = await this.profiles();
    const runningDirectories = new Set(
      (await this.runningProfileDirectories())
        .map((value) => value.toLowerCase())
    );
    const bridgeRoots = [
      path.resolve(process.cwd(), "extension"),
      path.resolve(process.cwd(), "artifacts", "chrome-bridge"),
    ].map((value) => value.toLowerCase());

    const isBridgeExtensionPath = async (extensionPath: string) => {
      const normalized = extensionPath.toLowerCase();
      if (bridgeRoots.includes(normalized)) return true;

      try {
        const manifest = JSON.parse(
          await fs.readFile(
            path.join(extensionPath, "manifest.json"),
            "utf8"
          )
        ) as any;
        const name = String(manifest?.name ?? "").trim();
        return name === "Zagent Chrome Bridge" ||
          name === "Zohr Chrome Bridge";
      } catch {
        return false;
      }
    };

    const result: ChromeBridgeInstallation[] = [];
    for (const profile of profiles) {
      const extensionIds = new Set<string>();
      const extensionPaths = new Set<string>();

      for (const preferenceName of ["Secure Preferences", "Preferences"]) {
        const preferencePath = path.join(
          this.userDataDir,
          profile.directory,
          preferenceName,
        );
        try {
          const raw = JSON.parse(
            await fs.readFile(preferencePath, "utf8")
          ) as any;
          const settings = raw?.extensions?.settings ?? {};
          for (const [extensionId, item] of Object.entries<any>(settings)) {
            const configuredPath =
              typeof item?.path === "string"
                ? item.path.trim()
                : "";
            if (!configuredPath) continue;

            const absolutePath = path.resolve(
              path.isAbsolute(configuredPath)
                ? configuredPath
                : path.join(
                    this.userDataDir,
                    profile.directory,
                    configuredPath,
                  )
            );
            if (!await isBridgeExtensionPath(absolutePath)) continue;

            extensionIds.add(extensionId);
            extensionPaths.add(absolutePath);
          }
        } catch {
          // Chrome may update preference files while we inspect them.
        }
      }

      if (extensionIds.size > 0) {
        result.push({
          profile,
          extensionIds: [...extensionIds],
          extensionPaths: [...extensionPaths],
          running: runningDirectories.has(
            profile.directory.toLowerCase()
          ),
        });
      }
    }

    return result.sort((a, b) =>
      Number(b.running) - Number(a.running) ||
      (b.profile.activeTime ?? 0) - (a.profile.activeTime ?? 0)
    );
  }

  async preferredProfile(): Promise<ChromeProfile | null> {
    try {
      const localState = path.join(this.userDataDir, "Local State");
      const raw = JSON.parse(await fs.readFile(localState, "utf8")) as any;
      const lastUsed = typeof raw?.profile?.last_used === "string"
        ? raw.profile.last_used.trim()
        : "";
      if (lastUsed) {
        return await this.resolveProfile(lastUsed).catch(() => null);
      }
      const profiles = await this.profiles();
      return profiles.length === 1 ? profiles[0]! : null;
    } catch {
      const profiles = await this.profiles().catch(() => []);
      return profiles.length === 1 ? profiles[0]! : null;
    }
  }

  async activeProfileHint(): Promise<{
    lastUsed: string | null;
    lastActiveProfiles: string[];
    safeProfile: ChromeProfile | null;
    reason: string;
  }> {
    try {
      if (await this.processCount() <= 0) {
        return { lastUsed: null, lastActiveProfiles: [], safeProfile: null, reason: "chrome-not-running" };
      }

      const localState = path.join(this.userDataDir, "Local State");
      const raw = JSON.parse(await fs.readFile(localState, "utf8")) as any;
      const lastUsed = typeof raw?.profile?.last_used === "string" ? raw.profile.last_used : null;
      const activeRaw = raw?.profile?.last_active_profiles;
      const lastActiveProfiles = Array.isArray(activeRaw)
        ? activeRaw.filter((x: unknown): x is string => typeof x === "string" && Boolean(x.trim()))
        : [];

      if (
        lastActiveProfiles.length === 1 &&
        lastUsed &&
        lastActiveProfiles[0] === lastUsed
      ) {
        return {
          lastUsed,
          lastActiveProfiles,
          safeProfile: await this.resolveProfile(lastUsed),
          reason: "single-last-active-matches-last-used",
        };
      }

      return {
        lastUsed,
        lastActiveProfiles,
        safeProfile: null,
        reason: lastActiveProfiles.length > 1
          ? "multiple-active-profiles"
          : "active-profile-not-unambiguous",
      };
    } catch {
      return { lastUsed: null, lastActiveProfiles: [], safeProfile: null, reason: "local-state-unavailable" };
    }
  }

  async resolveProfile(selector: string): Promise<ChromeProfile> {
    const wanted = selector.trim().toLowerCase();
    if (!wanted) throw new Error("Chrome profile name or directory is required.");
    const profiles = await this.profiles();
    const exact = profiles.find((p) =>
      p.directory.toLowerCase() === wanted ||
      p.name.toLowerCase() === wanted ||
      p.userName?.toLowerCase() === wanted
    );
    if (exact) return exact;
    const partial = profiles.filter((p) =>
      p.name.toLowerCase().includes(wanted) ||
      p.directory.toLowerCase().includes(wanted)
    );
    if (partial.length === 1) return partial[0]!;
    if (partial.length > 1) throw new Error(`Chrome profile '${selector}' is ambiguous.`);
    throw new Error(`Chrome profile '${selector}' was not found.`);
  }

  async runningProfileDirectories(): Promise<string[]> {
    try {
      const command = [
        "$items = @(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine)",
        "$items | ConvertTo-Json -Compress"
      ].join("; ");
      const { stdout } = await execFileAsync("powershell.exe", ["-NoProfile", "-Command", command], { windowsHide: true });
      const trimmed = stdout.trim();
      if (!trimmed) return [];
      const parsed = JSON.parse(trimmed);
      const lines = Array.isArray(parsed) ? parsed : [parsed];
      const found = new Set<string>();
      for (const line of lines) {
        if (typeof line !== "string") continue;
        const match = line.match(/--profile-directory=(?:"([^"]+)"|([^\s]+))/i);
        const value = match?.[1] ?? match?.[2];
        if (value) found.add(value);
      }
      return [...found];
    } catch {
      return [];
    }
  }

  async pairingProfile(profileSelector?: string): Promise<ChromeProfile> {
    if (profileSelector?.trim()) return this.resolveProfile(profileSelector);

    if (this.lastLaunch?.profileDirectory) {
      return this.resolveProfile(this.lastLaunch.profileDirectory);
    }

    const running = await this.runningProfileDirectories();
    if (running.length === 1) return this.resolveProfile(running[0]!);

    const hint = await this.activeProfileHint();
    if (hint.safeProfile) return hint.safeProfile;

    throw new Error(
      `Chrome profile cannot be determined safely for pairing (reason: ${hint.reason}). Open only the intended profile or specify it explicitly.`
    );
  }

  async launchProfile(
    profileSelector: string,
    options: { url?: string; newWindow?: boolean } = {}
  ): Promise<unknown> {
    if (!browserManager.settings) await browserManager.init();
    const chromePath = await this.chromePath();
    if (!chromePath) throw new Error("Google Chrome executable was not found.");
    const profile = await this.resolveProfile(profileSelector);
    const newWindow = options.newWindow !== false;
    let url = (options.url ?? "chrome://newtab/").trim() || "chrome://newtab/";
    const internalUrls = new Set([
      "chrome://newtab/",
      "about:blank",
      "chrome://inspect/#remote-debugging",
    ]);
    if (!internalUrls.has(url)) {
      url = validateNavigableUrl(url, browserManager.settings);
    }

    // Chrome 136+ ignores --remote-debugging-port/pipe for the default
    // Chrome user-data directory. Chrome 144+ supports user-enabled remote
    // debugging for the live browser session from chrome://inspect/#remote-debugging.
    // Keep the normal profile launch clean so that Chrome's user-approved
    // debugging server owns the endpoint lifecycle.
    const args = [
      `--profile-directory=${profile.directory}`,
    ];
    if (newWindow) args.push("--new-window");
    args.push(url);

    const child = spawn(chromePath, args, {
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    });
    const launchedPid = child.pid ?? null;
    child.unref();

    this.lastLaunch = {
      requestedProfile: profileSelector,
      profileDirectory: profile.directory,
      profileName: profile.name,
      launchedAt: Date.now(),
      launchedPid,
      url,
      newWindow,
    };

    await new Promise((resolve) => setTimeout(resolve, 700));
    return {
      ok: true,
      chromePath,
      profile,
      lastLaunch: this.lastLaunch,
      processCount: await this.processCount(),
      runningProfileDirectories: await this.runningProfileDirectories(),
      note: "The launcher preserves the exact Chrome profile and does not inject legacy remote-debugging flags. Chrome 144+ live-session remote debugging is user-enabled from chrome://inspect/#remote-debugging.",
    };
  }

  async openRemoteDebuggingSetup(profileSelector: string): Promise<unknown> {
    return this.launchProfile(profileSelector, {
      url: "chrome://inspect/#remote-debugging",
      newWindow: false,
    });
  }

  async launchStatus(): Promise<unknown> {
    return {
      ...(await this.status()),
      profiles: await this.profiles(),
      lastLaunch: this.lastLaunch,
      runningProfileDirectories: await this.runningProfileDirectories(),
      bridgeExtensionProfiles: await this.profilesWithZagentBridge(),
      activeProfileHint: await this.activeProfileHint(),
    };
  }

  private async endpointFromActivePort(): Promise<string | null> {
    const file = path.join(this.userDataDir, "DevToolsActivePort");
    try {
      const raw = await fs.readFile(file, "utf8");
      const lines = raw.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
      const port = Number(lines[0]);
      const wsPath = lines[1] ?? "";
      if (!Number.isInteger(port) || port <= 0) return null;
      if (wsPath.startsWith("/devtools/browser/")) return `ws://127.0.0.1:${port}${wsPath}`;
      return `http://127.0.0.1:${port}`;
    } catch {}
    return null;
  }

  private async endpointFromConfigured(): Promise<string | null> {
    const configured = browserManager.settings?.cdpEndpoint?.trim();
    return configured || null;
  }

  private async remoteDebuggingUserEnabled(): Promise<boolean> {
    try {
      const localState = path.join(this.userDataDir, "Local State");
      const raw = JSON.parse(await fs.readFile(localState, "utf8")) as any;
      return raw?.devtools?.remote_debugging?.["user-enabled"] === true;
    } catch {
      return false;
    }
  }

  private async canConnectLoopback(endpoint: string): Promise<boolean> {
    try {
      const url = new URL(endpoint);
      if (!["127.0.0.1", "localhost", "[::1]", "::1"].includes(url.hostname)) return false;
      const port = Number(url.port);
      if (!Number.isInteger(port) || port <= 0 || port > 65535) return false;
      return await new Promise<boolean>((resolve) => {
        const socket = net.createConnection({ host: url.hostname, port });
        let done = false;
        const finish = (value: boolean) => {
          if (done) return;
          done = true;
          socket.destroy();
          resolve(value);
        };
        socket.setTimeout(900);
        socket.once("connect", () => finish(true));
        socket.once("timeout", () => finish(false));
        socket.once("error", () => finish(false));
      });
    } catch {
      return false;
    }
  }

  private async validatedPermissionProxyEndpoint(endpoint: string): Promise<string | null> {
    try {
      const url = new URL(endpoint);
      if (url.protocol !== "ws:") return null;
      if (!["127.0.0.1", "localhost", "[::1]", "::1"].includes(url.hostname)) return null;
      if (!url.pathname.startsWith("/devtools/browser/")) return null;
      if (!await this.remoteDebuggingUserEnabled()) return null;
      if (!await this.canConnectLoopback(endpoint)) return null;
      return endpoint;
    } catch {
      return null;
    }
  }

  private devToolsHttpOrigin(endpoint: string): string | null {
    try {
      const url = new URL(endpoint);
      if (!["http:", "https:", "ws:", "wss:"].includes(url.protocol)) return null;
      if (!["127.0.0.1", "localhost", "[::1]", "::1"].includes(url.hostname)) return null;
      const protocol =
        url.protocol === "wss:" ? "https:" :
        url.protocol === "ws:" ? "http:" :
        url.protocol;
      return `${protocol}//${url.host}`;
    } catch {
      return null;
    }
  }

  private async validatedDevToolsEndpoint(endpoint: string): Promise<string | null> {
    const origin = this.devToolsHttpOrigin(endpoint);
    if (!origin) return null;
    try {
      const response = await fetch(new URL("/json/version", origin), {
        cache: "no-store",
        signal: AbortSignal.timeout(1500),
      });
      if (!response.ok) return null;
      const data = await response.json() as any;
      const ws = typeof data?.webSocketDebuggerUrl === "string"
        ? data.webSocketDebuggerUrl.trim()
        : "";
      if (!ws) return null;
      const wsUrl = new URL(ws);
      if (!["ws:", "wss:"].includes(wsUrl.protocol)) return null;
      if (!["127.0.0.1", "localhost", "[::1]", "::1"].includes(wsUrl.hostname)) return null;
      if (!wsUrl.pathname.startsWith("/devtools/browser/")) return null;
      return ws;
    } catch {
      return null;
    }
  }

  async discoverEndpoint(): Promise<string | null> {
    // Chrome 144+ live-session debugging exposes a permission proxy whose
    // /json/version intentionally returns 404. The trusted DevToolsActivePort
    // WebSocket must therefore be tried directly so Chrome can show its Allow
    // dialog. This endpoint is accepted only when Chrome's user-enabled remote
    // debugging preference is on and the loopback listener is alive.
    const activePortEndpoint = await this.endpointFromActivePort();
    if (activePortEndpoint) {
      const permissionProxy = await this.validatedPermissionProxyEndpoint(activePortEndpoint);
      if (permissionProxy) return permissionProxy;

      const standardFromActivePort = await this.validatedDevToolsEndpoint(activePortEndpoint);
      if (standardFromActivePort) return standardFromActivePort;
    }

    const candidates = [
      await this.endpointFromConfigured(),
      "http://127.0.0.1:9222",
    ].filter((x): x is string => Boolean(x));

    for (const endpoint of [...new Set(candidates)]) {
      const validated = await this.validatedDevToolsEndpoint(endpoint);
      if (validated) return validated;
    }
    return null;
  }

  async status(): Promise<NativeChromeStatus> {
    const chromePath = await this.chromePath();
    const endpoint = await this.discoverEndpoint();
    const processCount = await this.processCount();
    const activePortFile = path.join(this.userDataDir, "DevToolsActivePort");
    return {
      installed: Boolean(chromePath),
      running: processCount > 0,
      chromePath,
      chromeVersion: await this.chromeVersion(chromePath),
      userDataDir: this.userDataDir,
      devToolsActivePortFile: activePortFile,
      devToolsActivePortExists: await fs.access(activePortFile).then(() => true).catch(() => false),
      endpoint,
      attached: browserManager.isNativeAttached(),
      processCount,
    };
  }

  async attach(endpoint?: string): Promise<unknown> {
    if (browserManager.isNativeAttached() && !endpoint?.trim()) {
      return browserManager.status();
    }
    const target = endpoint?.trim() || await this.discoverEndpoint();
    if (!target) {
      throw new Error(
        "Chrome is running but no native CDP endpoint is available. Pairing can still be prepared, but page automation requires Chrome remote debugging/native CDP to be available."
      );
    }
    return browserManager.attachCdp(target, true);
  }

  async detach(): Promise<unknown> {
    return browserManager.detachExternal();
  }
}

export const nativeChrome = new NativeChromeManager();

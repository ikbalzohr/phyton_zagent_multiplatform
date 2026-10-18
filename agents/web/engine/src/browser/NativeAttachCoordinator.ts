import { browserManager } from "./BrowserManager.js";
import { nativeChrome } from "./NativeChromeManager.js";
import { bridge } from "../bridge/Bridge.js";

export type NativeAttachResult = {
  attached: boolean;
  reason: string;
  endpoint?: string | null;
  profile?: string | null;
  error?: string | null;
  attemptedAt: number;
};

export class NativeAttachCoordinator {
  private timer: NodeJS.Timeout | null = null;
  private inFlight: Promise<NativeAttachResult> | null = null;
  private lastResult: NativeAttachResult | null = null;

  async ensureAttached(options: { requireBridgeConnected?: boolean; strict?: boolean } = {}): Promise<NativeAttachResult> {
    if (this.inFlight) return this.inFlight;

    const task = this.ensureAttachedInternal(options).finally(() => {
      this.inFlight = null;
    });
    this.inFlight = task;
    return task;
  }

  private async ensureAttachedInternal(
    options: { requireBridgeConnected?: boolean; strict?: boolean }
  ): Promise<NativeAttachResult> {
    const attemptedAt = Date.now();

    if (browserManager.isNativeAttached()) {
      return this.remember({
        attached: true,
        reason: "already-attached",
        attemptedAt,
      });
    }

    await bridge.refresh();
    const bridgeState = bridge.status();
    const requireBridgeConnected = options.requireBridgeConnected !== false;

    if (requireBridgeConnected && (!bridgeState.profileBound || !bridgeState.connected)) {
      const result = this.remember({
        attached: false,
        reason: !bridgeState.profileBound ? "profile-not-bound" : "bridge-not-connected",
        profile: bridgeState.profileBinding?.directory ?? null,
        attemptedAt,
      });
      if (options.strict) {
        throw new Error(
          result.reason === "profile-not-bound"
            ? "Native Chrome attach blocked because no trusted Chrome profile is bound."
            : "Native Chrome attach is waiting for the trusted Chrome Bridge profile to reconnect."
        );
      }
      return result;
    }

    const endpoint = await nativeChrome.discoverEndpoint();
    if (!endpoint) {
      const result = this.remember({
        attached: false,
        reason: "cdp-endpoint-unavailable",
        endpoint: null,
        profile: bridgeState.profileBinding?.directory ?? null,
        attemptedAt,
      });
      if (options.strict) {
        throw new Error(
          "Trusted Chrome profile is connected, but no local Chrome CDP endpoint is available. Start the profile through the Zagent Chrome launcher or enable Chrome remote debugging."
        );
      }
      return result;
    }

    try {
      await nativeChrome.attach(endpoint);
      const attached = browserManager.isNativeAttached();
      const result = this.remember({
        attached,
        reason: attached ? "attached" : "attach-returned-without-native-state",
        endpoint,
        profile: bridgeState.profileBinding?.directory ?? null,
        attemptedAt,
      });
      if (!attached && options.strict) {
        throw new Error("Native Chrome attach completed without entering nativeAttached state.");
      }
      return result;
    } catch (error) {
      const result = this.remember({
        attached: false,
        reason: "attach-failed",
        endpoint,
        profile: bridgeState.profileBinding?.directory ?? null,
        error: error instanceof Error ? error.message : String(error),
        attemptedAt,
      });
      if (options.strict) throw error;
      return result;
    }
  }

  start(intervalMs = 1500): void {
    if (this.timer) return;

    const tick = () => {
      if (browserManager.settings?.runtimeMode !== "native_attach") return;
      if (browserManager.settings?.nativeAutoAttach !== true) return;
      void this.ensureAttached({ requireBridgeConnected: true }).catch(() => undefined);
    };

    tick();
    this.timer = setInterval(tick, intervalMs);
    this.timer.unref();
  }

  stop(): void {
    if (!this.timer) return;
    clearInterval(this.timer);
    this.timer = null;
  }

  status() {
    return {
      enabled:
        browserManager.settings?.runtimeMode === "native_attach" &&
        browserManager.settings?.nativeAutoAttach === true,
      monitoring: Boolean(this.timer),
      nativeAttached: browserManager.isNativeAttached(),
      lastResult: this.lastResult,
    };
  }

  private remember(result: NativeAttachResult): NativeAttachResult {
    this.lastResult = result;
    return result;
  }
}

export const nativeAttachCoordinator = new NativeAttachCoordinator();

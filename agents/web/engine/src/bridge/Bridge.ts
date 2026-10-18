import fs from "node:fs/promises";
import path from "node:path";
import { randomBytes, createHash, timingSafeEqual } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import { BRIDGE_FILE, RUNTIME_DIR } from "../config/paths.js";

export type Target = { id: string; windowId: number; origin: string };
export type LeaseScope = "tab" | "window" | "all";

export type ProfileHint = {
  directory: string;
  name: string;
  userName: string | null;
  gaiaId?: string | null;
};

export type ProfileIdentity = {
  instanceId: string;
  email: string;
  gaiaId: string;
};

export type ObservedExtensionProfile = {
  origin: string;
  email: string | null;
  gaiaId: string | null;
  instanceFingerprint: string;
  lastSeen: number;
};

export type ProfileBinding = ProfileHint & {
  instanceHash: string;
  boundEmail: string;
  boundGaiaId: string;
  boundAt: number;
  verifiedBy: "chrome_identity_email+profile_instance" | "profile_instance";
};

export type Lease = {
  scope: LeaseScope;
  targets: Target[];
  expiresAt: number | null;
  allowNavigation: boolean;
  allowNewTabs: boolean;
  persistent?: boolean;
};

export type PairRequest = {
  id: string;
  createdAt: number;
  expiresAt: number;
  profile: ProfileHint;
};

export type AuthorizationRequest = {
  id: string;
  scope: LeaseScope;
  seconds: number;
  allowNavigation: boolean;
  allowNewTabs: boolean;
  createdAt: number;
  expiresAt: number;
};

type Config = {
  required: boolean;
  pairingHash?: string;
  pairingExpiresAt?: number;
  extensionOrigin?: string;
  reconnectHash?: string;
  persistentConsent?: boolean;
  consentScope?: "all";
  consentSource?: "extension-popup-approve";
  consentAt?: number;
  profileBinding?: ProfileBinding;
};

const digest = (s: string) => createHash("sha256").update(s).digest("hex");
const equal = (a: string, b: string) => a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b));
const requestId = (prefix: string) => `${prefix}-${randomBytes(12).toString("hex")}`;
const cleanEmail = (value: string | null | undefined) => (value ?? "").trim().toLowerCase();
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export class Bridge {
  private config: Config = { required: false };
  private token = "";
  private lease: Lease | null = null;
  private lastSeen = 0;
  private revision = 0;
  private tail: Promise<unknown> = Promise.resolve();
  private pendingPair: PairRequest | null = null;
  private pendingAuthorization: AuthorizationRequest | null = null;
  private reconnectRequestedAt: number | null = null;
  private observedExtensions = new Map<string, ObservedExtensionProfile>();
  // CDP target IDs must be reported by the exact approved Chrome profile extension.
  private approvedTargetIds = new Set<string>();

  private readonly eventLogFile = path.join(RUNTIME_DIR, "bridge-events.log");

  constructor(readonly configFile = BRIDGE_FILE, private clock = Date.now) {}

  private audit(event: string, data: Record<string, unknown> = {}) {
    const line = JSON.stringify({
      at: new Date().toISOString(),
      event,
      ...data,
    }) + "\n";
    void fs.mkdir(path.dirname(this.eventLogFile), { recursive: true })
      .then(() => fs.appendFile(this.eventLogFile, line, "utf8"))
      .catch(() => undefined);
  }

  async refresh() {
    try {
      const next = JSON.parse(await fs.readFile(this.configFile, "utf8")) as Config;
      if (!next || typeof next.required !== "boolean") throw new Error("Invalid bridge configuration");
      if (
        next.extensionOrigin !== this.config.extensionOrigin ||
        next.pairingHash !== this.config.pairingHash ||
        next.reconnectHash !== this.config.reconnectHash ||
        next.profileBinding?.instanceHash !== this.config.profileBinding?.instanceHash
      ) this.revoke(true);
      this.config = next;
    } catch (e: any) {
      if (e.code !== "ENOENT") throw new Error("Bridge configuration unreadable; access denied");
    }
    return this.config.required;
  }

  private activePair(): PairRequest | null {
    if (this.pendingPair && this.pendingPair.expiresAt <= this.clock()) this.pendingPair = null;
    return this.pendingPair;
  }

  private activeAuthorization(): AuthorizationRequest | null {
    if (this.pendingAuthorization && this.pendingAuthorization.expiresAt <= this.clock()) this.pendingAuthorization = null;
    return this.pendingAuthorization;
  }

  private validateIdentity(identity: ProfileIdentity): ProfileIdentity {
    const normalized: ProfileIdentity = {
      instanceId: String(identity?.instanceId ?? "").trim(),
      email: cleanEmail(identity?.email),
      gaiaId: String(identity?.gaiaId ?? "").trim(),
    };
    if (!/^[A-Za-z0-9-]{16,128}$/.test(normalized.instanceId)) {
      throw new Error("Invalid Chrome profile instance identity.");
    }
    if (normalized.email.length > 320 || normalized.gaiaId.length > 256) {
      throw new Error("Invalid Chrome profile account identity.");
    }
    return normalized;
  }

  private expectedProfileMatches(profile: ProfileHint, identity: ProfileIdentity): boolean {
    const expectedEmail = cleanEmail(profile.userName);
    if (!expectedEmail) return true;
    return expectedEmail === cleanEmail(identity.email);
  }

  private assertExpectedProfile(profile: ProfileHint, identity: ProfileIdentity) {
    if (!this.expectedProfileMatches(profile, identity)) {
      throw new Error(
        `Chrome profile mismatch. Pairing was requested for ${profile.name} (${profile.directory}) / ${profile.userName}, but this extension profile reports ${identity.email || "no signed-in account"}.`
      );
    }
  }

  private bindingMatches(identity: ProfileIdentity): boolean {
    const binding = this.config.profileBinding;
    if (!binding) return false;
    if (!equal(digest(identity.instanceId), binding.instanceHash)) return false;
    const expectedEmail = cleanEmail(binding.userName);
    if (expectedEmail && expectedEmail !== cleanEmail(identity.email)) return false;
    return true;
  }

  private publicBinding() {
    const binding = this.config.profileBinding;
    if (!binding) return null;
    return {
      directory: binding.directory,
      name: binding.name,
      userName: binding.userName,
      gaiaIdKnown: Boolean(binding.gaiaId),
      boundEmail: binding.boundEmail,
      boundAt: binding.boundAt,
      verifiedBy: binding.verifiedBy,
      instanceFingerprint: binding.instanceHash.slice(0, 12),
    };
  }

  private observeExtension(origin: string, identity: ProfileIdentity) {
    const fingerprint = digest(identity.instanceId).slice(0, 12);
    this.observedExtensions.set(fingerprint, {
      origin,
      email: identity.email || null,
      gaiaId: identity.gaiaId || null,
      instanceFingerprint: fingerprint,
      lastSeen: this.clock(),
    });
    this.pruneObservedExtensions();
  }

  private pruneObservedExtensions() {
    const cutoff = this.clock() - 120_000;
    for (const [key, item] of this.observedExtensions) {
      if (item.lastSeen < cutoff) this.observedExtensions.delete(key);
    }
  }

  observedExtensionProfiles(): ObservedExtensionProfile[] {
    this.pruneObservedExtensions();
    return [...this.observedExtensions.values()]
      .sort((a, b) => b.lastSeen - a.lastSeen);
  }

  private publicIdentity(identity: ProfileIdentity) {
    return {
      email: identity.email || null,
      gaiaIdKnown: Boolean(identity.gaiaId),
      instanceFingerprint: digest(identity.instanceId).slice(0, 12),
    };
  }

  private persistentLease(): Lease {
    return {
      scope: "all",
      targets: [],
      expiresAt: null,
      allowNavigation: true,
      allowNewTabs: true,
      persistent: true,
    };
  }

  status() {
    const now = this.clock();
    const connected = Boolean(this.token) && now - this.lastSeen < 90_000;
    const lease = connected && this.lease && (this.lease.expiresAt === null || this.lease.expiresAt > now) ? this.lease : null;
    return {
      required: this.config.required,
      connected,
      authorized: Boolean(lease),
      lease,
      pairingPending: this.activePair(),
      authorizationPending: connected ? this.activeAuthorization() : null,
      profileBinding: this.publicBinding(),
      profileBound: Boolean(this.config.profileBinding),
      persistentConsent: Boolean(this.config.persistentConsent),
      approvedTabCount: this.approvedTargetIds.size,
      engine: "native_cdp",
      revision: this.revision,
      heartbeatTimeoutSeconds: 90,
      reconnectAvailable: Boolean(
        this.config.extensionOrigin &&
        this.config.reconnectHash &&
        this.config.profileBinding
      ),
      reconnectRequestedAt: this.reconnectRequestedAt,
      observedExtensionProfiles: this.observedExtensionProfiles(),
    };
  }

  pairStatus() {
    return {
      ...this.status(),
      pairedOriginKnown: Boolean(this.config.extensionOrigin),
      pairingPending: this.activePair(),
    };
  }

  profileBindingStatus() {
    return {
      bound: Boolean(this.config.profileBinding),
      profile: this.publicBinding(),
      connected: this.status().connected,
      authorized: this.status().authorized,
      reconnectAvailable: this.status().reconnectAvailable,
    };
  }

  requestPair(seconds: number, profile: ProfileHint) {
    if (!Number.isInteger(seconds) || seconds < 30 || seconds > 600) {
      throw new Error("Pair request must last 30-600 seconds.");
    }
    if (!profile?.directory?.trim() || !profile?.name?.trim()) {
      throw new Error("A concrete Chrome profile must be selected for pairing.");
    }

    const active = this.activePair();
    if (active) {
      const sameProfile =
        active.profile.directory === profile.directory &&
        cleanEmail(active.profile.userName) === cleanEmail(profile.userName) &&
        String(active.profile.gaiaId ?? "") === String(profile.gaiaId ?? "");
      if (sameProfile) {
        this.audit("pair_request_reused", {
          requestId: active.id,
          profile: active.profile.directory,
        });
        return this.pairStatus();
      }
      this.audit("pair_request_rejected_existing", {
        existingRequestId: active.id,
        existingProfile: active.profile.directory,
        requestedProfile: profile.directory,
      });
      throw new Error(
        `Another pairing request is already active for ${active.profile.name} (${active.profile.directory}). Wait for it to finish or expire before pairing a different profile.`
      );
    }

    this.pendingPair = {
      id: requestId("pair"),
      createdAt: this.clock(),
      expiresAt: this.clock() + seconds * 1000,
      profile: {
        directory: profile.directory,
        name: profile.name,
        userName: profile.userName ?? null,
        gaiaId: profile.gaiaId ?? null,
      },
    };
    this.audit("pair_request_created", {
      requestId: this.pendingPair.id,
      profile: this.pendingPair.profile.directory,
      expiresAt: this.pendingPair.expiresAt,
    });
    this.revision++;
    return this.pairStatus();
  }

  requestAuthorization(
    scope: LeaseScope,
    seconds: number,
    allowNavigation = true,
    allowNewTabs = true,
    requestSeconds = 120
  ) {
    if (!this.status().connected) {
      throw new Error("Chrome Bridge is not connected to its bound profile. Pair or reconnect the intended profile first.");
    }
    if (!this.config.profileBinding) throw new Error("Chrome Bridge has no profile binding.");
    if (!["tab", "window", "all"].includes(scope)) throw new Error("Invalid authorization scope.");
    if (!Number.isInteger(seconds) || ![0, 900, 1800].includes(seconds)) {
      throw new Error("Permission duration must be 15 minutes, 30 minutes, or unlimited.");
    }
    if (!Number.isInteger(requestSeconds) || requestSeconds < 30 || requestSeconds > 300) {
      throw new Error("Authorization request must last 30-300 seconds.");
    }
    if (scope === "tab") allowNewTabs = false;

    const active = this.activeAuthorization();
    if (active) {
      const sameRequest =
        active.scope === scope &&
        active.seconds === seconds &&
        active.allowNavigation === allowNavigation &&
        active.allowNewTabs === allowNewTabs;
      if (sameRequest) {
        this.audit("authorization_request_reused", { requestId: active.id, scope });
        return this.status();
      }
      this.audit("authorization_request_rejected_existing", {
        existingRequestId: active.id,
        existingScope: active.scope,
        requestedScope: scope,
      });
      throw new Error(
        "Another authorization request is already active. Wait for it to finish or expire before changing authorization parameters."
      );
    }

    this.pendingAuthorization = {
      id: requestId("auth"),
      scope,
      seconds,
      allowNavigation,
      allowNewTabs,
      createdAt: this.clock(),
      expiresAt: this.clock() + requestSeconds * 1000,
    };
    this.audit("authorization_request_created", {
      requestId: this.pendingAuthorization.id,
      scope,
      expiresAt: this.pendingAuthorization.expiresAt,
    });
    this.revision++;
    return this.status();
  }

  async waitForPairRequest(id: string, waitSeconds = 180) {
    const startedAt = Date.now();
    const initial = this.pendingPair?.id === id ? this.pendingPair : null;
    const requestExpiresAt = initial?.expiresAt ?? startedAt + Math.max(0.01, waitSeconds) * 1000;
    const deadline = Math.min(
      requestExpiresAt,
      startedAt + Math.max(0.01, waitSeconds) * 1000
    );

    while (Date.now() < deadline) {
      const state = this.pairStatus();
      if (state.profileBound && state.connected && !state.pairingPending) {
        return {
          ok: true,
          outcome: "paired",
          timedOut: false,
          waitedMs: Date.now() - startedAt,
          ...state,
        };
      }

      const pending = this.activePair();
      if (!pending || pending.id !== id) {
        const timedOut = Date.now() >= requestExpiresAt;
        return {
          ok: true,
          outcome: timedOut ? "timed_out" : (state.profileBound && state.connected ? "paired" : "cancelled"),
          timedOut,
          cancelled: !state.profileBound,
          waitedMs: Date.now() - startedAt,
          ...state,
        };
      }

      await sleep(Math.min(500, Math.max(1, deadline - Date.now())));
    }

    const pending = this.activePair();
    if (pending?.id === id) {
      this.pendingPair = null;
      this.revision++;
    }

    return {
      ok: true,
      outcome: "timed_out",
      timedOut: true,
      cancelled: true,
      waitedMs: Date.now() - startedAt,
      ...this.pairStatus(),
    };
  }

  async waitForAuthorizationRequest(id: string, waitSeconds = 180) {
    const startedAt = Date.now();
    const initial = this.pendingAuthorization?.id === id ? this.pendingAuthorization : null;
    const requestExpiresAt = initial?.expiresAt ?? startedAt + Math.max(0.01, waitSeconds) * 1000;
    const deadline = Math.min(
      requestExpiresAt,
      startedAt + Math.max(0.01, waitSeconds) * 1000
    );

    while (Date.now() < deadline) {
      const state = this.status();
      if (state.authorized && !state.authorizationPending) {
        return {
          ok: true,
          outcome: "approved",
          timedOut: false,
          waitedMs: Date.now() - startedAt,
          ...state,
        };
      }

      const pending = this.activeAuthorization();
      if (!pending || pending.id !== id) {
        const timedOut = Date.now() >= requestExpiresAt;
        return {
          ok: true,
          outcome: timedOut ? "timed_out" : (state.authorized ? "approved" : "cancelled"),
          timedOut,
          cancelled: !state.authorized,
          waitedMs: Date.now() - startedAt,
          ...state,
        };
      }

      await sleep(Math.min(500, Math.max(1, deadline - Date.now())));
    }

    const pending = this.activeAuthorization();
    if (pending?.id === id) {
      this.pendingAuthorization = null;
      this.revision++;
    }

    return {
      ok: true,
      outcome: "timed_out",
      timedOut: true,
      cancelled: true,
      waitedMs: Date.now() - startedAt,
      ...this.status(),
    };
  }

  requestReconnect() {
    if (!this.config.profileBinding || !this.config.reconnectHash) {
      throw new Error("No profile-bound trusted reconnect exists. Pair a Chrome profile first.");
    }
    this.reconnectRequestedAt = this.clock();
    this.revision++;
    return this.pairStatus();
  }

  revoke(disconnect = false) {
    // Durable user approval survives temporary CDP/worker disconnection.
    // A new profile requires an explicit Disconnect and a new Approve.
    this.lease = !disconnect && this.config.persistentConsent &&
      Boolean(this.token) && this.clock() - this.lastSeen < 90_000
        ? this.persistentLease() : null;
    this.pendingAuthorization = null;
    this.revision++;
    if (disconnect) {
      this.approvedTargetIds.clear();
      this.token = "";
      this.lastSeen = 0;
    }
    return this.status();
  }

  private issueToken() {
    this.token = randomBytes(32).toString("hex");
    this.lastSeen = this.clock();
    this.lease = this.config.persistentConsent ? this.persistentLease() : null;
    this.approvedTargetIds.clear(); // new Chrome/CDP target IDs after restart
    return this.token;
  }

  private async finishPair(
    origin: string,
    rawIdentity: ProfileIdentity,
    profile: ProfileHint,
    persistentConsent = false
  ) {
    const identity = this.validateIdentity(rawIdentity);
    this.assertExpectedProfile(profile, identity);

    const reconnectSecret = randomBytes(32).toString("hex");
    const expectedEmail = cleanEmail(profile.userName);
    const next: Config = {
      required: true,
      extensionOrigin: origin,
      reconnectHash: digest(reconnectSecret),
      persistentConsent: Boolean(persistentConsent),
      consentScope: "all",
      consentSource: "extension-popup-approve",
      consentAt: this.clock(),
      profileBinding: {
        directory: profile.directory,
        name: profile.name,
        userName: profile.userName ?? null,
        gaiaId: profile.gaiaId ?? null,
        instanceHash: digest(identity.instanceId),
        boundEmail: identity.email,
        boundGaiaId: identity.gaiaId,
        boundAt: this.clock(),
        verifiedBy: expectedEmail
          ? "chrome_identity_email+profile_instance"
          : "profile_instance",
      },
    };
    await fs.writeFile(this.configFile, JSON.stringify(next, null, 2));
    this.config = next;
    this.pendingPair = null;
    this.reconnectRequestedAt = null;
    this.revoke(true);
    const token = this.issueToken();
    return { token, reconnectSecret, ...this.status() };
  }

  async pair(code: string, origin: string, identity: ProfileIdentity) {
    await this.refresh();
    if (
      !this.config.pairingHash ||
      this.clock() >= (this.config.pairingExpiresAt ?? 0) ||
      !equal(digest(code), this.config.pairingHash)
    ) throw new Error("Invalid or expired pairing code");

    const normalized = this.validateIdentity(identity);
    const pending = this.activePair();
    const manualProfile: ProfileHint = pending?.profile ?? {
      directory: "unknown",
      name: normalized.email || "Chrome profile",
      userName: normalized.email || null,
      gaiaId: normalized.gaiaId || null,
    };
    return this.finishPair(origin, normalized, manualProfile);
  }

  async acceptPairRequest(
    id: string,
    origin: string,
    identity: ProfileIdentity,
    consentMode?: string
  ) {
    await this.refresh();
    const pending = this.activePair();
    this.audit("pair_accept_attempt", {
      requestId: id,
      pendingRequestId: pending?.id ?? null,
      pendingProfile: pending?.profile.directory ?? null,
      identityEmail: cleanEmail(identity?.email),
    });
    if (!pending || pending.id !== id) {
      this.audit("pair_accept_rejected", {
        requestId: id,
        pendingRequestId: pending?.id ?? null,
        reason: "no-matching-active-request",
      });
      throw new Error("No matching active pair request.");
    }
    const normalized = this.validateIdentity(identity);
    this.assertExpectedProfile(pending.profile, normalized);

    if (this.config.extensionOrigin && origin !== this.config.extensionOrigin) {
      this.audit("pair_accept_rejected", {
        requestId: id,
        reason: "extension-origin-mismatch",
      });
      throw new Error("This Zagent Web instance is already bound to a different extension origin.");
    }
    const result = await this.finishPair(
      origin, normalized, pending.profile,
      consentMode === "persistent-all-tabs-v1"
    );
    this.audit("pair_accept_success", {
      requestId: id,
      profile: pending.profile.directory,
      email: normalized.email,
    });
    return result;
  }

  async reconnect(secret: string, origin: string, rawIdentity: ProfileIdentity) {
    await this.refresh();
    const identity = this.validateIdentity(rawIdentity);
    if (!this.config.profileBinding) {
      throw new Error("Legacy unbound pairing is not accepted. Pair this Chrome profile once to create a profile-bound trust.");
    }
    if (
      !this.config.extensionOrigin ||
      origin !== this.config.extensionOrigin ||
      !this.config.reconnectHash ||
      !equal(digest(secret), this.config.reconnectHash) ||
      !this.bindingMatches(identity)
    ) throw new Error("Reconnect denied; this trusted pairing belongs to a different Chrome profile.");

    this.revoke(true);
    this.reconnectRequestedAt = null;
    const token = this.issueToken();
    return { token, ...this.status() };
  }

  handshake(origin: string, rawIdentity: ProfileIdentity) {
    const identity = this.validateIdentity(rawIdentity);
    this.observeExtension(origin, identity);
    const pending = this.activePair();
    if (this.config.extensionOrigin && origin !== this.config.extensionOrigin) {
      throw new Error("Extension origin does not match the paired Chrome Bridge.");
    }

    const binding = this.config.profileBinding;
    const bindingMatches = binding ? this.bindingMatches(identity) : false;
    const pendingMatches = pending ? this.expectedProfileMatches(pending.profile, identity) : false;

    return {
      paired: Boolean(
        this.config.extensionOrigin &&
        this.config.reconnectHash &&
        binding &&
        bindingMatches
      ),
      profileMismatch: Boolean(binding && !bindingMatches),
      boundProfile: this.publicBinding(),
      localProfile: this.publicIdentity(identity),
      pendingPair: pendingMatches ? pending : null,
      pendingPairForDifferentProfile: Boolean(pending && !pendingMatches),
      reconnectRequestedAt: bindingMatches ? this.reconnectRequestedAt : null,
      required: this.config.required,
    };
  }

  authenticate(token: string, origin: string, rawIdentity: ProfileIdentity) {
    const identity = this.validateIdentity(rawIdentity);
    if (
      !this.token ||
      !equal(token, this.token) ||
      origin !== this.config.extensionOrigin ||
      !this.bindingMatches(identity)
    ) {
      throw new Error("Bridge session does not belong to this Chrome profile.");
    }
    if (this.clock() - this.lastSeen >= 90_000) this.revoke();
    this.lastSeen = this.clock();
  }

  grant(
    scope: LeaseScope,
    targets: Target[],
    seconds: number,
    options: { allowNavigation?: boolean; allowNewTabs?: boolean; requestId?: string } = {}
  ) {
    if (!this.status().connected) throw new Error("Extension is disconnected");
    if (!this.config.profileBinding) throw new Error("Chrome profile binding is missing.");
    if (
      !["tab", "window", "all"].includes(scope) ||
      !Number.isInteger(seconds) ||
      ![0, 900, 1800].includes(seconds) ||
      !targets.length ||
      targets.length > 500 ||
      (scope === "tab" && targets.length !== 1) ||
      (scope === "window" && new Set(targets.map(t => t.windowId)).size !== 1)
    ) throw new Error("Invalid lease");

    let allowNavigation = Boolean(options.allowNavigation);
    let allowNewTabs = Boolean(options.allowNewTabs) && scope !== "tab";
    const pending = this.activeAuthorization();
    if (options.requestId) {
      if (!pending || pending.id !== options.requestId) throw new Error("Authorization request is missing or expired.");
      if (pending.scope !== scope || pending.seconds !== seconds) throw new Error("Authorization request parameters changed.");
      allowNavigation = pending.allowNavigation;
      allowNewTabs = pending.allowNewTabs;
      this.pendingAuthorization = null;
    }

    this.lease = {
      scope,
      targets,
      expiresAt: seconds === 0 ? null : this.clock() + seconds * 1000,
      allowNavigation,
      allowNewTabs,
    };
    this.revision++;
    return this.status();
  }

  async upgradeConsent() {
    if (!this.status().connected || !this.config.profileBinding) {
      throw new Error("Trusted Chrome connection is required.");
    }
    const next: Config = {
      ...this.config,
      persistentConsent: true,
      consentScope: "all",
      consentSource: "extension-popup-approve",
      consentAt: this.clock(),
    };
    await fs.writeFile(this.configFile, JSON.stringify(next, null, 2));
    this.config = next;
    this.lease = this.persistentLease();
    this.pendingAuthorization = null;
    this.approvedTargetIds.clear();
    this.revision++;
    return this.status();
  }

  syncTargets(ids: unknown) {
    if (!this.status().connected || !this.config.persistentConsent) {
      throw new Error("Persistent Chrome approval required.");
    }
    if (!Array.isArray(ids) || ids.length > 500 ||
      ids.some(id => typeof id !== "string" || !/^[A-Za-z0-9-]{1,128}$/.test(id))) {
      throw new Error("Invalid Chrome profile target identities.");
    }
    this.approvedTargetIds = new Set<string>(ids as string[]);
    this.revision++;
    return this.status();
  }

  private leaseTarget(target: Target): Target | null {
    const state = this.status();
    if (!state.authorized || !state.lease) return null;
    if (state.lease.persistent) {
      return typeof target?.id === "string" &&
        this.approvedTargetIds.has(target.id) &&
        Number.isInteger(target.windowId) && typeof target.origin === "string"
          ? target : null;
    }
    return state.lease.targets.find(t => t.id === target.id && t.windowId === target.windowId) ?? null;
  }

  assertTarget(target: Target) {
    const match = this.leaseTarget(target);
    if (!match || (!this.status().lease?.persistent && match.origin !== target.origin)) {
      throw new Error("Bridge authorization required for this tab, window and origin");
    }
  }

  assertNavigation(target: Target, nextOrigin: string) {
    const state = this.status();
    const match = this.leaseTarget(target);
    if (!state.lease || !match) throw new Error("Bridge authorization required for this tab.");
    if (match.origin !== target.origin) throw new Error("The authorized tab origin has changed.");
    if (nextOrigin !== match.origin && !state.lease.allowNavigation) {
      throw new Error("This lease does not allow cross-origin navigation.");
    }
  }

  commitNavigation(target: Target, nextOrigin: string) {
    const state = this.status();
    if (state.lease?.persistent) return;
    if (!state.lease) throw new Error("Bridge authorization expired during navigation.");
    const match = state.lease.targets.find(t => t.id === target.id && t.windowId === target.windowId);
    if (!match) throw new Error("Authorized tab disappeared during navigation.");
    match.origin = nextOrigin;
    this.revision++;
  }

  assertNewTab(source: Target) {
    const state = this.status();
    const match = this.leaseTarget(source);
    if (!state.lease || !match || !state.lease.allowNewTabs || !["window", "all"].includes(state.lease.scope)) {
      throw new Error("Current bridge lease does not allow opening new tabs.");
    }
    this.assertTarget(source);
  }

  enrollNewTarget(source: Target, target: Target) {
    const state = this.status();
    if (state.lease?.persistent) { this.assertNewTab(source); return; }
    if (!state.lease) throw new Error("Bridge authorization expired before the new tab was enrolled.");
    this.assertNewTab(source);
    if (state.lease.scope === "window" && target.windowId !== source.windowId) {
      throw new Error("New tab opened outside the authorized Chrome window.");
    }
    state.lease.targets.push(target);
    this.revision++;
  }

  removeTarget(id: string) {
    const state = this.status();
    if (state.lease?.persistent) return;
    if (!state.lease) return;
    state.lease.targets = state.lease.targets.filter(t => t.id !== id);
    if (!state.lease.targets.length) this.lease = null;
    this.revision++;
  }

  serial<T>(fn: () => Promise<T>): Promise<T> {
    const result = this.tail.then(fn, fn);
    this.tail = result.catch(() => undefined);
    return result;
  }

  async disconnectTrusted() {
    this.revoke(true);
    this.pendingPair = null;
    this.reconnectRequestedAt = null;
    const next: Config = { required: true };
    await fs.writeFile(this.configFile, JSON.stringify(next, null, 2));
    this.config = next;
    return this.status();
  }

  private bodyIdentity(body: any): ProfileIdentity {
    return this.validateIdentity({
      instanceId: body?.profileIdentity?.instanceId,
      email: body?.profileIdentity?.email,
      gaiaId: body?.profileIdentity?.gaiaId,
    });
  }

  async handle(
    req: IncomingMessage,
    res: ServerResponse,
    resolve: (ids: string[]) => Promise<Target[]>,
    native: () => boolean,
    detachNative?: () => Promise<unknown>
  ) {
    const reply = (code: number, body: unknown) => {
      res.writeHead(code, { "content-type": "application/json", "cache-control": "no-store" });
      res.end(JSON.stringify(body));
    };
    const origin = req.headers.origin ?? "";
    const host = req.headers.host ?? "";

    if (
      !["127.0.0.1", "127.0.0.3", "::1", "::ffff:127.0.0.1", "::ffff:127.0.0.3"].includes(req.socket.remoteAddress ?? "") ||
      !/^(127\.0\.0\.1|127\.0\.0\.3|localhost|\[::1\]):\d+$/.test(host) ||
      !/^chrome-extension:\/\/[a-p]{32}$/.test(origin)
    ) {
      reply(403, { error: "Local extension requests only" });
      return;
    }

    try {
      await this.refresh();
      const route = (req.url ?? "").split("?")[0] ?? "";
      if (route === "/bridge/pair-accept") {
        this.audit("pair_accept_http_arrived", {
          contentLength: req.headers["content-length"] ?? null,
          origin,
        });
      }
      const prePair = ["/bridge/pair", "/bridge/handshake", "/bridge/pair-accept"].includes(route);
      if (!prePair && origin !== this.config.extensionOrigin) {
        throw new Error("Unpaired extension origin");
      }

      res.setHeader("Access-Control-Allow-Origin", origin);
      res.setHeader("Vary", "Origin");
      if (req.method === "OPTIONS") {
        res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
        res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
        reply(204, null);
        return;
      }
      if (req.method !== "POST" || req.headers["content-type"] !== "application/json") {
        reply(415, { error: "JSON POST required" });
        return;
      }

      let text = "";
      for await (const chunk of req) {
        text += chunk;
        if (Buffer.byteLength(text) > 65536) throw new Error("Request too large");
      }
      const body = JSON.parse(text);
      if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("Invalid request");
      if (route === "/bridge/pair-accept") {
        this.audit("pair_accept_body_parsed", {
          requestId: typeof body.requestId === "string" ? body.requestId : null,
          contentLength: Buffer.byteLength(text),
        });
      }
      const identity = this.bodyIdentity(body);

      if (route === "/bridge/handshake") {
        const pending = this.activePair();
        if (pending) {
          this.audit("handshake_during_pair", {
            pendingRequestId: pending.id,
            pendingProfile: pending.profile.directory,
            identityEmail: cleanEmail(identity.email),
            profileMatches: this.expectedProfileMatches(pending.profile, identity),
          });
        }
        reply(200, this.handshake(origin, identity));
        return;
      }
      if (route === "/bridge/pair") {
        reply(200, await this.serial(() => this.pair(String(body.code ?? ""), origin, identity)));
        return;
      }
      if (route === "/bridge/pair-accept") {
        // Pair approval is latency-sensitive and must not wait behind reconnect/disconnect
        // operations queued on the general bridge serial tail. requestId validation plus
        // profile-bound identity checks make this path safe to execute directly.
        reply(200, await this.acceptPairRequest(
          String(body.requestId ?? ""), origin, identity, body.consentMode
        ));
        return;
      }
      if (route === "/bridge/reconnect") {
        reply(200, await this.serial(() => this.reconnect(String(body.secret ?? ""), origin, identity)));
        return;
      }

      this.authenticate((req.headers.authorization ?? "").replace(/^Bearer /, ""), origin, identity);

      if (route === "/bridge/status") {
        reply(200, { ...this.status(), nativeAttached: native() });
        return;
      }
      if (route === "/bridge/targets-sync") {
        reply(200, this.syncTargets(body.targetIds));
        return;
      }
      if (route === "/bridge/consent-upgrade") {
        reply(200, await this.serial(() => this.upgradeConsent()));
        return;
      }
      if (route === "/bridge/revoke") {
        reply(200, this.revoke(false));
        return;
      }
      if (route === "/bridge/disconnect") {
        const detached = detachNative
          ? await detachNative().catch((error) => ({
              ok: false,
              error: error instanceof Error ? error.message : String(error),
            }))
          : { ok: true, detached: false, reason: "detach-handler-unavailable" };
        const disconnected = await this.serial(() => this.disconnectTrusted());
        reply(200, {
          ...disconnected,
          nativeAttached: native(),
          detach: detached,
        });
        return;
      }
      if (route === "/bridge/lease") {
        if (!native()) throw new Error("Native Chrome must be attached");
        if (
          !Array.isArray(body.targetIds) ||
          body.targetIds.length > 500 ||
          body.targetIds.some(
            (id: unknown) => typeof id !== "string" || !/^[A-Za-z0-9-]{1,128}$/.test(id)
          )
        ) throw new Error("Invalid target IDs");
        const revision = this.revision;
        const targets = await resolve([...new Set<string>(body.targetIds)]);
        if (revision !== this.revision) throw new Error("Authorization changed; retry");
        reply(200, this.grant(body.scope, targets, body.seconds, {
          allowNavigation: Boolean(body.allowNavigation),
          allowNewTabs: Boolean(body.allowNewTabs),
          requestId: typeof body.requestId === "string" ? body.requestId : undefined,
        }));
        return;
      }
      reply(404, { error: "Unknown bridge endpoint" });
    } catch (e) {
      reply(403, { error: e instanceof Error ? e.message : "Bridge request denied" });
    }
  }
}

export const bridge = new Bridge();

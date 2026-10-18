from pathlib import Path
import shutil
root=Path(r"D:\3-Ikbalzohr\Agent")
dev=root/"appBridge/production/Zagent/v3/agents/web/engine"
prod=root/"ZohrSystem/Zagent Master/agents/web/engine"
files=["background.js","popup.html","popup.js","popup.css"]
for f in files:
 shutil.copy2(prod/"extension"/f,dev/"extension"/f)
 print("SYNCED_EXTENSION",f)
def edit(rel,changes):
 p=dev/rel
 s=p.read_text(encoding="utf-8-sig")
 for before,after in changes:
  n=s.count(before)
  if n!=1:
   raise AssertionError((rel,before[:140],n))
  s=s.replace(before,after,1)
 p.write_text(s,encoding="utf-8")
 print("PATCHED_TS",rel)
edit("src/bridge/Bridge.ts",[
('''  allowNewTabs: boolean;
};

export type PairRequest''','''  allowNewTabs: boolean;
  persistent?: boolean;
};

export type PairRequest'''),
('''  reconnectHash?: string;
  profileBinding?: ProfileBinding;''','''  reconnectHash?: string;
  persistentConsent?: boolean;
  consentScope?: "all";
  consentSource?: "extension-popup-approve";
  consentAt?: number;
  profileBinding?: ProfileBinding;'''),
('''  private observedExtensions = new Map<string, ObservedExtensionProfile>();''','''  private observedExtensions = new Map<string, ObservedExtensionProfile>();
  // CDP target IDs must be reported by the exact approved Chrome profile extension.
  private approvedTargetIds = new Set<string>();'''),
('''  status() {
    const now = this.clock();''','''  private persistentLease(): Lease {
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
    const now = this.clock();'''),
('''      profileBound: Boolean(this.config.profileBinding),
      engine: "native_cdp",''','''      profileBound: Boolean(this.config.profileBinding),
      persistentConsent: Boolean(this.config.persistentConsent),
      approvedTabCount: this.approvedTargetIds.size,
      engine: "native_cdp",'''),
('''  revoke(disconnect = false) {
    this.lease = null;
    this.pendingAuthorization = null;''','''  revoke(disconnect = false) {
    // Durable user approval survives temporary CDP/worker disconnection.
    // A new profile requires an explicit Disconnect and a new Approve.
    this.lease = !disconnect && this.config.persistentConsent &&
      Boolean(this.token) && this.clock() - this.lastSeen < 90_000
        ? this.persistentLease() : null;
    this.pendingAuthorization = null;'''),
('''    if (disconnect) {
      this.token = "";''','''    if (disconnect) {
      this.approvedTargetIds.clear();
      this.token = "";'''),
('''    this.lastSeen = this.clock();
    return this.token;
  }''','''    this.lastSeen = this.clock();
    this.lease = this.config.persistentConsent ? this.persistentLease() : null;
    this.approvedTargetIds.clear(); // new Chrome/CDP target IDs after restart
    return this.token;
  }'''),
('''  private async finishPair(origin: string, rawIdentity: ProfileIdentity, profile: ProfileHint) {''',
'''  private async finishPair(
    origin: string,
    rawIdentity: ProfileIdentity,
    profile: ProfileHint,
    persistentConsent = false
  ) {'''),
('''      reconnectHash: digest(reconnectSecret),
      profileBinding: {''','''      reconnectHash: digest(reconnectSecret),
      persistentConsent: Boolean(persistentConsent),
      consentScope: "all",
      consentSource: "extension-popup-approve",
      consentAt: this.clock(),
      profileBinding: {'''),
('''  async acceptPairRequest(id: string, origin: string, identity: ProfileIdentity) {''',
'''  async acceptPairRequest(
    id: string,
    origin: string,
    identity: ProfileIdentity,
    consentMode?: string
  ) {'''),
('''    const result = await this.finishPair(origin, normalized, pending.profile);''',
'''    const result = await this.finishPair(
      origin, normalized, pending.profile,
      consentMode === "persistent-all-tabs-v1"
    );'''),
('''  private leaseTarget(target: Target): Target | null {''',
'''  async upgradeConsent() {
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

  private leaseTarget(target: Target): Target | null {'''),
('''    return state.lease.targets.find(t => t.id === target.id && t.windowId === target.windowId) ?? null;''',
'''    if (state.lease.persistent) {
      return typeof target?.id === "string" &&
        this.approvedTargetIds.has(target.id) &&
        Number.isInteger(target.windowId) && typeof target.origin === "string"
          ? target : null;
    }
    return state.lease.targets.find(t => t.id === target.id && t.windowId === target.windowId) ?? null;'''),
('''    if (!match || match.origin !== target.origin) {''',
'''    if (!match || (!this.status().lease?.persistent && match.origin !== target.origin)) {'''),
('''    if (!state.lease) throw new Error("Bridge authorization expired during navigation.");''',
'''    if (state.lease?.persistent) return;
    if (!state.lease) throw new Error("Bridge authorization expired during navigation.");'''),
('''    if (!state.lease) throw new Error("Bridge authorization expired before the new tab was enrolled.");''',
'''    if (state.lease?.persistent) { this.assertNewTab(source); return; }
    if (!state.lease) throw new Error("Bridge authorization expired before the new tab was enrolled.");'''),
('''  removeTarget(id: string) {
    const state = this.status();
    if (!state.lease) return;''',
'''  removeTarget(id: string) {
    const state = this.status();
    if (state.lease?.persistent) return;
    if (!state.lease) return;'''),
('''        reply(200, await this.acceptPairRequest(String(body.requestId ?? ""), origin, identity));''',
'''        reply(200, await this.acceptPairRequest(
          String(body.requestId ?? ""), origin, identity, body.consentMode
        ));'''),
('''      if (route === "/bridge/revoke") {''',
'''      if (route === "/bridge/targets-sync") {
        reply(200, this.syncTargets(body.targetIds));
        return;
      }
      if (route === "/bridge/consent-upgrade") {
        reply(200, await this.serial(() => this.upgradeConsent()));
        return;
      }
      if (route === "/bridge/revoke") {'''),
])

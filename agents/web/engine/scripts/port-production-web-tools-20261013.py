from pathlib import Path
p=Path(r"D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3\agents\web\engine\src\tools\bridge.ts")
s=p.read_text(encoding='utf-8-sig')
pairs=[
('''  const state = bridge.status();

  if (explicitProfile?.trim()) {''',
'''  const state = bridge.status();

  // Prefer a fresh extension heartbeat if exactly one profile matches;
  // never infer foreground solely from Chrome process CLI or Local State.
  if (!explicitProfile?.trim()) {
    const candidates = uniqueProfiles(profiles.filter(
      profile => Boolean(profile.userName) &&
        observed.some(item => String(item.email || "").trim().toLowerCase() ===
          String(profile.userName).trim().toLowerCase())
    ));
    if (candidates.length === 1) {
      return {
        selected: candidates[0]!,
        launchedChrome: false,
        observedExtensionProfiles: observed,
        selectionSource: "fresh-extension-heartbeat",
      };
    }
    if (candidates.length > 1) {
      return {
        selectionRequired: true,
        launchedChrome: false,
        candidates: candidates.map(publicProfile),
        observedExtensionProfiles: observed,
        reason: "multiple-live-extension-profiles",
      };
    }
  }

  if (explicitProfile?.trim()) {'''),
('''    const state = bridge.status();
    if (!state.connected || !state.profileBinding?.directory) {
      throw new Error("Chrome Bridge is not connected to a trusted profile. Pair or reconnect the intended profile first.");
    }

    const attach = await nativeAttachCoordinator.ensureAttached({''',
'''    let state = bridge.status();
    if (state.authorized && state.lease?.persistent) {
      return mcpText({ ok: true, outcome: "already_authorized", ...state });
    }
    if (!state.connected || !state.profileBinding?.directory) {
      const preflight = await selectPairProfile();
      if ("selectionRequired" in preflight) {
        return mcpText({
          ok: true, outcome: "profile_selection_required",
          reason: preflight.reason, candidates: preflight.candidates,
          userAction: "Select/open a Chrome profile with Zagent Chrome Bridge.",
        });
      }
      const selected = preflight.selected;
      const heartbeat = await waitForProfileHeartbeat(selected);
      if (!heartbeat.matched) {
        return mcpText({
          ok: true, outcome: "extension_heartbeat_required",
          profile: publicProfile(selected),
          userAction: "Open the Chrome Bridge extension in the selected profile.",
        });
      }
      const pending = bridge.requestPair(expiresInSeconds, {
        directory: selected.directory,
        name: selected.name,
        userName: selected.userName,
        gaiaId: selected.gaiaId,
      });
      const id = pending.pairingPending?.id;
      if (!id) throw new Error("Unable to request persistent Chrome consent.");
      const outcome = await bridge.waitForPairRequest(id, expiresInSeconds);
      if (outcome.outcome !== "paired") {
        return mcpText({ ...outcome, selectedProfile: publicProfile(selected) });
      }
      state = bridge.status();
      if (!state.authorized || !state.lease?.persistent) {
        throw new Error("Persistent authorization was not established by Chrome Approve.");
      }
    }

    const attach = await nativeAttachCoordinator.ensureAttached({'''),
('''    const requested = bridge.requestAuthorization(scope, seconds, allowNavigation, allowNewTabs, expiresInSeconds);''',
'''    const connectedState = bridge.status();
    if (connectedState.authorized && connectedState.lease?.persistent) {
      return mcpText({ ok: true, outcome: "approved_persistent", ...connectedState });
    }
    const requested = bridge.requestAuthorization(scope, seconds, allowNavigation, allowNewTabs, expiresInSeconds);''')
]
for a,b in pairs:
 n=s.count(a)
 assert n==1,(a[:140],n)
 s=s.replace(a,b,1)
p.write_text(s,encoding='utf-8')
print("TS_BRIDGE_TOOLS_SYNCHRONIZED")

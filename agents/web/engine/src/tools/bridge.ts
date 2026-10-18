import type { McpServer } from "@modelcontextprotocol/server";
import * as z from "zod/v4";
import { bridge } from "../bridge/Bridge.js";
import { authorizedTabs, selectTab } from "../bridge/gate.js";
import { browserManager as B } from "../browser/BrowserManager.js";
import { nativeChrome, type ChromeProfile } from "../browser/NativeChromeManager.js";
import { nativeAttachCoordinator } from "../browser/NativeAttachCoordinator.js";
import { mcpText } from "../utils/json.js";

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function publicProfile(profile: ChromeProfile) {
  return {
    directory: profile.directory,
    name: profile.name,
    userName: profile.userName,
    gaiaName: profile.gaiaName,
    activeTime: profile.activeTime,
  };
}

function uniqueProfiles(profiles: ChromeProfile[]): ChromeProfile[] {
  const seen = new Set<string>();
  return profiles.filter((profile) => {
    const key = profile.directory.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function expectedBridgeEndpoint(): string {
  const settings = B.settings as any | undefined;
  const host = String(settings?.host || "127.0.0.3").trim();
  const port = Number(settings?.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return "";
  return `http://${host}:${port}/bridge/`;
}

function bridgeEnvironment(): string {
  const settings = B.settings as any | undefined;
  return String(settings?.bridgeEnvironment || "DEVELOPMENT")
    .trim()
    .toUpperCase();
}

function heartbeatMatchesProfile(
  profile: ChromeProfile,
  observed: ReturnType<typeof bridge.observedExtensionProfiles>
): boolean {
  const expectedEmail = String(profile.userName || "").trim().toLowerCase();
  if (expectedEmail) {
    return observed.some(
      (item) => String(item.email || "").trim().toLowerCase() === expectedEmail
    );
  }
  return observed.length === 1;
}

async function waitForProfileHeartbeat(
  profile: ChromeProfile,
  timeoutMs = 2000
): Promise<{
  matched: boolean;
  waitedMs: number;
  observedExtensionProfiles: ReturnType<typeof bridge.observedExtensionProfiles>;
}> {
  const startedAt = Date.now();
  const deadline = startedAt + Math.max(250, timeoutMs);
  let observed = bridge.observedExtensionProfiles();

  while (Date.now() < deadline) {
    if (heartbeatMatchesProfile(profile, observed)) {
      return {
        matched: true,
        waitedMs: Date.now() - startedAt,
        observedExtensionProfiles: observed,
      };
    }
    await sleep(250);
    observed = bridge.observedExtensionProfiles();
  }

  return {
    matched: heartbeatMatchesProfile(profile, observed),
    waitedMs: Date.now() - startedAt,
    observedExtensionProfiles: observed,
  };
}

async function ensureProfileOpen(
  profile: ChromeProfile,
  observedExtensionProfiles: ReturnType<typeof bridge.observedExtensionProfiles>
): Promise<boolean> {
  const observedEmails = new Set(
    observedExtensionProfiles
      .map((item) => String(item.email ?? "").trim().toLowerCase())
      .filter(Boolean),
  );
  const observedHere =
    Boolean(profile.userName) &&
    observedEmails.has(String(profile.userName).trim().toLowerCase());

  const running = new Set(
    (await nativeChrome.runningProfileDirectories())
      .map((value) => value.toLowerCase()),
  );

  if (observedHere || running.has(profile.directory.toLowerCase())) {
    return false;
  }

  await nativeChrome.launchProfile(profile.directory, {
    url: "chrome://newtab/",
    newWindow: true,
  });
  await sleep(1200);
  return true;
}

async function selectPairProfile(explicitProfile?: string): Promise<
  | {
      selected: ChromeProfile;
      launchedChrome: boolean;
      observedExtensionProfiles: unknown[];
      selectionSource: string;
    }
  | {
      selectionRequired: true;
      launchedChrome: boolean;
      candidates: unknown[];
      observedExtensionProfiles: unknown[];
      reason: string;
    }
> {
  const profiles = await nativeChrome.profiles();
  const observed = bridge.observedExtensionProfiles();
  const state = bridge.status();

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

  if (explicitProfile?.trim()) {
    const selected = await nativeChrome.resolveProfile(explicitProfile);
    return {
      selected,
      launchedChrome: await ensureProfileOpen(selected, observed),
      observedExtensionProfiles: observed,
      selectionSource: "explicit-profile",
    };
  }

  const boundDirectory = state.profileBinding?.directory;
  if (boundDirectory) {
    const selected = await nativeChrome.resolveProfile(boundDirectory);
    return {
      selected,
      launchedChrome: await ensureProfileOpen(selected, observed),
      observedExtensionProfiles: observed,
      selectionSource: "trusted-profile-binding",
    };
  }

  const pendingDirectory = state.pairingPending?.profile?.directory;
  if (pendingDirectory) {
    const selected = await nativeChrome.resolveProfile(pendingDirectory);
    return {
      selected,
      launchedChrome: await ensureProfileOpen(selected, observed),
      observedExtensionProfiles: observed,
      selectionSource: "pending-pair-profile",
    };
  }

  const bridgeInstallations =
    await nativeChrome.profilesWithZagentBridge().catch(() => []);

  const bridgeProfiles = uniqueProfiles(
    bridgeInstallations.map((item) => item.profile),
  );

  if (bridgeProfiles.length === 1) {
    const selected = bridgeProfiles[0]!;
    return {
      selected,
      launchedChrome: await ensureProfileOpen(selected, observed),
      observedExtensionProfiles: observed,
      selectionSource: "installed-bridge-profile",
    };
  }

  if (bridgeProfiles.length > 1) {
    return {
      selectionRequired: true,
      launchedChrome: false,
      candidates: bridgeInstallations.map((item) => ({
        ...publicProfile(item.profile),
        bridgeInstalled: true,
        bridgeExtensionIds: item.extensionIds,
        running: item.running,
      })),
      observedExtensionProfiles: observed,
      reason: "multiple-installed-bridge-profiles",
    };
  }

  const observedEmails = new Set(
    observed
      .map((item) => String(item.email ?? "").trim().toLowerCase())
      .filter(Boolean),
  );

  const observedCandidates = uniqueProfiles(
    profiles.filter((profile) =>
      Boolean(profile.userName) &&
      observedEmails.has(String(profile.userName).trim().toLowerCase())
    ),
  );

  if (observedCandidates.length === 1) {
    return {
      selected: observedCandidates[0]!,
      launchedChrome: false,
      observedExtensionProfiles: observed,
      selectionSource: "live-bridge-heartbeat",
    };
  }

  if (observedCandidates.length > 1) {
    return {
      selectionRequired: true,
      launchedChrome: false,
      candidates: observedCandidates.map(publicProfile),
      observedExtensionProfiles: observed,
      reason: "multiple-running-extension-profiles",
    };
  }

  const runningDirectories = await nativeChrome.runningProfileDirectories();
  const runningSet = new Set(
    runningDirectories.map((item) => item.toLowerCase()),
  );
  const runningCandidates = uniqueProfiles(
    profiles.filter((profile) =>
      runningSet.has(profile.directory.toLowerCase())
    ),
  );

  if (runningCandidates.length === 1) {
    return {
      selected: runningCandidates[0]!,
      launchedChrome: false,
      observedExtensionProfiles: observed,
      selectionSource: "single-running-profile-fallback",
    };
  }

  if (runningCandidates.length > 1) {
    return {
      selectionRequired: true,
      launchedChrome: false,
      candidates: runningCandidates.map(publicProfile),
      observedExtensionProfiles: observed,
      reason: "multiple-running-chrome-profiles",
    };
  }

  const preferred = await nativeChrome.preferredProfile();
  if (preferred) {
    return {
      selected: preferred,
      launchedChrome: await ensureProfileOpen(preferred, observed),
      observedExtensionProfiles: observed,
      selectionSource: "preferred-profile-fallback",
    };
  }

  return {
    selectionRequired: true,
    launchedChrome: false,
    candidates: profiles.map(publicProfile),
    observedExtensionProfiles: observed,
    reason: "no-unambiguous-bridge-profile",
  };
}

async function prepareNativeDebugging(profileDirectory: string) {
  const first = await nativeAttachCoordinator.ensureAttached({
    requireBridgeConnected: true,
    strict: false,
  });

  if (first.attached) {
    return {
      attached: true,
      setupOpened: false,
      userActionRequired: false,
      attach: first,
    };
  }

  await nativeChrome.openRemoteDebuggingSetup(profileDirectory).catch(() => undefined);
  await sleep(400);

  const second = await nativeAttachCoordinator.ensureAttached({
    requireBridgeConnected: true,
    strict: false,
  });

  return {
    attached: second.attached,
    setupOpened: true,
    userActionRequired: !second.attached,
    userAction: second.attached
      ? null
      : "Chrome Remote Debugging was opened for the paired profile. Enable remote debugging / click Allow debugging in Chrome; Zagent auto-attach will continue automatically.",
    attach: second,
  };
}

export function registerBridgeTools(server: McpServer) {
  server.registerTool("web_bridge_pair", {
    description: "Preflight Chrome, select the unambiguous running Bridge profile, create a profile-bound pairing request, and wait only when an actual pairing request is actionable. If multiple profiles are plausible, return profile_selection_required immediately instead of waiting. After pairing, prepare Chrome remote debugging/native attach.",
    inputSchema: z.object({
      profile: z.string().min(1).optional(),
      expiresInSeconds: z.number().int().min(30).max(180).default(180),
    }),
  }, async ({ profile, expiresInSeconds }) => {
    await bridge.refresh();
    const existing = bridge.status();

    if (existing.connected && existing.profileBinding?.directory) {
      const debugging = await prepareNativeDebugging(existing.profileBinding.directory);
      return mcpText({
        ok: true,
        outcome: "already_paired",
        profile: existing.profileBinding,
        debugging,
        ...bridge.pairStatus(),
      });
    }

    const preflight = await selectPairProfile(profile);
    if ("selectionRequired" in preflight) {
      return mcpText({
        ok: true,
        outcome: "profile_selection_required",
        waitedMs: 0,
        launchedChrome: preflight.launchedChrome,
        reason: preflight.reason,
        candidates: preflight.candidates,
        observedExtensionProfiles: preflight.observedExtensionProfiles,
        userAction: "Open/focus only one intended Chrome profile that has the Zagent Bridge extension, or call web_bridge_pair again with profile set to the intended profile name/directory/email.",
      });
    }

    const selected = preflight.selected;

    if (
      preflight.selectionSource === "trusted-profile-binding" &&
      existing.profileBinding?.directory
    ) {
      let reconnectRequested = false;
      if (existing.reconnectAvailable) {
        bridge.requestReconnect();
        reconnectRequested = true;
      }

      for (let attempt = 0; attempt < 6; attempt += 1) {
        await sleep(350);
        await bridge.refresh();
        const refreshed = bridge.status();
        if (refreshed.connected) {
          const debugging = await prepareNativeDebugging(
            existing.profileBinding.directory
          );
          return mcpText({
            ok: true,
            outcome: "trusted_profile_reconnected",
            selectedProfile: publicProfile(selected),
            launchedChrome: preflight.launchedChrome,
            selectionSource: preflight.selectionSource,
            reconnectRequested,
            debugging,
            ...bridge.pairStatus(),
          });
        }
      }

      return mcpText({
        ok: true,
        outcome: "trusted_profile_opened",
        waitedMs: 2100,
        selectedProfile: publicProfile(selected),
        launchedChrome: preflight.launchedChrome,
        selectionSource: preflight.selectionSource,
        reconnectRequested,
        userAction: "The trusted Chrome profile was opened. Zagent will reconnect automatically when its Bridge extension heartbeat resumes; no new pairing is required.",
        ...bridge.pairStatus(),
      });
    }

    const heartbeat = await waitForProfileHeartbeat(selected);
    if (!heartbeat.matched) {
      return mcpText({
        ok: true,
        outcome: "extension_heartbeat_required",
        waitedMs: heartbeat.waitedMs,
        selectedProfile: publicProfile(selected),
        launchedChrome: preflight.launchedChrome,
        selectionSource: preflight.selectionSource,
        observedExtensionProfiles: heartbeat.observedExtensionProfiles,
        expectedBridgeEndpoint: expectedBridgeEndpoint(),
        bridgeEnvironment: bridgeEnvironment(),
        pairingPending: null,
        userAction:
          "The intended Chrome profile is open, but its Zagent Chrome Bridge heartbeat has not reached the configured Web bridge. Reload/check the extension and verify its bridge environment/endpoint before pairing.",
      });
    }

    const requested = bridge.requestPair(expiresInSeconds, {
      directory: selected.directory,
      name: selected.name,
      userName: selected.userName,
      gaiaId: selected.gaiaId,
    });
    const id = requested.pairingPending?.id;
    if (!id) throw new Error("Pairing request was not created.");

    const outcome = await bridge.waitForPairRequest(id, expiresInSeconds);
    if (outcome.outcome !== "paired") {
      return mcpText({
        ...outcome,
        selectedProfile: publicProfile(selected),
        launchedChrome: preflight.launchedChrome,
        selectionSource: preflight.selectionSource,
        observedExtensionProfiles: preflight.observedExtensionProfiles,
      });
    }

    const debugging = await prepareNativeDebugging(selected.directory);
    return mcpText({
      ...outcome,
      selectedProfile: publicProfile(selected),
      launchedChrome: preflight.launchedChrome,
      selectionSource: preflight.selectionSource,
      debugging,
    });
  });

  server.registerTool("web_bridge_pair_status", {
    description: "Return pairing, observed Bridge profiles, configured bridge endpoint/environment, profile binding, reconnect, connection, and authorization-request status without exposing bridge credentials."
  }, async () => {
    const state = bridge.pairStatus();
    return mcpText({
      ...state,
      expectedBridgeEndpoint: expectedBridgeEndpoint(),
      bridgeEnvironment: bridgeEnvironment(),
      extensionHeartbeatDetected: state.observedExtensionProfiles.length > 0,
    });
  });

  server.registerTool("web_bridge_profile_binding", {
    description: "Show which exact Chrome profile is trusted by the bridge, including profile directory, account email verification method, and a non-secret profile-instance fingerprint."
  }, async () => mcpText(bridge.profileBindingStatus()));

  server.registerTool("web_bridge_authorize_request", {
    description: "Request a user-approved automation lease. If native Chrome debugging is not ready, return debugging_permission_required immediately and open Chrome remote-debugging setup instead of waiting for an approval that cannot succeed.",
    inputSchema: z.object({
      scope: z.enum(["tab", "window", "all"]).default("window"),
      seconds: z.union([z.literal(0), z.literal(900), z.literal(1800)]).default(900),
      allowNavigation: z.boolean().default(true),
      allowNewTabs: z.boolean().default(true),
      expiresInSeconds: z.number().int().min(30).max(180).default(180),
    }),
  }, async ({ scope, seconds, allowNavigation, allowNewTabs, expiresInSeconds }) => {
    await bridge.refresh();
    let state = bridge.status();
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

    const attach = await nativeAttachCoordinator.ensureAttached({
      requireBridgeConnected: true,
      strict: false,
    });

    if (!attach.attached) {
      const debugging = await prepareNativeDebugging(state.profileBinding?.directory ?? "");
      if (!debugging.attached) {
        return mcpText({
          ok: true,
          outcome: "debugging_permission_required",
          waitedMs: 0,
          debugging,
          userAction: debugging.userAction,
          ...bridge.status(),
        });
      }
    }

    const connectedState = bridge.status();
    if (connectedState.authorized && connectedState.lease?.persistent) {
      return mcpText({ ok: true, outcome: "approved_persistent", ...connectedState });
    }
    const requested = bridge.requestAuthorization(scope, seconds, allowNavigation, allowNewTabs, expiresInSeconds);
    const id = requested.authorizationPending?.id;
    if (!id) throw new Error("Authorization request was not created.");
    return mcpText(await bridge.waitForAuthorizationRequest(id, expiresInSeconds));
  });

  server.registerTool("web_bridge_reconnect", {
    description: "Request trusted reconnect for the exact Chrome profile previously paired. A different Chrome profile cannot reuse this reconnect."
  }, async () => mcpText(bridge.requestReconnect()));

  server.registerTool("web_bridge_status", {
    description: "Bridge connection, configured endpoint/environment, observed Bridge profiles, exact profile binding, native attach, and authorization lease status (no credentials)."
  }, async () => {
    const state = bridge.status();
    return mcpText({
      ...state,
      expectedBridgeEndpoint: expectedBridgeEndpoint(),
      bridgeEnvironment: bridgeEnvironment(),
      extensionHeartbeatDetected: state.observedExtensionProfiles.length > 0,
      nativeAttached: B.isNativeAttached(),
      autoAttach: nativeAttachCoordinator.status(),
    });
  });

  server.registerTool("web_bridge_revoke", {
    description: "Revoke the current lease but keep the exact Chrome profile trusted for later authorization."
  }, async () => mcpText(bridge.revoke()));

  server.registerTool("web_bridge_disconnect", {
    description: "Detach native automation, invalidate the current lease, reconnect secret, and trusted Chrome profile binding. Chrome remains open."
  }, async () => {
    const detach = await nativeChrome.detach().catch((error) => ({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    }));
    const disconnected = await bridge.disconnectTrusted();
    return mcpText({
      ...disconnected,
      nativeAttached: B.isNativeAttached(),
      detach,
    });
  });

  server.registerTool("web_bridge_tabs", {
    description: "List currently authorized tabs, including eligible blank/new-tab targets, using stable CDP target IDs."
  }, async () => mcpText(await authorizedTabs()));

  server.registerTool("web_bridge_select_tab", {
    description: "Select a tab inside the current extension lease by stable CDP target ID.",
    inputSchema: z.object({ targetId: z.string().min(1) }),
  }, async ({ targetId }) => mcpText(await selectTab(targetId)));
}

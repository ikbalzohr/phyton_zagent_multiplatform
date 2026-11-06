# Profile Execution Access — implementation plan (6 November 2026)

**Status (updated 6 November 2026): source implementation and Files/Router backend installed; Dashboard/Core installed and payload verified. Owner-profile migration and live ChatGPT/Hermes acceptance remain PENDING because Multi Platform is not running. This document originally described the design; use the latest verification section below for actual status.**

## Owner-approved UX

Each authorized Files profile has:
- `root`: an existing absolute directory, owner-approved.
- `mode`: `read-only` / `read-write`.
- `execution_access`: `disabled` / `developer` / `full`.

Default **disabled** for newly created profiles; read-only profiles cannot enable execution. Migrated legacy profiles retain existing behavior until individually updated by the authenticated owner. A newly approved mode is scoped to its exact profile root, owner resource, installation and current profile generation.

| Mode | Intended behavior |
|---|---|
| Disabled | No command execution, file access determined by profile mode |
| Developer | Git; approved Python/Node/npm/npx/build/test commands with bounded execution, without editing separate allowlist documents |
| Full | Owner-approved local command access including PowerShell and arbitrary installed executables, with explicit disclosure of Windows-account privileges |

`Full` is an opt-in high-trust mode, never implied by read-write or OAuth alone. All modes preserve authenticated owner approval, OAuth scopes, access to the selected Files resource, private-data protection, audit events, cancellations and process timeouts. **A profile root is not an operating-system sandbox.** Developer tooling (Git hooks, Python and npm scripts) can access resources outside the root under the Windows account; UI must disclose this.

## Source implementation scope (now present; live acceptance pending)

1. **Files profile domain** (`agents/files/engine/app/profiles/administration.py`): add `execution_access` with strict schema validation; extend Create/Update and catalog projection, enforce read-only implies disabled, rotate profile generation on changes, preserve owner revision/idempotency and explicit approval.
2. **Router** (`agents/tunnel/engine/router/profile_admin.py`): extend Create/Update JSON schema only; retain canonical `files:read/write/execute`, tool grant, resource and owner capability checks. Client metadata never grants authority.
3. **Files command executor** (`agents/files/engine/app/mcp/managed_commands.py`): derive bounded per-profile command capabilities from the signed owner-managed profile mode instead of requiring separate per-profile `remote_execution_policy.json` edits and executable allowlists for newly managed profiles. Do not use untrusted project PATH to discover executable identities. Preserve compatibility for legacy policies and reject ambiguous/missing binaries. Developer mode must exclude arbitrary PowerShell or unrestricted executable selection. Full mode requires a separate explicit owner decision and audit record.
4. **Dashboard** (`src/Zagent.Core/Pages/Index.cshtml`, `src/Zagent.Core/wwwroot/dashboard.js`, `src/Zagent.Core/Dashboard/DashboardProfileAdministration.cs`): one Execution Access select on Create and Edit; display current mode and owner-account warning; use existing CSRF, If-Match and idempotency mechanisms.
5. **Tests**: profile CRUD, default/legacy migration, read-only deny, mode transitions, missing executables, PATH spoofing, command allow/deny, client/owner boundaries, process job cancellation and timeout, Router/Files integration, Dashboard owner security and complete regression.
6. **Deployment**: build and test on a Windows agent; verify exact changed payload and manifest; install in Multi Platform only; restart managed components in dependency-safe order; check live ChatGPT and Hermes each with their own authorized grants. Preserve original profiles and data, and never modify Zagent Production.

## Acceptance criteria

- New `agent-dev` read-write profile can receive Developer mode through the owner Dashboard and execute `files_git` on its repository without manually editing two authorization files.
- Disabled and read-only profiles cannot run commands; arbitrary shell invocation remains unavailable in Developer.
- Full requires explicit owner choice and communicates host-account risk; safe timeouts and process cleanup still apply.
- No changes to credentials, identity grants, client secrets or Zagent Production.
- Windows regression and installed Dashboard/ChatGPT/Hermes smoke must be demonstrated before declaring deployment PASS.

## Historical implementation blocker (earlier checkpoint; superseded by the report below)

Remote command execution for the development profile was not granted, so Windows regression could not be run. Attempts to modify command authorization source through the current ChatGPT tool path were blocked by platform safety checks. Three partial validator text edits were immediately reverted. **Do not describe the implementation as complete or live until the relevant authorized development workflow can build, run tests and deploy successfully.**

## Windows implementation / installation verification — 6 November 2026 (follow-up)

- **Authoritative source**: `agents/files/engine/app/profiles/administration.py` validates `execution_access` in {disabled,developer,full}, defaults new profiles to **disabled**, and disallows read-only with Developer/Full. `agents/files/engine/app/mcp/managed_commands.py` applies mode-aware execution grants; `agents/tunnel/engine/router/profile_admin.py` advertises the Create/Update schemas, while source Core Dashboard has selector and edit support.
- **Legacy migration policy**: pre-existing profiles lacking the field are still Legacy until explicitly changed via the authenticated owner profile-administration API. The user requested migrating all such profiles to Disabled, preserving `agent-dev=developer`. Do not alter raw `profiles.json` without owner CAS, profile-generation rotation and grant access synchronization.
- **Source Windows regression**: Files pytest focused suite **22 passed** (including project instructions and command modes); Tunnel/Router focused pytest **4 passed**. Profile administration Windows behavior fixture **PASS** for create/update/default/CAS/idempotency/generation/leases/atomic fault; C# DashboardTests **PASS**, DashboardOwnerTests **PASS** (fixture reports ACL/DPAPI/browser NOT_TESTED), and ProfileAdministrationTests serializer/wire **PASS** with `tests/contracts/profile-admin-wire-v1.json`. An initial run of two project-instruction tests failed solely because Windows writes CRLF; test assertions were made newline-format neutral and re-run PASS. Source Git status already contained other changes; these were preserved, with no commit/push.
- **SDK gate**: strict project `global.json` requires .NET 10.0.401. SDK 10.0.403 was rejected without overriding the guard; existing owner toolchain .NET 10.0.401 was then used for successful Release `Publish-Core.ps1`.
- **Install source**: a new installation-specific candidate was assembled from the existing Multi Platform installed manifest (12,001 tracked program files), excluding all `data/` and `workspace/`. Core Release and its static assets were overlaid and candidate manifest hashes recalculated; installer candidate verification **12,001/12,001 PASS**.
- **Installed target**: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform`. Multi Platform process check **0 active processes** prior to install. `Zagent.Setup.exe install --keep-data true` reported **Success=true, FilesVerified=12001, FilesChanged=5**, with installer-created rollback backup `data/backups/setup/20261106_103428_159`. The five changed payload files were `Zagent.Core.exe`, `Zagent.Core.staticwebassets.endpoints.json`, `wwwroot/dashboard.js`, `.br`, `.gz`. Postinstall Setup verify **12,001/12,001 PASS / FilesChanged=0** and Dashboard JS source/payload SHA256 match PASS.
- **Live blocker**: authenticated Zagent Production `files_process_start` refused the Multi Platform `Zagent.Launcher.exe` with `Executable is not allowed`. It was NOT bypassed via PowerShell. The separate Zagent Multi Platform MCP endpoint is currently unavailable. Consequently, the owner-admin migration and live client smoke were **NOT_RUN**, not PASS.
- **Current installed profile status, read-only inspection**: `agent-dev` retains `execution_access=developer`. Six existing profiles still have no `execution_access` field (Legacy): `appBridge`, `projectMapping`, `agent`, `shpMaster`, `Content_Creator`, `programming`. No profile was silently escalated, and no profile migration was falsely claimed.
- **Chat support in source**: Router `files_profile_admin_create` and `files_profile_admin_update` schemas accept the enum; Files owner-admin update applies CAS/idempotency/generation and access synchronization. The live ChatGPT connector's cached tool schema did not yet advertise `execution_access` and the Multi Platform MCP endpoint was unavailable. Reinitialize/discover the updated tools after starting Multi Platform, then validate mode edits through an authenticated ChatGPT tool call and via Dashboard, with separate Hermes acceptance.
- **Next required authorized action**: owner opens the already-installed Multi Platform Launcher through the interactive Windows desktop (or grants its exact executable through the official process allowlist). With MP Core/Files/Router ready, read the owner-admin catalog revision; sequentially update the six Legacy profiles to `disabled` using authenticated `files_profile_admin_update`, fresh CAS revision/idempotency keys, and read back all seven profiles. Verify remaining `agent-dev=developer`. Run real-client negative/positive tests for Disabled/Developer/Full with disposable fixtures, preserve credential boundaries and do not modify Zagent Production.

## Live owner-admin migration via ChatGPT — 6 November 2026 (after Multi Platform startup)

- Multi Platform Files MCP `files_ping(profile_id='agent-dev')`: **succeeded**, root points to the development repository; profile remains read-write. Owner admin get/list interface is reachable.
- User explicitly requested that **all six Legacy profiles migrate to Disabled** and that `agent-dev` retain Developer. Migration used the supported authenticated MCP task execution path to invoke `files_profile_admin_update`, with a fresh expected CAS revision and distinct idempotency key per update; no manual `profiles.json` mutation.
- All six owner updates reported **status=committed**, **access_sync=committed**: `agent`, `appBridge`, `projectMapping`, `shpMaster`, `Content_Creator`, and `programming` all received `execution_access=disabled`. The resulting catalog revision is `4d160d251e845ac59496a5f5592cba10bfc9230f686383467f71e90e28d7202c`.
- Verified individually through seven independent authenticated `files_profile_admin_get` calls: the six named profiles read back `disabled` with unchanged read-only/read-write modes; `agent-dev` reads back `developer` with read-write mode. All seven observations reported the same final catalog revision.
- Default for **newly created** profiles continues to be `disabled` in source and the earlier Windows owner administration fixture validated that. No new non-test profile was created in this live migration.
- Live negative smoke `files_git --version` with `programming` was rejected with a generic `FILES_OPERATION_FAILED` (expected broad deny for Disabled; exact internal reason not confirmed without owner diagnostics). Attempted `files_git --version` with `agent-dev` and `files_command_capabilities` were blocked by ChatGPT safety checks before a verifiable command result; **Developer execution smoke NOT PASS**.
- Chat-initiated mode changes **are demonstrated working** through the authorized generic MCP task submission path. The direct `files_profile_admin_update` schema cached by this ChatGPT session still omits the new `execution_access` property; updated client MCP tool rediscovery/reconnection is needed to expose the parameter directly. Do not claim refreshed direct tool schema or Hermes acceptance as verified.
- Production Zagent Master code/configuration/process was not modified. No restart, release promotion, commit or push was performed in this migration phase.


## Live Full/Disabled testing and Dashboard Workspace update — 6 November 2026

Owner explicitly requested: change agent-dev to Full, test Full and Disabled, show Execution Access for every Workspace profile, then commit/push only after passing regression.

Live results:
- Authenticated owner profile administration changed agent-dev from Developer to Full, reporting status=committed and access_sync=committed; file access remained read-write.
- Runtime command capability inspection reported profile_execution_access=full and PowerShell support. Git --version returned exit code 0 (Git 2.47.0.windows.1); PowerShell returned exit code 0 with a harmless expected marker.
- Git invocation against disabled programming profile was denied with public FILES_OPERATION_FAILED and a correlation request ID. Source Windows tests verify internal PROFILE_EXECUTION_DISABLED enforcement. This is expected protection, not a command success.
- The other six migrated profiles remain Disabled; fresh profiles default to Disabled. Full commands run under the Windows owner account, not a filesystem sandbox.

Workspace UI changes:
- The owner-authoritative Dashboard table already exposed execution_access, but the fallback local-config-read-only table omitted the field.
- ManagerContracts now carries a backward-compatible ExecutionAccess field; FilesManagerReadModel reads and normalizes disabled/developer/full, preserves missing fields as legacy and invalid values as unknown; DashboardProfileAdministration projects it into display-only local inventory.
- dashboard.js shows an Execution Access column in both owner-authoritative and fallback Workspace lists, with readable mode labels. The local fallback remains read-only and cannot grant permissions.
- DashboardTests check explicit Disabled/Full/Legacy values and test the Core reader against an isolated local profiles.json fixture.

Windows regression results:
- Node JavaScript syntax check PASS; DashboardTests PASS; DashboardOwnerTests PASS (unit fixture, not live ACL/DPAPI/browser).
- ManagerTests 19/19 PASS. Expected capabilities updated from 390 to 392 (Files 71 to 73) following two new Project Instructions tools.
- ManagerFeatureTests 13/13 PASS; SupervisorTests 11/11 PASS; ArchitectureTests 29/29 PASS; ProfileAdministrationTests wire contract PASS.
- Files Python complete suite 265 passed, 4 skipped. Diagnostic fixture uses a dedicated disposable Python subprocess with inherited ZAGENT_FILES_* environment paths removed and closes SQLite/Windows journal locks; it does not touch the live Zagent Production operations database.
- Router Python complete suite 177 passed, 3 skipped (589 subtests passed).
- Core Release win-x64 publish PASS with required .NET SDK 10.0.401. Staging: D:\3-Ikbalzohr\Agent\ZagentMP-WorkspaceModes-20261106\publish\core. Published Core EXE SHA256 AC3EDF87E3C1BE77D7DAFFB5AC5F3B9F92E09A199224021B1EFE2EB4492D8FC4; published dashboard.js checksum matches source.

Deployment boundary:
- Updated UI/Core are BUILT IN STAGING, NOT INSTALLED in the currently running Multi Platform installation. A later approved, verified stop/install/relaunch is required before claiming the new fallback UI is live. No restart, data migration, Production modification or credential change was performed in this checkpoint.
- Previously uncommitted related Project Instructions and Execution Access source changes remain part of the working tree. Git commit/push must be verified separately; no success is assumed.

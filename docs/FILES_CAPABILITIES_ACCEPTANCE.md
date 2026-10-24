# Files capabilities: source implementation and Windows acceptance

## Scope

This release does NOT claim all 71 tools are executable. `packaging/files-capabilities.json` enumerates every name in disjoint categories:
- 46 selected project tools: 19 read, 15 write, 12 managed commands.
- 24 local-management-only profile/update/cross-profile tools, not published through OAuth.
- 1 unsupported persistent lifecycle tool: `files_process_start`.

Counts are AST/JSON inventory evidence, not runtime success. Commands require matching installed/approved executables; npm/npx/build/test additionally require a supported fixed npm CLI layout.

## Implemented boundaries

- Canonical per-tool scope policy rejects mutation-under-read and requires BOTH files:execute and files:write for commands.
- Consumer binds the actual tool and inner native operation/arguments to the trusted context; public client metadata never supplies authority.
- Read-only profiles, revoked/expired grants, mismatched profiles/devices/installations and cross-profile transfers remain fail-closed.
- Native filesystem guards reject known symlink/reparse ancestors and unsafe overwrites, use exclusive temporary files, and revalidate local approval. They are best-effort checks, not handle-based TOCTOU-proof Windows isolation.
- Managed commands use an explicit local policy, absolute executable approvals, clean child environment, bounded output/deadline and kill-on-close Windows Job Objects assigned before resuming the child. No arbitrary host process listing or unmanaged PID killing.
- Command capability/list/stop/cancel controls bypass the command's installation queue ONLY after normal tool/grant validation, fresh dual-scope revalidation, owner/resource binding and exact registry mapping. This lets cancellation reach an owned running command instead of queuing behind it. Ordinary mutation/job locking remains installation-wide.
- Cancellation task_id is narrowly treated as a target selector for the two cancel APIs; session/principal/authority overrides remain rejected.
- `files_process_stop.expected_name` is not currently implemented as an extra name filter; ownership/live registry and job handle checks are the authority. Do not describe it as host process administration.

## Command mode is NOT a sandbox

The supported mode is explicitly `owner-account`. A shell/interpreter/project build script can access files/network allowed to that Windows account, including outside its starting directory. CWD is checked, but it does not sandbox command effects. Child environment stripping prevents ambient token inheritance; it cannot prevent an explicitly approved interpreter from reading owner-readable files from disk.

Local activation requires typing BOTH `ALLOW READ WRITE` and `ALLOW OWNER ACCOUNT EXECUTION`. Never silently set this policy or remove backend guards to make tools appear.

## Gate 1: Windows tests (before activation)

From the existing owner's PowerShell:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location 'D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform'
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'Git pull failed' }
    $Python = Join-Path $env:LOCALAPPDATA 'Zagent-Envs\files\Scripts\python.exe'
    & $Python -m pip install 'pytest>=8,<10'
    if ($LASTEXITCODE -ne 0) { throw 'Test dependency installation failed' }
    & '.\packaging\scripts\Test-OwnerFilesCapabilities.ps1' -InstallRoot (Get-Location).Path
}
```

The runner uses disposable directories for every Files data/config/runtime/log/backup/update path, never the real owner DataRoot. It runs Router unittest fixtures plus the existing context and new consumer/command fixtures. Review reported skips: an installed-npm smoke-test skip is NOT build/test acceptance. Native symlink fixtures may depend on owner privileges; document skipped negative cases. This is a focused suite, not every product test or every MCP operation.

No Windows PowerShell parser, Windows product tests, Job Object behavior or managed commands were executed on the VPS. AST/source guards and offline OAuth packaging tests are a separate evidence level.

## Gate 2: explicit local configuration (only after gate 1)

Keep exactly one Core running for path discovery. Execute:

```powershell
& '.\packaging\scripts\Enable-OwnerFilesCapabilities.ps1' -InstallRoot (Get-Location).Path -EnableCommands
```

Review selected root/tools and host-rights warning; type the exact consent phrases only if accepted. When instructed, stop Core through Overview > Stop Core, then press Enter in the helper.

The helper preserves existing grant expiry/revocation/device/installation/resource/root bindings, updates only the existing appBridge profile's mode, adds exact tool policies/scopes, and writes the expanded resource grant LAST. Every replaced file has a private backup and exact read-back. There is no multi-file transaction: on any failure KEEP CORE STOPPED and retain .bak/.tmp files for reviewed recovery. No automatic rollback/reprovisioning/start/renewal occurs. Existing expired/revoked grants are not renewed/reactivated.

If validation fails, do NOT run Configure-OwnerOAuth.ps1 as a workaround: its original staging/activation contract is not a general capabilities upgrade and can create another bounded grant.

## Gate 3: scope issuance and Hermes configuration

Coordinator must separately associate files:write/files:execute as optional scopes on the exact existing Hermes Keycloak client, read back the association, and perform ONE fresh OAuth consent for the larger requested scope set. Refreshing an old read-only grant must not be used to pretend it gained new scope. Retain exact Cloudflare audience + introspection client audience + subject mapper and existing issuer.

Only after scopes/local consent are ready, use Hermes supported configuration interfaces to set the exact Files allowlist plus receipt controls and enable the active profile's MCP entry. No hand-editing config YAML, model/provider changes, fallback work or another profile's settings.

## Gate 4: actual remote evidence

Verify discovery against the manifest with programmatic counts; fetch terminal results, not only receipts. Run unique disposable native create/read-back/hash/delete, outside-root and read-token negative cases, metadata read/write consistency, and a separately authorized harmless command. Exercise cancellation/list/stop against an owned fixture process; verify no unowned process can be stopped. Test real installed npm build/test from a disposable package before claiming those tools work.

At source publication, live access remains the pre-existing read-only grant. Windows gates, consent, expanded OAuth and expanded MCP canaries remain NOT_RUN.

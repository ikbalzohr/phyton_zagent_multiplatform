# Direct owner profile administration — Core/dashboard deployment

**Source authored; Windows compilation/fixtures/live acceptance NOT_RUN; laptop activation NOT_APPLIED.**
This is installation of already-authorized persistent profile management, not another consent request.
Do not run the old `Activate-OwnerFilesProfile.ps1` or use public Files command execution to administer the installation.

## Adapter boundary

Dashboard Administrator cookie + existing same-origin/HTTPS/CSRF/rate-limit checks authorize the real session actor.
`DashboardProfileAdministration` calls the existing Files `/mcp` loopback endpoint using `ProfileAdministrationClient`.
The exact private token header is `X-Zagent-Internal-Token`; authority goes in `params._meta.zagent.profile_admin_context`
or the separate `zagent.profile_catalog_context`. Generic `ManagementHandler` and its native data-tool allowlist are unchanged.
The adapter never substitutes a Windows actor or invents an active Files profile resource.

The adapter resolves exactly one explicit enabled `resource_server.grants.<principal>.profile_management` in owner-private
`tunnel/config/tunnel.json` for every request. Missing/ambiguous/malformed mapping, finite expiry/revocation, placement,
read/write scopes, exact six tool grants, disabled policies or incorrect policy scopes deny. No principal is an application constant.
Admin deadlines are numeric Unix seconds bounded by the existing grant expiry. Capability and payload revisions use SHA256
of UTF8 sorted-key compact JSON with literal Unicode (Python `ensure_ascii=False`); the shared literal vector is
`tests/contracts/profile-admin-wire-v1.json` (including Unicode, emoji, newline, Windows root and leading `_/-` ID).
The production Core launch passes its resolved DataRoot as `ZAGENT_CORE_DATA_ROOT` and enrolled installation ID as
`ZAGENT_INSTALLATION_ID` to Files; neither is inferred from ambient process state. Legacy standalone native callers
without placement explicitly clear these admin placement fields. The Files verifier denies their administration calls.

Backend list/get/create/update/delete/set_default are the only direct admin methods. Catalog reads are private only.
Browser write bodies cannot contain authority, actor, scopes, metadata, revision or idempotency fields: headers supply
If-Match and Idempotency-Key; the authenticated adapter forwards those exact values with the session actor.
The dashboard uses the backend catalog revision, not a locally recomputed UI-row hash. The static owner resource is only
the legacy default fallback until the backend has owner metadata. No catalog read initializes metadata.

The UI supports root, mode, enabled, description and set-default. Create/update/delete/default show terminal committed
backend results and access synchronization, not pending laptop requests. Delete only removes configuration; deleting a
default requires an exact replacement ID. Browser/other-agent action approvals remain in their existing separate flow.
Uncertain transport outcomes keep the same actor/key/body/revision in browser memory and expose an exact-retry button;
there is no automatic replay or assertion of success after a lost response. Reload loses this local recovery handle: retain
it until reconciled, rather than creating another command. Backend actor-scoped idempotency remains authoritative.
Legacy desktop profile-writer entry points now reject with a dashboard instruction rather than spawning a second Python
profile writer. Existing unrelated approvals and their compatibility CAS are not converted to profile administration.

## Capability bootstrap (owner-local, no interactive prompts)

New entry: `packaging/scripts/Enable-OwnerProfileAdministration.ps1`.
All six explicit deployment inputs must be supplied; missing inputs throw (no mandatory-parameter input prompt).

- Windows owner SID only. Existing machine install/DataRoot anchor must match.
- Rejects any `Zagent.Core.exe`, and conservatively any `dotnet.exe`/`dotnet` host, irrespective of executable path.
  CIM failures deny. No process is killed, no command line is read/logged, no Core or Cloudflare process is launched.
- Existing protected owner-private DataRoot plus owner-only ACLs/reparse guards on all config ancestors/leaves.
- Bounded strict JSON rejects duplicate keys, non-JSON constants, excessive depth/size; original untouched JSON tokens
  (including unrelated numeric values) are preserved instead of round-tripping the whole configuration.
- Exact explicit principal must already have a finite active nonrevoked Files grant at the supplied workspace/device/install.
  Existing files:read/files:write scopes are required and never added. Adds only the six exact public admin tool names,
  their exact read/write policies and the exact capability object; never publishes catalog/legacy admin tools.
- Existing conflicting/disabled tool policies or malformed/ambiguous capability mappings fail closed, not silently repaired.
- Writes only ONE authoritative static config file (`tunnel/config/tunnel.json`): independent private backup, unique
  same-directory candidate, flushed writes, concurrent snapshots, expiry recheck, `File.Replace`, ACL and exact readback.
  A failure leaves private recovery artifacts; no implicit rollback, credential rotation or Core restart.
- Static resource/default/membership IDs, all scopes, issuer/OAuth/credential fields, expiry/revocation and unrelated principals
  are unchanged. `profiles.json` metadata/membership/default is initialized only by the Files service's first admin mutation.
  This helper does not create agentRoot, delete appBridge, touch physical data, or clone command execution policy.
- The stopped gate is a conservative precondition, not a global startup lock; keep the supervisor stopped throughout deployment.

## Target Windows checks (not executed on Linux)

Run from the delivered source checkout using its owner-approved .NET SDK and the exact Files interpreter chosen by Core.
`$SourceRoot` and `$FilesPython` below are deployment inputs, not guessed installation paths. The scratch directories are disposable.

```powershell
& {
  $ErrorActionPreference = 'Stop'
  Set-Location -LiteralPath $SourceRoot
  dotnet build .\tests\Zagent.ProfileAdministrationTests\Zagent.ProfileAdministrationTests.csproj
  if ($LASTEXITCODE -ne 0) { throw 'C# build failed' }
  $wire = Join-Path $env:LOCALAPPDATA ('profile-admin-wire-' + [guid]::NewGuid().ToString('N') + '.json')
  dotnet run --no-build --project .\tests\Zagent.ProfileAdministrationTests -- .\tests\contracts\profile-admin-wire-v1.json $wire
  if ($LASTEXITCODE -ne 0) { throw 'C# fixture failed' }
  $seamRoot = Join-Path $env:LOCALAPPDATA ('profile-admin-seam-' + [guid]::NewGuid().ToString('N'))
  & $FilesPython .\tests\check_profile_admin_wire_windows.py $wire $seamRoot
  if ($LASTEXITCODE -ne 0) { throw 'Actual C#/Files serializer-verifier seam failed' }
  & .\packaging\scripts\Test-OwnerProfileAdministration.ps1
  # This fixture uses disposable private paths and a mocked process inventory, never live grants.
  # Run the existing dashboard test executable too; it is a separate build target.
  dotnet run --project .\tests\Zagent.DashboardTests
  if ($LASTEXITCODE -ne 0) { throw 'Existing dashboard regression failed' }
}
```

The emitted wire contains only fixture values and must be consumed immediately (its deadline is bounded).
The paired Windows fixture imports Files only after every config/data/runtime/log/backup/update path points to a fresh
disposable directory. It uses the real C# JSON body and the real Files `request_meta`/profile verifier, checks token/actor/digest,
and denies wrong token/plain spoofed metadata/tampered payload. It does not claim live HTTP or physical profile CRUD acceptance.
The PowerShell fixture exercises plan preservation/denial, process-gate simulation and real disposable ACL/backup/replace/readback.

After all three lanes and target fixtures pass, deploy/rebuild the exact reviewed source with Core stopped, then run the bootstrap
noninteractively from the Windows owner deployment channel (not a public MCP command). Supply the already-validated owner
principal explicitly. The deployment value recorded in the approved contract is
`principal_v1_41d40891edc920d08c8bf7d58f508bb1a082a9dc8dc5bb70f4fa2d913161a59d`;
this value is deliberately confined to deployment documentation, never an application/bootstrap default.

```powershell
& {
  $ErrorActionPreference = 'Stop'
  & "$SourceRoot\packaging\scripts\Enable-OwnerProfileAdministration.ps1" `
    -InstallRoot $InstallRoot -DataRoot $DataRoot -OwnerPrincipal $OwnerPrincipal `
    -WorkspaceId $WorkspaceId -DeviceId $DeviceId -InstallationId $InstallationId
}
```

Expected evidence is `PROFILE_ADMIN_CAPABILITY_APPLIED` with exact readback and a private backup path, or an explicit
already-current no-op. Only then restart the existing enrolled Core through its established owner launcher. No re-enrollment,
new OAuth login, grant renewal or local approval prompts are part of this feature. Run live authenticated acceptance separately:
create -> committed revision -> explicit Files read in new profile; dashboard/chat same catalog; set default; root-change queued
work rejects old generations; delete default requires replacement; original marker files unchanged; command policy absent denies.
Do not infer these gates from a tool catalog, Linux source checks, C# serializer fixture, or capability bootstrap alone.

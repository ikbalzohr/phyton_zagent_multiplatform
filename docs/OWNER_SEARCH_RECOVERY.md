# Owner-local orphaned search recovery (offline)

This is **not an MCP tool** and must not be invoked through Files shell/execute.
It neither changes executable permissions nor adds authentication/enrollment.
No .NET rebuild is needed. Pull the reviewed source through the agreed GitHub
handoff first; source delivery does not reconcile an installed journal.

## Scope and guarantees

`packaging/scripts/owner_search_recovery.py` accepts one explicitly selected
orphaned `files_search` only, with the closed argument shape for path
`phyton_zagent_multiplatform`, profile `agentRoot`, query `allowedExecutables`
and integer `max_results` in 1..100. The installation, device, principal,
workspace and Files resource are **not hardcoded**: they must match existing
owner-private enrollment/config and the journal's original execution context.

The Router currently records the installation scheduler lock as
`access_mode=write` even for Files reads. Recovery requires that actual shared
lock contract **and** trusted `effective_access=read`, `required_scope=files:read`
and public/upstream `files_search`. It never treats a generic scheduler writer
as a read, replays a task, or marks an unknown result successful.

Default **PlanOnly** uses immutable read-only SQLite, does not create an audit,
checkpoint a database, or create WAL/SHM files. A nonempty WAL/rollback journal
fails closed: do not delete it. Normal clean shutdown/checkpoint or separately
reviewed evidence-preserving SQLite recovery is required first.

Explicit Apply requires the unchanged plan digest. It obtains an exclusive
SQLite write transaction, repeats owner/config/path/process guards, rejects
all active/queued/recovering/unknown tasks (even on another resource), checks
the full original row and physical database identity, and rejects triggers.
Only that row changes to **failed** with recovery timestamps; an existing
`finished_at` is retained (started orphans can already have a finish timestamp).
Original
error, result, payload, owner, resource, idempotency and dispatch evidence remain
unchanged. An atomic `owner_search_recovery_audit` row contains complete before
and after evidence, plan digest, reason, owner SID and timestamp. No journal,
operation or evidence is deleted. Failed guard/audit writes roll back together.

The existing scheduler quarantine predicate is unchanged. Other started
orphans continue quarantining the installation; Apply reports their remaining
count. Readback verifies the exact task and audit before reporting success.

## Owner-local Windows gate (NOT_RUN on VPS)

Use the existing owner console and owner's selected Python interpreter and
PowerShell **7** `pwsh.exe`, not an MCP-launched terminal. Stop Core through its
supported owner control and wait for Core, Router, Files, ArcMap and Web
executors to exit. The guard rejects every Core/dotnet host and every other
Python/Node host, even unrelated ones, rather than guessing command lines.
It checks inherited owner-only ACLs back to the protected DataRoot, rejects
reparse ancestors and verifies the enrolled install/DataRoot and placement.
It does not create/repair ACLs or read/decrypt OAuth/internal credentials.

From the pulled installation checkout (replace placeholders locally; do not
paste private config or the complete journal into chat):

```powershell
& '<existing-owner-python.exe>' .\packaging\scripts\owner_search_recovery.py `
  --install-root '<checkout>' --data-root '<enrolled-DataRoot>' `
  --owner-principal '<existing-enrolled-principal>' `
  --powershell '<owner-selected-PowerShell7-pwsh.exe>' `
  --task-id 'tsk_0bd717b5538149d78797d45e29abc4ec'
```

Inspect the local PlanOnly outcome. Only if its exact task is intended, repeat
the same command with `--apply --expected-plan '<plan_sha256>'`. A stale plan,
unknown context/shape, changed config or active process is a stop, not permission
to force an update. This helper has no force/skip-owner/skip-ACL mode and no
caller-supplied journal path. Do not widen its allowlist on the laptop to make
an unknown task fit.

If Apply reports failed/audit_verified and zero remaining quarantine tasks,
start Core normally; then verify discovery and **one terminal authenticated
read-only Files result**, not just an accepted receipt. Nonzero remaining
quarantine tasks need their own evidence review; never clear all or replay
uncertain writes. Windows SID/ACL/reparse/process/SQLite publication acceptance
and the real task's recovery remain **NOT_RUN** until those steps are observed.

## Isolated verification

```text
python -m pytest tests/test_owner_search_recovery.py -q -o asyncio_default_fixture_loop_scope=function
```

Tests create disposable databases using the actual Router schema extracted as
AST constants (without importing product modules). They exercise plan byte
preservation, honest failed transition, retained evidence/audit, stale-plan and
owner/context/resource denials, rollback, concurrent writer exclusion, active
work rejection, remaining quarantine, WAL/hot-journal refusal and native Linux
denial. They do not emulate or claim Windows native guard acceptance.

Parent verification before source delivery: **38 recovery tests passed**, and
complete Router regression **126 passed, 565 subtests passed**. PowerShell parser
passed; 10 isolated revocation-projection cases passed (absent/false accepted,
true/malformed rejected). These are Linux/PowerShell Core fixture results, not
Windows owner/SID/ACL/process or installed-journal acceptance.

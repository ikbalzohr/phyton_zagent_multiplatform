# Immediate MCP task recovery

`zagent_task_recover` is a native authenticated Router control, not a submitted job. It works while an installation resource is quarantined by an orphaned task. Core/Router must be running and reachable; there is no owner-terminal, clean-stop, empty-WAL, enrollment or grant-edit prerequisite.

## Two-phase usage

Call `tools/call` with name `zagent_task_recover` and arguments:

```json
{"task_id":"tsk_0bd717b5538149d78797d45e29abc4ec"}
```

`plan_only` defaults to true. Inspect the result's classification and retain its `expected_plan` digest. This call changes no task or audit data. Apply using the exact returned digest:

```json
{"task_id":"tsk_0bd717b5538149d78797d45e29abc4ec","plan_only":false,"expected_plan":"<64-character digest returned by plan>"}
```

The response is an immediate MCP control result, **not** an accepted durable task receipt. Inspect HTTP/JSON-RPC errors and MCP `isError`. A successful apply reports `audit_recorded` and `remaining_resource_orphans`. A nonzero remaining count means other tasks still quarantine that resource; this control does not clear those tasks. For independent post-apply readback, call this same tool again with only `task_id`: it checks the exact persisted row against the audit and reports `audit_verified: true` with the same plan digest. Ordinary `zagent_task_status`/`zagent_task_result` still perform their existing Files catalog checks and can remain unavailable while that backend is broken.

## Authority and scope

Both `files:read` and `files:write`, current grant membership for the original `files_search`, and the original canonical enabled tool policy are required. No new grant entry for `zagent_task_recover` is needed. An explicit recovery policy entry must use `files:write`; disabled or malformed entries deny access. Malformed global policy maps also fail closed.

The selected row must belong to the authenticated principal/workspace owner, refer to this device/installation and shared installation resource, and retain the original request/task identity, policy revision and current local grant placement/profile membership. Recovery does not call Files or its catalog. A historical `profile_generation` token is preserved as evidence, not renewed or treated as current file-access authority; every subsequent Files operation still performs normal live profile-generation checks. Only orphaned, started, canonical read-only `files_search` tasks are recoverable. The scheduler's `access_mode=write` is an installation serialization lease, not evidence that the Files search mutates data. Arbitrary write tools, unknown operations, other owners and client-supplied authority fields are rejected.

## Transaction and evidence

Recovery uses the live journal connection with its existing SQLite WAL mode, async journal lock and actual orchestrator resource condition/lease state. Active resource readers/writers, queued/nonterminal tasks, queued scheduler entries and live executor runners block recovery. It never invokes or replays an executor, manipulates WAL files, checkpoints manually or opens an immutable snapshot.

Apply validates a stable plan digest over the full original row and current local grant and policies, then performs a full-row CAS in `BEGIN IMMEDIATE`. Only `state` (`orphaned` to `failed`), `updated_at` and `recovered_at` change. Original error, result, arguments, execution context and existing `finished_at` remain intact. Full before/after evidence is inserted into `task_recovery_audit` in the same transaction; audit failure rolls back the task change. Apply reads the task back and counts remaining resource orphans with the unchanged execution quarantine predicate. Stale plans and replayed applies fail closed.

## Visibility diagnostics and source verification

`zagent_capabilities` now includes `allowlist_diagnostics` for the four fixed
native allowlist tool names. Each projection has `name` and a `blockers` array:
`UPSTREAM_NOT_DISCOVERED`, `POLICY_REJECTED`, `POLICY_DISABLED`, `SCOPE_MISSING`,
`TOOL_NOT_GRANTED`, or `AUTH_EXPIRED`. Multiple blockers may coexist. An empty
array means those visibility gates passed, not that a Files operation succeeded.
No grants, private paths or exception messages are returned, and the projection
changes no permissions or discovery cache.

Final parent source gates: complete Router suite **139 passed, 569 subtests
passed**; native Files/HTTP + recovery + visibility diagnostics **37 passed,
4 subtests passed**. Suites overlap; do not add these as a unique-test count.
Plan/apply/independent audit readback were exercised with the Files catalog
forced unavailable. Unknown historical contexts and unaudited/modified failed
rows are rejected. These are isolated source fixtures, not live recovery.

## Verification boundary

Linux isolated HTTP ASGI and live SQLite WAL fixtures cover discovery, plan/apply, authority failures, preserved evidence/timestamps, competing readers, transaction rollback, concurrent apply and persistent readback. Fixture authentication is explicitly substituted; real OAuth, Windows deployment and live application acceptance are **NOT_RUN**. The historical offline console helper is unchanged and is not used by this control.

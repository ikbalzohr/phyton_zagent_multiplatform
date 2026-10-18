# Zagent v3 — ZISB I0 Contract Freeze & Inventory

> HISTORICAL / SUPERSEDED untuk produk MCP v1. Dokumen ini menyimpan konteks baseline, bukan routing/approval/instalasi aktif. Gunakan [runbook v1](RELEASE-V1.md); UI hanya dashboard web Core dan semua produk termasuk Files versi 1.0.0.

Date: 2026-09-30
Status: COMPLETE
Scope: Point 4 / Zagent Identity & Session Binding (ZISB)
Runtime change in I0: none

## Current inventory

### Local device identity
- Current implementation: `src/Zagent.Core/Identity/MachineIdentityStore.cs`.
- Current persisted location used by Core/Manager: `<DataRoot>/config/device_identity.json`.
- Schema: 1.0.
- `device_id`: random UUID created once when the store is absent.
- `device_name`: current Windows machine name used as display metadata.
- Secret: 32 random bytes protected by Windows DPAPI CurrentUser.
- Binding fingerprint: HMAC-SHA256 over `zagent-device-binding:<device_id>`.
- Tunnel binding: HMAC-SHA256 over `zagent-tunnel-binding:<device_id>:<tunnel_id>`.
- Clone/DPAPI failure already fails closed through `IdentityMismatchException`.
- Existing identity survives restart because the same protected identity file is loaded.

### Current Tunnel identity flow
- Core passes `ZAGENT_DEVICE_ID` and `ZAGENT_DEVICE_NAME` to the local Tunnel router.
- Core passes `ZAGENT_DEVICE_ID`, `ZAGENT_DEVICE_NAME`, and `ZAGENT_DEVICE_BINDING` to tunnel-client transport.
- Router adds `zagent.device_id` and `zagent.executed_on` result provenance.
- Router currently validates a supplied `target_device_id`, but permits a missing target.
- Router status currently reports `target_validation=verify-if-supplied`.
- No native session-to-device binding store exists yet.
- No trusted-device registry or challenge/response registry exists in the local router.
- tunnel-client is an external binary; its control-plane internals are not source-owned by this repository.

### Current chat/session flow
- Router derives a durable Zagent `session_id` from host `openai/session` metadata.
- Chat registry is already persisted and independently tracks multiple chats.
- Task journal and orchestration already carry session/request/task/trace/idempotency/resource metadata.

### Current Manager identity surface
- `identity.snapshot` exposes the local UUID, name, fingerprint, creation time, protection state, and target validation mode.
- No session binding list/switch/revoke UI exists yet.

### Current Plugin/Skill state
- Editable plugin available to this development workflow: `zagent-dev`.
- Existing DEV skill enforces DEV/Production isolation.
- Point 4 production identity skill contract must consume backend identity tools; it must never persist operator/device identity itself.

## Frozen v3 identity contract

### Identity entities
- `device_id`: stable random UUID belonging to one Zagent identity store.
- `device_alias`: mutable human-readable label; changing it never changes `device_id`.
- `installation_id`: random installation lineage identifier; useful for clone/reinstall diagnostics and not a routing identifier.
- `identity_fingerprint`: safe short/public fingerprint derived from protected identity material.
- `operator_alias`: session context only, never an authentication factor.
- `session_id`: authoritative durable chat/session key from Zagent/Tunnel.
- `tunnel_id`: transport identifier; it may change without changing `device_id`.

### Session binding
Authoritative relation:
`session_id -> operator_alias + target_device_id`

Rules:
1. Backend/Tunnel owns and persists bindings.
2. ChatGPT Memory and SKILL.md are never identity stores.
3. One session has at most one active target device.
4. Switching target device is explicit.
5. No fallback to another device when the bound device is unavailable.
6. A session cannot overwrite another session's binding.

### Required native management contracts
- `identity_status`
- `identity_list_devices`
- `identity_session_get`
- `identity_session_bind`
- `identity_session_unbind`
- `identity_session_switch`
- `identity_verify_target`

Internal handshake contracts may additionally expose challenge/proof operations, but they do not replace the seven public identity management contracts above.

### Task envelope
Every enforced execution must resolve:
- `target_device_id`
- `session_id`
- `request_id`
- `task_id`
- `trace_id`

Successful result provenance must include:
- `target_device_id`
- `executed_on`
- `session_id`
- `request_id`
- `task_id`
- `trace_id`

Success invariant:
`executed_on == target_device_id`

### Standard errors
- `SESSION_IDENTITY_REQUIRED`
- `DEVICE_NOT_TRUSTED`
- `TARGET_DEVICE_OFFLINE`
- `IDENTITY_MISMATCH`
- `IDENTITY_PROOF_FAILED`
- `SESSION_BINDING_CONFLICT`
- `DEVICE_SWITCH_CONFIRMATION_REQUIRED`

### Enforcement stages
- Compatibility/observation mode may temporarily permit unbound calls during DEV migration.
- Mandatory mode requires a valid session binding for normal routed tools.
- Explicit identity-management/status tools remain callable before binding so a new session can establish identity.
- After mandatory mode is enabled, missing binding is `SESSION_IDENTITY_REQUIRED`; mismatch is `IDENTITY_MISMATCH`; no silent fallback is permitted.

## Migration contract
- Preserve every valid existing `device_id`; do not regenerate only because of v2 -> v3 upgrade.
- Existing schema-1 identity is migrated in place/forward without losing its UUID or protected secret.
- Production identity observed before this work must be preserved during actual production migration.
- A clean reinstall with no retained identity store may create a new identity.
- A copied store that cannot decrypt its DPAPI secret is rejected and cannot silently become a trusted duplicate.

## I0 exit decision
I0 is complete. The existing code already supplies a useful I1 foundation (stable UUID, DPAPI secret, fingerprint, target check, provenance), but Point 4 is not complete because session binding, mandatory exact-target resolution, trusted-device/handshake state, full Manager binding surface, plugin identity UX contract, migration staging, and the fault-injection matrix are still missing.

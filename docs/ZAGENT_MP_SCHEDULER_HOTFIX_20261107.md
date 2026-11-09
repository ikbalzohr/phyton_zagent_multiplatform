# Zagent Multi Platform — Production comparison, scheduler/orphan hotfix

Date: 2026-11-07. Operator approval: Zagent Production session bound to local trusted device. Source checkout: `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`, branch `zagent-v1`, HEAD `ade49ed`. **All unrelated dirty checkout changes preserved; no Git commit or push.**

## Observed architecture differences

Production `appBridge/production/Zagent/v3/agents/tunnel/engine/router/server.py` computes policy-specific resource keys and read/write access based on tool category; Production Files backend supports path/ancestor-aware read/write resources. Multi Platform's `scheduler_meta` historically used one `installation:<installation_id>` write lease for *all* tools, including `files_ping` and `files_read`, which serialized concurrent readers. Its task-orphan dispatch guard also blocked *read-only* Files operations after an uncertain Files command, making benign health checks unavailable. A failed MCP `ensure_initialized` could be marked `orphaned` despite no `tools/call` being sent.

Core/Files update audit: Production Files advertises self-update and exposes a Core-broker staging/request design. Multi Files `updater.py` contains equivalent capability logic, but its `files_capabilities` advertises `self_update:false`. The `FilesUpdateRequestProcessor.ProcessPendingAsync` method was not found wired into a Core call path in either audited C# checkout. There is **no verified, safe unattended full Core EXE self-restart/update contract** in Multi. Do not flip an advertising flag or assume self-update works until a separate out-of-process Core lifecycle implementation is tested.

## Source changes and safety contracts

- `agents/tunnel/engine/router/orphan_conflicts.py`: strictly verified non-effect `arcmap_execution_capabilities` orphan classified like `arcmap_ping` (without deleting its journal row); exact reviewed Files read targets can bypass unrelated write orphan conflict. Malformed context, mismatched device, writes and unknown tools fail closed.
- `agents/tunnel/engine/router/server.py`: applies narrowly scoped safe observation exception to orphan blocking; still performs normal grant, policy, device, expiry, profile generation and tool-mapping validation.
- `agents/tunnel/engine/router/execution_context.py`: trusted Files `required_scope=files:read` + `effective_access=read` uses a reader lease; existing installation resource key retained. Writes retain exclusive installation lock; no claimed parallel writes.
- `agents/tunnel/engine/router/task_recovery.py`: read-only search recovery candidate accepts either legacy scheduler `write` lease or trusted new `read` lease; all other validation/audited plan-apply constraints remain.
- `agents/tunnel/engine/router/registry.py`: MCP upstream initialization failures *before dispatch* become `PreDispatchRejected(UPSTREAM_INITIALIZATION_UNAVAILABLE)`, preserving the definitive `failed` journal outcome. Errors after actual dispatch are **not** blindly reclassified or replayed. Existing Headless 75-second timeout contract preserved.

Tests modified: `test_predispatch_rejection.py`, `test_files_scope_authority.py`, `agents/files/engine/tests/test_native_multiprofile_windows.py`; added `test_safe_observations_and_parallel.py`.

## Verified results

- RED test before fix: `test_safe_observations_and_parallel.py` import failed on missing reviewed `safe_read_target`; RED test before `registry.py` fix demonstrated uncaught upstream initialization error.
- Focused GREEN: 8/8 tests (incl. genuine durable read-read concurrency while writer waits; verified orphan read vs writer blocking; pre-dispatch failure).
- Combined Windows bundled Tunnel Python 3.11.9 unittest: **64/64 PASS**, zero fails/errors/skips, after all patch changes; no live journal or user files accessed by tests.
- All five source modules and deployment Python compiled successfully.
- Source payload staged with exact SHA-256 backup and manifest preservation, bundle `_validation/mp-router-recovery-20261107/before`. Original installed manifest SHA-256 `ac31f366fb32481cd9c12c7dadcf890138f97858ffa94cc0de4c362476ac2b47`. New installed manifest SHA-256 `ef0a3ffe21aed3c1a1c5e551e25b757f571c629217fbd12596fbf1c679e41897`, 12,005 records retained.
- Production sent authenticated owner HTTPS Core lifecycle stop/start **only** for `system.tunnel`; script `_validation/mp-router-recovery-20261107-deploy.py`, status source test exit 0 and live verified. Tunnel new PID `16604` Ready; Files PID `10980` Ready, Web `9060` Ready, ArcMap `13228` Running/Degraded because desktop bridge offline, QGIS `7824` Ready. Unrelated PIDs unchanged.
- Genuine public Multi Platform `files_ping(profile_id=agent-dev)` succeeded under original historical Files writer orphan; task `tsk_8c96c8f2ab004ba08021b49699fa95fb`. Genuine public `files_read(path=ZAGENT.md)` also succeeded, task `tsk_6f97b582e4024ac2b99071f5ac08bb89`.
- `zagent_reconciliation_status` still shows `tsk_a02e8da4558f4801b05ff072b5035f18` (Files command) manual-owner reconciliation required, and two no-effect ArcMap probes classified nonblocking. **Historical journal untouched**.

## Remaining gates (not claimed complete)

1. Mutating Files commands and QGIS Files-authority calls can remain blocked by the original historical uncertain Files command; verify its Core management side-effects and support genuine owner-approved audited resolution (without journal deletion, scheduler bypass or blind replay).
2. Implement and test out-of-process **Core binary self-update/restart** independent from the service's own transport and durable task, with restart ACK and rollback. Files updater staging is not proof of a full Core self-updater.
3. Improve disjoint mutating-resource scheduling after proving filesystem/installation path aliasing safety; this hotfix guarantees **parallel reads**, not arbitrary parallel writes.
4. Run actual public ArcMap Headless/CURRENT isolated acceptance through a compatible client and genuine licensed worker. Public catalog visibility, fixture tests and current Desktop-Degraded are not public execution acceptance.
5. Preserve Production control plane, all user data/grants, historic journal and unrelated changes; do not auto-commit/push.

## Verification files

- `_validation/mp-router-recovery-20261107/plan.json`, `payload-applied.json`, `success.json`, `verify.json`
- `_validation/mp-router-recovery-20261107/before` = exact predeployment rollback bytes including manifest
- `_validation/mp-router-recovery-20261107/staged` = new exact payload and manifest.

## Historical restart-task evidence found after deployment

Using Production Files and pin-verified owner Dashboard GET, the old Multi deployment bundle `_validation/arcmap-headless-deploy-20261107-chat/tunnel-restart-ack.json` contained management operation ID `2bab324a9e3c486496cfacb9867fea24`, accepted for `system.tunnel` restart. A fresh authenticated `GET https://localhost:19444/api/management/v1/operations/2bab324a9e3c486496cfacb9867fea24` confirmed `method=lifecycle.agent`, `state=succeeded`, `updatedAtUtc=2026-11-07T06:22:06.7253625Z`. This proves the Core lifecycle operation completed; it does **not** on its own prove the entire Files command receipt succeeded. The associated orphaned Files task remains in the Router journal, unchanged. An owner-authenticated audited reconciliation pathway should use this evidence without blind replay or deleting the task record.

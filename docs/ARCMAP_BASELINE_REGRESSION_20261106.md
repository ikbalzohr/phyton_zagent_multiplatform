# ArcMap legacy baseline harness repair — 2026-11-06

## Result and boundary

**Windows source-fixture verification PASS:** all original 26 baseline test methods remain, and the combined baseline + Stage3 + layer-identity suite runs 62 tests without failures, errors or skips. The combined suite also passes in both explicit orders in one process with restoration sentinels. These are overlapping executions of the same tests, not additional unique coverage.

Only `tests/arcmap/test_bridge_regression.py` and this new document are owned by this repair. No production source, guard, runtime compatibility alias, installed configuration, grant, client, live map, deployment or service was changed. No commit or push was performed. Other workers' existing source/test/doc changes were preserved.

- Host checkout: `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`; native Files profile `agent-dev`, cwd `.`.
- HEAD verified as `ade49ed81a0addec93c481bd3c62e2dc3e38c6be` (working tree includes the parent-coordinated Stage3/layer changes).
- Interpreter: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\runtime\python\python.exe`, parent-verified Python 3.11.9 with `mcp.server.MCPServer`; stdlib `unittest`, no pytest installation.

## Preserved and reproduced RED

Original raw bytes were copied, before editing, to ignored `_validation/arcmap_baseline_red_20261106/test_bridge_regression.original.py`. SHA-256: `c2d4fc6f7f9a61550c18bb7a05ae6a9e1b3e6524792f06b320244c55027420fd`. Native preservation receipt: `tsk_4677c01ee5ee4a6eadccab44f9da64f8`.

The original diagnostic receipt `tsk_d399ad00d14f496c8f3154a12d64c08a` ran 26 tests with **8 errors + 1 failure, 0 skips, success=false**. Its collector exited 0; that was not a passing suite. The parent's original failing command receipt is `tsk_ed07a155b9544b0b807bb177a00ada5a`.

This repair independently reproduced all nine failures from the preserved unchanged bytes: `tsk_6221ac79500440e8b01dd5cda0b634d0`, **collected 26 / run 26 / failures 1 / errors 8 / skips 0 / success=false**. This diagnostic collector also deliberately exited 0, not a green test exit. It neutralized inherited Zagent identity variables and redirected only the real source runtime-locator read to a nonexistent isolated validation path. No product authentication function was stubbed. The reproduced thread tracebacks show both worker calls rejected at the authenticated service boundary.

| Original failing method | Observed reason | Current source contract / harness correction |
|---|---|---|
| `test_mutation_does_not_switch_after_observation` | `AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED` | Bind complete synthetic issuer context before the real service call. Retain changed-document denial and exactly one health ping, no mutation. |
| `test_offline_write_is_not_queued` | `ipc_client.INBOX` absent | Use `_channel(IPC_ROOT, DATA_ROOT)['inbox']`; retain offline denial and empty-queue assertion. |
| `test_owner_status_retries_transient_read_lock` | `_read_owner_json` requires `owner_path` | Supply the current channel owner path; verify all three retry reads target exactly that path. |
| `test_real_arcmap_window_capture_is_registered_and_guarded` | ignored `runtime-tools.snapshot.json` absent | Import actual source server registration and enumerate the installed SDK's real `list_tools`; compare actual names/count to source registration. Invoke the registered capture callable's confirmation and foreign-session denial before any capture/service call. No snapshot is fabricated. |
| `test_stale_owner_fails_closed_and_write_is_not_queued` | `ipc_client.INBOX` absent | Current channel API; stale heartbeat must still deny write without queueing. |
| `test_timeout_removes_queued_work` | `ipc_client.INBOX` absent | Current channel API; real timeout still removes the queued command and reports not executed. |
| `test_unknown_outcome_timeout_is_never_auto_replayed` | `ipc_client.INBOX` absent | Current channel API; unknown outcome still warns against automatic replay, and atomic enqueue is now asserted exactly once. |
| `test_visual_session_provenance_and_recovery` | `owner_key` requires `principal_id`/`workspace_id`; legacy session-only isolation assumption | Owner identity is principal + workspace, not transport session or resource. Same owner sees both sessions' artifacts, including after reload and from another resource; different principal or workspace cannot list them, even with copied foreign manifests and `_all_sessions=True`. Session override denial, provenance, prune and recovery remain exercised. |
| `test_two_session_mutations_are_serialized_by_global_arcmap_lock` | both threads lacked authenticated fields; result count 0 | Each thread binds/resets both ContextVars with real verified fixture context; collect worker exceptions explicitly. Distinct service instances still serialize globally, complete twice and preserve distinct request provenance. Add queued-expiry denial after waiting for the same lock, with no transport. |

The observed failures were obsolete fixture/API assumptions, not evidence that production guards should be weakened. No unresolved product bug was exposed by these repaired tests.

## Isolation and retained coverage

Setup now occurs in `setUpModule`, not at discovery/import time. `addModuleCleanup` plus `ExitStack` restore environment, `sys.path`, bytecode policy and pre-existing `arcpy`, `core`, `features`, `mcp_server` and `stage3` module identities. Every ordinary test and worker thread resets its context tokens. The fixture uses real `execution_context.verify`, synthetic `TrustedMetadata` and disposable device identity; it does not obtain a private token or installed grants, nor replace auth/current/safety methods.

All writable/config/IPC/visual roots are unique directories under ignored `_validation`. Unchanged bridge config source executes with a fixture-local `__file__` so its relative runtime locator is also isolated. A constructor-only invalid-service loopback endpoint permits source server registration without installed workflow settings; no workflow request is issued. The real safety policy remains active, with only fixture `allow_live_write` values scoped by `patch.dict` for mutation-specific tests.

Retained assertions include command deadline rejection, missing deadline rejection, document switch/reopen, bridge restart, valid-context acceptance, **2,341 legacy command quarantine**, expired-command rejection before dispatch, orphan queue cleanup, offline/stale-owner denial, no replay after unknown outcome, active dataframe selection, partial scale state, PNG/PDF validation and truncated-file rejection, owner heartbeat atomicity, named-mutex exclusivity, global live-tool serialization, timing markers, typed ArcObjects source markers and long-render timeout budgets. No test is skipped or removed; AST method-name set equality confirms all original 26 names.

An initial implementation-only fixture mistake assigned the path string returned by `TemporaryDirectory.__enter__` to `TEMP`. Receipt `tsk_b5ff2ec61dbe4a5b8f02ba80140d4479`: collected 26, run 0, failures 0, module errors 1, skips 0, process exit 1. It is preserved in `green-first.log` despite that historical filename. A CAS patch retained the TemporaryDirectory object separately; all later runs below are green.

## Executed gates and receipts

| Execution | Collected | Run | Failures | Errors | Skips | Process exit | Native task |
|---|---:|---:|---:|---:|---:|---:|---|
| Repaired baseline, standalone stdlib runner | 26 | 26 | 0 | 0 | 0 | 0 | `tsk_744f62c3ae64470d9b7aa3a70180d3cb` |
| Baseline with pre-existing module/context sentinels | 26 | 26 | 0 | 0 | 0 | 0, shared process | `tsk_d569a0ed9f5d4d149ffa50dcccec055f` |
| Baseline → Stage3 → layer identity | 62 | 62 | 0 | 0 | 0 | 0, shared process | `tsk_d569a0ed9f5d4d149ffa50dcccec055f` |
| Layer identity → Stage3 → baseline | 62 | 62 | 0 | 0 | 0 | 0, shared process | `tsk_d569a0ed9f5d4d149ffa50dcccec055f` |
| Standard CLI discovery: baseline → layer identity → Stage3 | 62 | 62 | 0 | 0 | 0 | 0 | `tsk_ef70ef26c2504cd5afa1238e9f6774a6` |

The shared-process command re-collects suites between each execution. After each it asserts exact environment/path restoration, bytecode policy, module-map/object identity preservation (including explicit ArcPy/core/features sentinels), both ContextVar restoration and removal of the baseline temporary root. All restoration assertions passed. Suite size is 26 baseline + 18 Stage3 + 18 layer identity; repeated orders are not summed as unique tests.

Standard CLI command actually executed through Files MCP, cwd `.`:

```text
D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\runtime\python\python.exe -B -m unittest discover -s tests/arcmap -p test_*.py -v
```

Native terminal task arguments preserve the exact custom runner/reproduction scripts. Logs and `combined-summary.json` are under ignored `_validation/arcmap_baseline_red_20261106/`.

`git diff --check -- tests/arcmap/test_bridge_regression.py` passed, exit 0: `tsk_91331f7fac71480dbe01b199bce10849`. Git emitted only its LF-to-CRLF advisory; raw-byte hashes below describe the current bytes, not Git-normalized text.

## Raw-byte SHA-256 evidence

Original-to-final CAS chain: native write `tsk_b15154bc76ab4e62b08149789ce87923` expected original `c2d4fc...`, produced intermediate `e7b63f8e039d1643b9ea77132d2599187341743a43059681a4522860a5c35949`; exact-target readback matched. Native patch `tsk_bc1b72eac10e45f69f09ae3cacde5e80` expected that intermediate hash and produced final `931e916b376c5eb4e2aa8f8bed12b5223a82cfdf19257c4b27972267060d6bbc`. Exact-target readback matched in baseline and combined receipts. No text-projection digest was used as a CAS value.

Hashes read back by `tsk_8752ad7e2f784e968470cbf67135cffd`:

| File | SHA-256 |
|---|---|
| `tests/arcmap/test_bridge_regression.py` | `931e916b376c5eb4e2aa8f8bed12b5223a82cfdf19257c4b27972267060d6bbc` |
| `tests/arcmap/test_stage3_safety.py` | `608557ecf724c74d9f3219fa27de0335c4cef293b069942f779b6b39bd2a96dc` |
| `tests/arcmap/test_layer_identity.py` | `0bf8267495aeec170e2275f1f7f48967af40df062f1144512964dbaca3aa7005` |
| `agents/arcmap/engine/mcp_server/services.py` | `9525e5a62e8aaa2b1cab251a4aa60e6b790dfcdfcf7e1acf95bdd0b22e0298c0` |
| `agents/arcmap/engine/stage3/mcp_tools.py` | `9f8c384458dd686a3654e5329990540a423be0232f0c8600eea46b88b5a123d9` |
| `agents/arcmap/engine/arcmap_bridge/core/current_map.py` | `0604d2879ce1444638ccb16efc7dd74f71578c44c86bfcdad91a099026fe7cc4` |
| `agents/arcmap/engine/arcmap_bridge/features/layers.py` | `902dfc4460e23d8e0c98985f3c8eebbd8847cf4a42bdc928299964820e9abce5` |

Relevant raw log hashes:

- `red-reproduced.log`: `2728438eb417359dba68b507c93a267d3290d8613d70b0729643935d43426894`
- `green-second.log`: `3431292886dee382875023ef69b40c16f7913314dad1f98b1c74f8b5eee68176`
- `baseline-sentinel.log`: `5c36af1a4f48a1d94dde10577f1c9b6c8ceb0cead26c367f0d05b0a23c12030b`
- `combined-forward.log`: `2174cc747f90651d66914a029cb025a89da3200c8f5464cc0f2ae5782d11b765`
- `combined-reverse.log`: `191536108c9c029fcff07e5a343578e9d461163bb721657f841967d04bb333b5`

## NOT_RUN / no live acceptance claim

- Live ArcMap/ArcObjects UI, real MXD writes, live Add-In dispatch and genuine window capture: **NOT_RUN**.
- Installed owner ACL/DPAPI/private-token provisioning and actual authenticated Router-to-ArcMap public-client protocol dispatch: **NOT_RUN**.
- ChatGPT/Claude client discovery and authorization acceptance: **NOT_RUN**.
- Deployment, installed-runtime replacement, restart, permission edits, commit and push: **NOT_RUN / not authorized for this repair**.
- Python 2.7 bridge-runtime compatibility: **NOT_RUN by this harness worker**; parent owns any separate compatibility check.

No model fallback was observed or requested; no delegation or global model setting was used by this repair worker. Parent integration/review owns any remaining roadmap and live gates.

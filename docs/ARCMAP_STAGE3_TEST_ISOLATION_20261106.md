# ArcMap Stage3 test process isolation — 6 November 2026

## Outcome and scope

Stage3 fixture leakage repaired on the authoritative Windows source through authenticated native Files MCP, profile `agent-dev`, cwd `.`:
`D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`.
Branch/revision inherited from the coordinator: `zagent-v1`, `ade49ed81a0addec93c481bd3c62e2dc3e38c6be`.
The current owner direction is Windows-only source, no GitHub handoff; obsolete VPS/GitHub statements in WORK.md do not authorize another checkout or commits.

Only these source/document paths belong to this repair:
- `tests/arcmap/test_stage3_safety.py`
- `tests/arcmap/test_stage3_fixture_isolation.py` (new)
- this document (new)

No product code, real authentication/safety implementation, policy, grant, private configuration, installed payload, live map, service lifecycle, Git commit/remotes/push/pull, or sibling suites were modified. Existing owner/coordinator work was preserved. Disposable runners, original raw bytes and full logs are in ignored `_validation`; native `git check-ignore` receipt `tsk_7a5af5a24b7b4a3b9cdf67b0b352a785` exited 0.

## Repair

The former import-time block removed all `ZAGENT_` / `ARCMAP_` environment values, installed disposable values, prepended ENGINE to sys.path and imported cached product modules during discovery, without restoration. It also assumed `_validation` already existed.

Setup now runs only in unittest `setUpModule`. An ExitStack is registered with `unittest.addModuleCleanup` before mutation, so unittest closes it after success or setup failure. It snapshots/removes only the owned `mcp_server` / `stage3` module trees, restores their exact cached object identities, restores environment, sys.path and bytecode flag, resets both request-context ContextVar tokens and removes the disposable TemporaryDirectory. The TemporaryDirectory object is retained separately from `enter_context`'s string result. `_validation` is created with parents when necessary; its persistent parent is not recursively deleted.

The entire `class Stage3Safety` suffix, including all 18 original methods/assertions, is byte-for-byte unchanged from the saved original. No service/auth/safety guard or transport alias was added or weakened. The original service and raw IPC boundary substitutes remain the same.

## Vertical test-first evidence

Each behavior was added and actually run before its corresponding fixture change. Counts are outer unittest test methods, not unique totals across invocations; failing subtests may exceed methods.

| Slice | Genuine RED | Minimal change / GREEN |
| --- | --- | --- |
| Discovery must preserve environment/path | `tsk_48881e30df8f4a96a19b2995ee193a43`: 1 run, 1 failure, 0 errors/skips, real exit 1; assertion `discovery changed environment` | Defer setup/imports and register env/path/temp cleanup; `tsk_2fdaf4f62c064ddbbfa5fa73a17358f8`: 1 run, no failures/errors/skips, exit 0 |
| Complete execution/repeat must tolerate and restore cached sentinel modules and ContextVars | `tsk_e5a791ba255e4a808d615cdbce2aa353`: 2 outer run, 2 failing iteration subtests, no outer errors/skips, real exit 1; nested setup cannot import services from cached sentinel package | Evict/restore the two owned module trees; preserve bytecode; `tsk_61217554705c46fb9943d1e01d35c0a7`: 2 outer run, no failures/errors/skips, exit 0; nested Stage3 18/18 twice |
| Setup failure must reset both fresh ContextVars as well as process state | `tsk_a6c48d311450401dba15d4ce4692889d`: 3 outer run, 1 failure, 0 outer errors/skips, real exit 1; `correlation leaked after setup failure` | Register both ContextVar token resets before final Stage3 import; `tsk_4ee554853d0f4f84b90dec88961927b7`: 3 outer run, no failures/errors/skips, exit 0 |

Full immutable phase logs:
- `_validation/stage3-isolation-red-discovery.log`
- `_validation/stage3-isolation-green-discovery.log`
- `_validation/stage3-isolation-red-repeat.log`
- `_validation/stage3-isolation-green-repeat.log`
- `_validation/stage3-isolation-red-setup-failure.log`
- `_validation/stage3-isolation-green-setup-failure.log`

Original pre-repair bytes: `_validation/stage3-isolation-original.py`, SHA-256 `608557ecf724c74d9f3219fa27de0335c4cef293b069942f779b6b39bd2a96dc`. The original copy was saved by the first RED command before repair.

All RED/GREEN receipts use the approved interpreter below with `-B -X utf8 -c`, `unittest.defaultTestLoader.discover('tests/arcmap', pattern='test_stage3_fixture_isolation.py')`, TextTestRunner verbosity 2, redirect_stdout/redirect_stderr into the named full log, and `sys.exit(int(not result.wasSuccessful()))`. Exact submitted argument strings, readback prefixes and per-operation paths remain in the named native terminal task receipts. No exit-0 capture wrapper disguises RED as PASS. Terminal envelopes sometimes truncate a failed command; the complete runner stream and JSON count/exit row remain in its log.

The setup-failure test deliberately raises only at the final fixture import boundary after real module imports, changes both fresh ContextVars, and verifies unittest's automatic module cleanup. Its nested runner is intentionally 0 run / 1 error; the outer test asserts that exact expected failure and state restoration. Such nested diagnostic ERROR text is not an outer suite failure. No product verification/authentication function is mocked.

After GREEN, discovery assertions were strengthened to check cached identities, bytecode and absence of fixture creation. The sentinel test's own ContextVar tokens are also reset by test cleanup.

## Final verification: real results, including failures

Approved unchanged interpreter:
`D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\runtime\python\python.exe` (Python 3.11.9 established by the coordinator; stdlib unittest, no pytest installation).

Disposable exact runner: `_validation/stage3-isolation-final-runner.py`, raw SHA-256 `6cd942574c091dc38628bb93b9a5ed510b2429397e76d2c80d69896ea57a6c12`.
It compares every production/sibling source hash, verifies the original Stage3 class raw bytes, imports all four modules without fixture side effects, and records collection/run/fail/error/skip/state results. Sentinel modules for arcpy/core/features/mcp_server/stage3, original ContextVar values, environment, sys.path, bytecode False, and temporary-directory membership are checked after every phase. Only test-owned modules are substituted and evicted before real fixtures load product code.

Equivalent direct rerun commands (cwd `.`, Files profile `agent-dev`, timeout 240 seconds):

```text
<approved-python> -B -X utf8 _validation/stage3-isolation-final-runner.py individual
<approved-python> -B -X utf8 _validation/stage3-isolation-final-runner.py combined
```

Actual individual invocation `tsk_ae005c7e064741429f7f4fe7ce633e10` used `-B -X utf8 -c` to read raw runner/new-test bytes, assert their exact hashes, set `sys.argv=['_validation/stage3-isolation-final-runner.py','individual']`, then `runpy.run_path(sys.argv[0], run_name='__main__')`. Actual combined invocation `tsk_dc356022d3af4b1da2b14a721738b6ae` used the second command above. Individual phases share one process; all three combined passes share another single process, not one child process per suite/pass.

| Phase | Collected / run | Failures / errors / skips | State unchanged | Phase exit |
| --- | --- | --- | --- | --- |
| focused isolation | 3 / 3 | 0 / 0 / 0 | true | 0 |
| original baseline suite | 26 / 26 | 1 / 0 / 0 | true | 1 |
| unchanged layer suite | 18 / 18 | 0 / 0 / 0 | true | 0 |
| Stage3 original assertions | 18 / 18 | 0 / 0 / 0 | true | 0 |
| original three combined | 62 / 62 | 1 / 0 / 0 | true | 1 |
| all four forward: baseline, layer, Stage3, isolation | 65 / 65 | 0 / 0 / 0 | true | 0 |
| all four reverse | 65 / 65 | 0 / 0 / 0 | true | 0 |
| all four forward repeat | 65 / 65 | 0 / 0 / 0 | true | 0 |

Individual command real process exit **1**, not PASS; combined command real process exit **0**. The three isolation methods additionally execute the unchanged 18 Stage3 methods twice internally, and inject one expected setup failure; these nested executions are not added to the outer 65-test collection count.

Machine-readable exact rows: `_validation/stage3-isolation-final-individual.json` and `...-combined.json`. Full phase streams: `_validation/stage3-isolation-final-{focused,baseline,layer,stage3,originals,forward,reverse,repeat}.log`. Do not overwrite or dismiss the baseline/originals failure logs because later combined passes succeeded.

### Separate observed baseline issue

The unchanged `test_visual_session_provenance_and_recovery` failed at line 262: after publishing `one` and `two`, `visual_store.latest(source='arcmap')` returned `one` instead of `two`. Same failure occurred in the original-three combined phase. Every process-state comparison still passed. The subsequent forward/reverse/repeat passes all passed without changing this source or any test. This is an observed intermittent/latest-order issue, **not a proven Stage3 regression or a proven root cause**. Existing visual_store sorts `capturedAt`; clock precision/order deserves separate investigation. No sleep, clock mock, retry-to-green, production fix or baseline assertion edit was introduced. The preserved first failure remains a release/integration caveat.

## Raw hashes and write/readback evidence

| Path | Final raw SHA-256 |
| --- | --- |
| tests/arcmap/test_stage3_safety.py | e893713d523bfc704d29313d541c57a331a20077548fd6c81a440a88c781c5dc |
| tests/arcmap/test_stage3_fixture_isolation.py | ee738ebcbad8accfa5d07fa163ef8d647961a1153706256945811ed316e83c38 |
| agents/arcmap/engine/stage3/mcp_tools.py (unchanged) | 9f8c384458dd686a3654e5329990540a423be0232f0c8600eea46b88b5a123d9 |
| agents/arcmap/engine/mcp_server/services.py (unchanged) | 9525e5a62e8aaa2b1cab251a4aa60e6b790dfcdfcf7e1acf95bdd0b22e0298c0 |
| agents/arcmap/engine/arcmap_bridge/core/current_map.py (unchanged) | 0604d2879ce1444638ccb16efc7dd74f71578c44c86bfcdad91a099026fe7cc4 |
| agents/arcmap/engine/arcmap_bridge/features/layers.py (unchanged) | 902dfc4460e23d8e0c98985f3c8eebbd8847cf4a42bdc928299964820e9abce5 |
| tests/arcmap/test_bridge_regression.py (unchanged) | 931e916b376c5eb4e2aa8f8bed12b5223a82cfdf19257c4b27972267060d6bbc |
| tests/arcmap/test_layer_identity.py (unchanged) | 0bf8267495aeec170e2275f1f7f48967af40df062f1144512964dbaca3aa7005 |

Every existing-file edit used native files_patch raw-byte expected_sha256 CAS; digest chain Stage3: `608557ec...` → `7eb94b61...` → `5f151c7a...` → `e893713d...`. Final patch receipt `tsk_9773dd7d1dd546ea8f5ecfa77c8f1297`; exact setup readback in GREEN `tsk_4ee554853d0f4f84b90dec88961927b7`. Final native hash receipts: Stage3 `tsk_3bac03cc358f47ec898d8c4096bc6253`; isolation `tsk_b30fb7ecde494e4c84aecf45b6393949`. New-test exact raw readback/hash assertion also appears in `tsk_ae005c7e064741429f7f4fe7ce633e10`. This document's own final raw hash and exact-target readback are returned in the handoff rather than made self-referential here.

## Quota, remaining gates and handoff

Latest owner quota correction supersedes the earlier 5% rule: **pause when ANY account window has remaining_percent strictly below 10 (used_percent >90)**. Exactly 10% remaining is not below threshold. Check supported read-only `hermes -p ikbal usage --provider openai-codex --json` before mutation/tests and each medium batch; compute every real window's remaining value. On threshold or confirmed fallback, do not start new writes/tests; preserve accepted receipts/uncertain operations and return QUOTA_PAUSE. If monitoring is unavailable, stop conservatively without inventing percentages. Do not change global settings or activate banked resets.

Checks remained above threshold. Last pre-document sample: usage_api Plus, fetched `2026-11-06T15:33:53.422199+00:00`; Session used58 / remaining42%, Weekly used51 / remaining49%, minimum42%. No confirmed fallback, no banked reset activation. A final supported sample is supplied in the worker handoff.

Remaining: coordinator review/integration and investigation of the separately preserved intermittent baseline assertion. Live ArcMap / real ArcObjects / live OAuth Stage3 / installed payload acceptance remain NOT_RUN and are not proved by fixture tests. No live-map tool, deployment or restart was performed. No uncertain external operation remains at this documentation checkpoint; terminal accepted operation receipts were reconciled before reporting results.

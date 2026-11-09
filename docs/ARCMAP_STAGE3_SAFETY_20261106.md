# ArcMap Stage3 P0 safety alignment — 6 November 2026

## Status and boundary

**Windows source implemented; isolated service-boundary unittest PASS (18 tests, no failures/errors/skips). Not deployed or live-accepted.**

Checkout: `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`, branch `zagent-v1`; starting revision supplied by coordinator: `ade49ed81a0addec93c481bd3c62e2dc3e38c6be`.
All writes and execution used authenticated native Files MCP, profile `agent-dev`, repository-relative paths and cwd `.`. No commit, push, deploy, restart, grant/policy/configuration change, or live ArcMap mutation was performed. Headless/Attached mode remains coordinator-owned design work, not an implementation in this change.

## Implementation

- Every one of the 20 existing Stage3 public wrappers calls the installed runtime namespace's actual `AgentServices.call`, with an explicit supported operation kind. Public wrapper names, signatures, payloads and registration behavior are unchanged.
- Unknown action raises `STAGE3_UNKNOWN_ACTION`; missing/non-AgentServices service raises `STAGE3_SERVICE_REQUIRED`. Raw IPC imports, loaded-module scanning, child-transport discovery and speculative signature retries were removed. There is no operational TypeError replay.
- The actual service retains authenticated principal/workspace/resource presence, deadline, write access, upstream-read-only denial, the shared ArcMap lock, safety policy and document preflight/context binding. No safety permission defaults were changed.
- Composite safety checks execute inside the same authenticated locked service call and before any transport. Builders always clear layers and therefore require `destructive`; their requested save/export effects require `save`/`export`. Blank initialization requires `destructive` only when `clear_layers` is enabled. Checkpoint restoration requires both `destructive` and `save`: the existing backend copies an MXD on disk and does not reopen CURRENT.
- Successful `live_write` retains independent current-map observation. A false readback or `ArcMapBridgeError` during readback returns `ok=false`, `POST_ACTION_VERIFICATION_FAILED`, `action_may_have_completed=true`, and failed verification; the action is not replayed. `verification.saved=false` does not claim the CURRENT document was saved. Export/save/geoprocessing are not mislabeled as verified live-document edits.

### Explicit action classification

Kinds below are existing kinds from `mcp_server/safety.py` and `services.py`, not new policy strings.

| Bridge action | Primary kind | Additional safety checks |
| --- | --- | --- |
| stage3_health | read | none |
| stage3_blank_init | live_write | destructive when clear_layers |
| stage3_ensure_dataframe | live_write | none |
| stage3_set_page_a4 | live_write | none |
| stage3_create_text | live_write | none |
| stage3_create_neatline | live_write | none |
| stage3_create_legend | live_write | none |
| stage3_create_north_arrow | live_write | none |
| stage3_create_scale_bar | live_write | none |
| stage3_create_featureclass | geoprocessing | none |
| stage3_create_xy_featureclass | geoprocessing | none |
| stage3_create_geometry_features | geoprocessing | none |
| stage3_add_dataset_auto | live_write | none |
| stage3_ingest_folder | live_write | conservative even when add_to_map=false |
| stage3_set_extent_auto | live_write | none |
| stage3_build_blank_a4 | live_write | destructive; save/export when requested |
| stage3_build_no_data_a4 | live_write | destructive; save/export when requested |
| stage3_save_checkpoint | save | none |
| stage3_restore_checkpoint | destructive | save |
| stage3_export_current | export | none |

## Real verification

Executable (existing shared ArcMap runtime; no installation/package changes):
`D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\runtime\python\python.exe` (Python 3.11.9 established by coordinator).

Final native Files invocation:

```json
{
  "executable": "D:\\3-Ikbalzohr\\Agent\\ZohrSystem\\Zagent Multi Platform\\agents\\arcmap\\runtime\\python\\python.exe",
  "args": ["-m", "unittest", "discover", "-s", "tests/arcmap", "-p", "test_stage3_safety.py", "-v"],
  "cwd": ".",
  "profile_id": "agent-dev",
  "timeout_seconds": 120
}
```

Final receipt **`tsk_45e138d7dc974f8099af8eccd78ce13d`**: real exit code **0**, `Ran 18 tests in 0.070s`, `OK`, output not truncated. Prior full GREEN: `tsk_194c505c00ef4e88ac8c013864579009` (18 tests, exit 0).

Fixtures use the real `AgentServices`, real `SafetyPolicy`, real request-context ContextVar, and real shared service lock. Only the IPC boundary is replaced; no service call/auth/guard methods are mocked. Each runner is a fresh process with inherited Zagent identity variables neutralized and temporary config/data/IPC roots beneath ignored `_validation`. Both the service's imported transport alias and the legacy IPC module transport are isolated so the initial vulnerable path cannot touch a live bridge. These are service-boundary authorization tests, not a claim of OAuth/signature or live-client acceptance.

Coverage includes all 20 wrappers rejecting missing authentication and expired context; all 19 non-health wrappers rejecting read access; actual supported safety kinds; read health; successful action transport exactly once; no fallback on unknown action/missing service; an operational TypeError after a recorded effect not being replayed; upstream read-only denial; preflight document mismatch; both negative and exception readback failures; composite destructive/save/export gates and disabled-effect options; and two concurrent authenticated calls serialized by the real service lock.

### Vertical RED → minimal fix → GREEN receipts

Counts are per invocation, not a sum of unique tests. Subtest failures may exceed the number of test methods.

| Behavior slice | RED receipt and actual result | GREEN receipt and actual result |
| --- | --- | --- |
| Read context cannot create text | `tsk_25bb23ae3c174d18b4bda4c702bb0b8d`: 1 test, 1 assertion failure (PermissionError not raised) | `tsk_17b2715ee5724b22abbe5ad51f7492b6`: 1 test PASS |
| Every known wrapper enters authenticated service | `tsk_2678096372404756b5c8199fa4d8eac4`: 2 tests, 19 failing action subtests | `tsk_d166d8e42ca64dfe9aca9f8680413d63`: 2 tests PASS |
| Fail-closed dispatcher; no raw fallback | `tsk_1d7054af40e54154bb06052d92b11951`: 3 tests, 1 failing unknown-action subtest plus 2 missing-service errors | `tsk_f8fc21b0d1f54530b8004c6925863d52`: 3 tests PASS; helper removal refactor `tsk_0879987e407e46d39ee959e0d08e0daa`: direct unittest exit 0 |
| Composite builder save gate | `tsk_accf581f03f946b5997cc0ab7ab544a3`: 12 tests, 1 failure (save blocked policy was bypassed) | `tsk_4580ed5211eb44988925c0ed2dc38281`: 12 tests PASS |
| Composite effect safety gates | `tsk_711f4b49617147008f02097fbd4edd38`: 13 tests, 6 failing destructive/export/restore-save subtests | `tsk_1df7b81555c44dabb692c4d81602171e`: 13 tests PASS |
| Failed readback transport preserves possible completed effect | `tsk_1ed89a47af544ae5bf89ae49701b2536`: 18 tests, 1 failure (missing POST_ACTION_VERIFICATION_FAILED) | `tsk_194c505c00ef4e88ac8c013864579009`: 18 tests PASS, direct unittest exit 0 |

RED diagnostic commands used `-c` runners around `unittest.defaultTestLoader.discover('tests/arcmap', pattern='test_stage3_safety.py')`, `unittest.TextTestRunner` and explicit JSON `test_success`, `tests_run`, failures/errors/skips. Diagnostic process exit 0 was deliberately only a capture wrapper, **not** a test PASS. The final direct `-m unittest` invocation establishes the real successful test exit. An initial fixture setup run `tsk_f79e85dca3164bbd8353357ed66cab54` produced a BRIDGE_OFFLINE error against the isolated root before the legacy transport alias was isolated; it is not counted as the behavior RED.

Review receipt `tsk_6522aafcb3c441a0adedd83ebfb90ccc` shows only dispatch/helper removal and the essential composite/readback service changes; public wrappers are unchanged. Native `git diff --check -- agents/arcmap/engine/stage3/mcp_tools.py agents/arcmap/engine/mcp_server/services.py` receipt `tsk_8c7e6653a3f64dd0bc5ade90a549983b` exited 0. Git emitted existing Windows LF→CRLF conversion warnings, not whitespace errors. Final raw hashes below describe the current raw LF bytes, not a future Git-normalized checkout.

## Owned source/test raw SHA-256

| Exact repository-relative path | SHA-256 | Native hash receipt |
| --- | --- | --- |
| agents/arcmap/engine/stage3/mcp_tools.py | 9f8c384458dd686a3654e5329990540a423be0232f0c8600eea46b88b5a123d9 | tsk_f0454fcd75f04066935bed7a5c171927 |
| agents/arcmap/engine/mcp_server/services.py | 9525e5a62e8aaa2b1cab251a4aa60e6b790dfcdfcf7e1acf95bdd0b22e0298c0 | tsk_1af47040c8e443e991d0c2387eaed695 |
| tests/arcmap/test_stage3_safety.py | 608557ecf724c74d9f3219fa27de0335c4cef293b069942f779b6b39bd2a96dc | tsk_14ba2055d36a47388a81a3ed2344c1b5 |

Existing-file changes used native raw-byte `files_hash` and `expected_sha256` CAS; every write/patch target was read back. This document's final hash/readback receipt is returned with the handoff, avoiding a self-referential hash.

## Remaining gates / issues

- **NOT_RUN live**: Stage3 mutation, real UI document switch/queue expiry, actual ArcObjects layout creation, dataset output, checkpoint restore, save/export artifact readback, and public OAuth Router→Stage3 dispatch after delivery. No live ArcMap tool was invoked for this feature.
- **NOT_RUN deployment**: installed payload replacement, restart and live discovery. Parent owns integration, review and commit/push.
- **Public read-only convenience remains conservative**: current `request_context.READ_TOOLS` does not include `arcmap_stage3_health`; although the service health kind is correctly read-only, MCP ingress may still require write access. No tool policy or ingress authorization was changed within this exclusive file scope. Folder ingestion also remains conservatively write-gated when add_to_map=false.
- The coordinator's existing `test_bridge_regression.py` baseline FAIL (26 tests attempted; obsolete fixture authentication/IPC interfaces and absent ignored snapshot) remains real and separate. That file was not edited; no guard was weakened to hide it. Combined-suite validation is coordinator-owned after fixture maintenance and sibling changes.
- Status receipt `tsk_17ec72e1ba7b4ffba3a697f012b075d8` included sibling/coordinator changes to layer identity, mode docs and project instructions. They were preserved and are not part of this feature's file ownership.

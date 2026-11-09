# ArcMap P0 unique layer targeting — 6 November 2026

## Status and scope

Implemented in the Windows source checkout `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform` through authenticated native Files MCP, profile `agent-dev`, repository-relative cwd `.`. This is source implementation and isolated Windows fixture acceptance, not installed/live ArcMap acceptance. No commit, push, deployment, restart, policy/grant change, mode selector or checkpoint implementation was performed by this workstream.

Owned files:
- `agents/arcmap/engine/arcmap_bridge/core/current_map.py`
- `agents/arcmap/engine/arcmap_bridge/features/layers.py`
- `tests/arcmap/test_layer_identity.py` (new)
- this document (new)

`WORK.md`, `ZAGENT.md`, the baseline regression harness and the other workstream's Stage 3/server files were not edited manually. Files MCP automatically generated generic root `ZAGENT.md` on the first write; its guidance was subsequently read, not modified.

## Targeting contract

`resolve_unique_layer(mxd, layer_name, data_frame="")` returns exactly one actual `(data_frame_object, layer_object)` pair, or raises `RuntimeError` with a deterministic message prefix:

| Condition | Failure |
|---|---|
| Empty/missing layer name | `LAYER_NAME_REQUIRED` |
| Explicit frame name matches multiple frame objects | `DATA_FRAME_AMBIGUOUS`, including frame count |
| No exact layer-name match within the requested scope | `LAYER_NOT_FOUND` |
| Multiple matching layer objects | `LAYER_AMBIGUOUS`, including match count |

Matching remains exact and case-sensitive. Empty frame scope means all data frames, not just the active frame. An absent explicitly named frame cannot fall back to another frame. A duplicated explicit frame name is rejected even when only one of those frames contains the named layer. Group hierarchy/`longName` is not a new selector: duplicate display names in different groups remain ambiguous. Error messages depend on names/counts, not enumeration order. No stable persistent layer identifier is introduced.

Both `set_layer_visibility` and `set_definition_query` retain the existing live-write safety gate and resolve uniquely before assigning a property or refreshing the view/TOC. Ambiguity/not-found failures cannot mutate an earlier match. Unique successful calls keep the existing singleton `matches` list and `saved: false` response; they do not save the MXD. `find_layer` is unchanged and still returns every matching pair in a list for untouched/batch callers. `get_dataframe` and other actions were not globally converted.

Definition-query support refusal returns `ok: false` plus `DEFINITION_QUERY_UNSUPPORTED`; ArcPy capability-check or property-set exceptions return `ok: false` plus `DEFINITION_QUERY_FAILED`. No empty success is substituted. Empty query text remains a supported way to clear the query. Raw underlying exception details are not exposed by that failure result. A setter may change state before raising: a failed response is **not** proof of rollback or proof that nothing changed. Refresh/other runtime failures are not transactionally repaired by this patch.

The bridge changes retain Python 2.7 syntax and use Unicode error formatting. The unittest harness uses Python 3.11 stdlib; the bridge does not import that harness or require pytest.

## Isolated Windows verification

Exact final command (native Files MCP, `profile_id=agent-dev`, `cwd=.`, bounded 60 seconds):

```text
"D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\runtime\python\python.exe" -m unittest discover -s tests/arcmap -p test_layer_identity.py -v
```

Final receipt `tsk_56382058f9d1458ebccfb95e6c9645c1`: task succeeded, domain `ok: true`, exit 0, **18 tests PASS, 0 failures/errors/skips**, stdout/stderr not truncated.

Vertical TDD ledger (each production change followed its observed failing slice; existing-behavior compatibility checks were added alongside later slices):

| Slice | RED receipt / result | GREEN receipt / result |
|---|---|---|
| Visibility duplicate layer names | `tsk_25358b3a100c4ccf95c6422432afb103`, 1 test, intended assertion failure, exit 1 | `tsk_2f059d0734eb40f5a4d3b73356bc8d72`, 1 PASS, exit 0 |
| Duplicate-named explicit frames | `tsk_b8702f1307a1473d8cfa3a345d7c7bf3`, 6 tests / 1 failure, exit 1 | `tsk_085ec0b087a449ebb9904fbd60f79a8b`, 6 PASS, exit 0 |
| Definition-query unique targeting | `tsk_c274c5842ea748c890937e59188f0d10`, 8 tests / 3 failing topology subtests, exit 1 | `tsk_3517a1f59cae4fb5bf7b0346e1ec770e`, 8 PASS, exit 0 |
| Unsupported definition query | `tsk_3bff34b55f0e4598b67fe0642b6ba05d`, 9 tests / 1 failure, exit 1 | `tsk_96bccc46eece47eba94f46434e5fc7c8`, 9 PASS, exit 0 |
| ArcPy definition-query exceptions | `tsk_088259ae2a5c4fdea2e4fdef18bbccd9`, 10 tests / 2 failing stage subtests, exit 1 | `tsk_7d17e48d6ecb4d38ac4c6b00173b8bba`, 10 PASS, exit 0 |
| Empty target cannot select unnamed layer | `tsk_973cb59426064c259105f1b0c376a4b3`, 18 tests / 1 failure, exit 1 | `tsk_573425981f6247c0a7b2df5c2b94c21a`, 18 PASS, exit 0 |

RED wrappers preserve failure exit codes. For slices 2–6 the complete logs are under ignored `_validation/layer_identity_redN.log`; intermediate GREEN logs use `layer_identity_greenN.log`. Error envelopes can truncate failing command output; the sixth RED log was explicitly read back in receipt `tsk_be7e2d97a838435e84ea5bd93a3753dc` to confirm the intended `True is not false` assertion. These are repeated cumulative suite counts, not independent totals.

Tests execute actual Windows bridge resolver, handlers, registry, safety and config source. Only the unavailable ArcPy module/objects are behavior substitutes. Real config source executes with a fixture-local virtual `__file__` and environment paths so no installed runtime locator/private configuration is read. Every test restores prior `core.*`, `features.*`, `arcpy` module state, environment and bytecode setting, and removes its unique directory beneath ignored `_validation`.

Post-refactor receipt `tsk_6975c086c4d64e7eb1aaa66afeea8673`: source-byte readback/hashes, Python 3.11 compile and two in-process repetitions each **18/18 PASS**, plus explicit sentinel-module/environment/bytecode restoration assertions; exit 0. This is still 18 unique tests, not 36. It covers scoped success, cross-frame ambiguity, same-frame/group duplicates, duplicated frame names, missing target/scope, query clearing, errors, safe-mode ordering, registry wiring, Unicode names and the preserved list resolver contract.

An optional legacy-grammar probe failed before test execution (`tsk_6541f181f0674ab19dc8d4288face5e6`): the bundled Python 3.11 stdlib lacks `lib2to3/Grammar3.11.9.final.0.pickle`. Nothing was installed or switched to another runtime. No Python 2.7 execution acceptance is claimed by that failed probe or the successful Python 3.11 compile.

Final source raw SHA-256 (readback receipt above):
- `current_map.py`: `0604d2879ce1444638ccb16efc7dd74f71578c44c86bfcdad91a099026fe7cc4`
- `layers.py`: `902dfc4460e23d8e0c98985f3c8eebbd8847cf4a42bdc928299964820e9abce5`
- `test_layer_identity.py`: `0bf8267495aeec170e2275f1f7f48967af40df062f1144512964dbaca3aa7005`

Existing writes used the prior raw-byte SHA-256 in native `expected_sha256` CAS, followed by actual target readback. New test/doc absence was checked before creation.

## Bounded checkpoint manifest proposal — NOT IMPLEMENTED

A future checkpoint must distinguish three separate protection scopes; one cannot truthfully stand in for another:

1. **MXD artifact snapshot:** an explicitly authorized `saveACopy` to a new bounded checkpoint path, recording original project identity, saved/unsaved state knowledge, copy byte length/hash and verified creation. It protects document content captured at that moment, not external datasets. The original saved MXD hash alone does not identify unsaved CURRENT state. Do not silently overwrite/reopen the owner's project.
2. **Property snapshot:** record only explicitly supported target properties (initially visibility/definition query), their before-values/capability status, the selector used, diagnostics such as frame/layer position and `longName`, and exact operation/state evidence. Diagnostic ordinals/paths are not stable IDs. A future restore must re-resolve uniquely, bind to the same project/session or independently validated revision, reject stale/ambiguous targets, and report each verified/failed/unknown result. No blind first-match restore.
3. **External data:** MXDs and property snapshots do not back up shapefiles, geodatabases, rasters, remote services or edits made by geoprocessing. A manifest must mark external data `excluded` by default, list affected-resource categories without secrets, and require a separately authorized/verified dataset backup or transactional workflow before promising recovery for data-changing operations.

Suggested bounded manifest fields: `schema_version`, opaque `checkpoint_id`, originating operation ID, creation UTC, project/session/revision evidence, declared capture scope, captured artifact relative path/hash/size, selected targets with supported before-properties, excluded external-data scope, capture/verification errors, restore eligibility and retention bounds. Never embed credentials/private policy. Limit target count, artifact count/size, allowed destination and retention before implementing writes.

Track checkpoint lifecycle explicitly (`prepared`, `capture_verified`, `mutation_attempted`, `effect_verified`, `restore_attempted`, `restore_verified`, or `unknown`). A transport timeout/accepted receipt is not effect verification. Partial mutation or a failed restore must remain partial/unknown; do not label this mechanism universal rollback, undo, or an atomic transaction. Checkpoint capture, restore, retention and public tools are all deferred.

## Remaining gates / non-claims

- Actual Python 2.7 execution against these changed bridge files, including Unicode error paths, remains a separate target-runtime gate.
- Real ArcMap 10.6.1 tests on a separately authorized disposable project: duplicate targeting rejection, unique visibility/definition-query effects and independent property readback. No active ArcMap/project/data was changed here.
- Coordinator integration review and combined regression gates remain required. The coordinator reported baseline `test_bridge_regression` 26 tests with 8 errors + 1 failure in pre-existing fixture/API assumptions; this workstream did not edit/rerun that harness or claim overall green.
- Installed payload activation, live MCP dispatch, restart/deployment and full rollback/checkpoint acceptance are NOT RUN by this workstream. Headless/Attached contracts belong to the coordinator; this change introduces neither mode API nor save/export behavior.

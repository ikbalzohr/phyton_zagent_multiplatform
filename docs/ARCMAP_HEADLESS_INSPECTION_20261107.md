# ArcMap headless disk-MXD inspection — 2026-11-07

## Delivered level and scope

Implemented and exercised in the authoritative Windows checkout `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`, branch `zagent-v1`, inherited base HEAD `ade49ed`, through authenticated native Files MCP with profile `agent-dev` and cwd `.`. This closes the missing disk-MXD file-worker adapter/protocol path; it does not repeat the completed tool audit or replace the Attached inspector.

Only these product/test/document paths belong to this change:

- `agents/arcmap/engine/orchestrator/adapters/file_worker/arcgis_process.py`
- `agents/arcmap/engine/orchestrator/adapters/file_worker/worker27.py`
- `tests/arcmap/test_headless_inspection.py` (new)
- this document (new)

No optional Python 2 helper was needed. No commit, publication, deployment, activation, installed-payload/configuration change, UI/ROT/CURRENT access, save or export was performed. Sibling mode routing and public MCP registration are separate work; this report does not claim deployed public end-to-end acceptance.

## Reuse versus new gap

Inspected the existing worker `validate_template` and Stage2 helpers before expanding inspection. Stage2 `open_mxd(path)` already delegates directly to `_arcpy().mapping.MapDocument(path)` and is reused through the existing `_engine(engine_root)` loader. Stage2 initialization is a version-only module; its engine uses standard-library imports and lazy ArcPy, not MCP configuration. Validation happens before loading it for this new operation. Existing worker operations retain their original Stage2 path and behavior.

`validate_template` is an A4/profile-layout validator, not a document/frame/layer inventory. `get_df` selects one frame; `layout_manifest` reads layout elements without the required inventory/error bounds; `a4_check` checks page dimensions. These are not equivalent to the new contract, so no copies of those implementations were added. The new work is a narrow protocol dispatch, strict disk-path validation and a bounded truthful inventory around the reused disk opener and read-only ArcPy enumeration.

## Fixed sibling contract

`ArcGISProcessFileWorker(engine_root, python_exe=None, timeout_seconds=300)` now has keyword-only `inspect_mxd(*, mxd_path)`, forwarding exactly to `_call('inspect_mxd', {'mxd_path': mxd_path}, timeout=60)`.

The Python 2-compatible worker implements that operation before the other dispatch branches. It rejects empty/non-string/CURRENT/relative/drive-rootless Windows paths, wrong extensions and missing files. Extension comparison is case-insensitive. It passes the original accepted path unchanged to the Stage2 disk opener; it does not canonicalize a different target or fall back to an attached document.

Successful inventory contains `ok`, `document_path`, `document`, `frames`, `partial`, `warnings`; the client adds real `exit_code` and `duration_ms`.

- Document: exact `path`, readable `title`, `author`, `description`.
- Frame: readable `name`, finite numeric `scale`/`rotation`, `spatial_reference` (`name`, numeric `factory_code`), extent (`xmin`, `ymin`, `xmax`, `ymax`), and `layers`.
- Layer: readable `name`, `long_name`, actual boolean `visible`, `is_group`, `is_broken`, and supported/readable `data_source`.
- Bounds: 32 frames, 500 layers total, 2048 characters per metadata string, 128 warnings. Truncation/uninspected remainder is explicitly warned. ArcPy returns eager lists; output/property traversal is bounded, but this is not a claim that ArcPy internally streams enumeration.
- Unsupported/throwing/non-finite properties are omitted, not fabricated; warnings force `partial=true`. A legitimate empty string returned by ArcPy remains an empty string.
- Failure to open the mandatory document or enumerate its frames remains a genuine `FILE_WORKER_FAILED`/nonzero worker failure, not an empty success. Invalid input returns `INVALID_MXD_PATH` or `MXD_NOT_FOUND`.
- `finally` releases document, frame, layer, spatial-reference/extent and enumeration-list references. The subprocess also exits after each request.
- Existing nonzero-exit, missing-result and timeout semantics remain. A real RED exposed valid non-object JSON crashing `_call`; its minimal fix treats non-dict payloads as `FILE_WORKER_NO_RESULT`.

This is an internal trusted backend, not a standalone public service or an authentication bypass. The MCP/service caller must enforce authenticated principal/resource/profile, expiry and mode policy before invoking it. No permissions, allowlists or arbitrary Python execution hooks were added.

## Executed TDD receipts

All REDs below exited 1 before their respective product change. The first direct unittest stderr envelope was truncated; its missing-method failure was then captured with a complete ledger and concise stdout before production code was written.

| Slice | RED terminal task / observation | GREEN terminal task / result |
|---|---|---|
| Real client/protocol tracer | `tsk_759d2b359260445ab1650754b8e0ff36`: 1 run, 1 failure, `inspect_mxd client operation missing` | `tsk_a7c691c631e84f8f8924270d104b5765`: 1/1 |
| Reject invalid disk targets before ArcPy | `tsk_10ecaffc88b749e3bf5a9f9545a06489`: 2 run, 10 failing subtests, wrong generic failure code | `tsk_9dad790c6a14414295fc95f5081f5cc7`: 2/2 |
| Truthful partial inventory | `tsk_7a5b8bb3837943c79ba61a3ed92790f1`: 3 run, 1 failure, missing partial flag | `tsk_5790abef2fbe4ff393b019a6ba9ac837`: 3/3 |
| Bounds/truncation | `tsk_8dd32a0f69f64f3c8960ca4b49e1a5e5`: 4 run, 1 failure, 40 frames != 32 | `tsk_ef5b74476bd343a6b9ff4dfa3da0d29e`: 4/4 |
| Malformed protocol object | `tsk_de7d74f585944403956ae4d6ace691e7`: 5 run, 1 error, list has no `setdefault` | `tsk_c994e7d90775441faabcfebf1742c7f5`: 5/5 |
| Windows rooted-but-drive-relative target | `tsk_7f5287fc49f24289ab2de1177f8cdc88`: 6 run, 1 failure, `MXD_NOT_FOUND` != `INVALID_MXD_PATH` | final focused run: 12/12 |

The initial happy-path fixture hit missing ArcPy because the bundled embedded Python excludes the script directory from sys.path. A test-only runpy wrapper explicitly inserts its disposable ArcPy-fixture directory. The real client, request/response serialization, worker entry/dispatch and Stage2 opener are exercised; no production interpreter configuration was changed. The earlier Stage2-forbidden fixture was replaced by the real Stage2 loader when reuse was confirmed. `tsk_3e14ec3007334a4abc1630ee5fc2ca5e` verified the reuse refactor at 2/2.

Ledgers under ignored `_validation/headless-red*`, `_validation/headless-green*`, `_validation/headless-reuse` preserve complete unittest output. Additional regression cases cover thrown properties, mandatory document/frame failure, layer enumeration failure, malformed/missing JSON, nonzero exit, timeout and Unicode paths/metadata with input-byte preservation.

## Final Python 3 suite

Exact interpreter: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\runtime\python\python.exe`.

The executed native command used arguments `-B -X utf8 -c <stdlib unittest collector>`. The collector first required `from mcp.server import MCPServer`, then ran `unittest.TestLoader().discover('tests/arcmap', pattern=...)` for `test_headless_inspection.py` followed by `test_*.py`, saved complete logs, printed collected/run/failure/error/skip counts, and exited nonzero on any failure/error/skip. Native terminal receipt: `tsk_fa3b963082714e5d91a362d3c8d6aa2b`, process exit 0, Python 3.11.9, required SDK export present.

- Focused: collected 12, run 12, failures 0, errors 0, skipped 0.
- Combined: collected 89, run 89, failures 0, errors 0, skipped 0.
- These overlap; do not report 101 unique tests.
- Combined module counts, parsed from the actual log: bridge regression 26, layer identity 18, Stage3 safety 18, Stage3 fixture isolation 3 (the original 65), headless inspection 12, sibling execution modes 12.
- Complete logs/counts: `_validation/headless-final-unit/focused.txt`, `combined.txt`, `counts.json`.
- The existing Stage3 isolation suite intentionally emits nested setup-failure diagnostics. The outer combined suite passed; those expected nested executions are not additional unique tests.

Static acceptance/hash receipt `tsk_0a040eeed1cc4d24b8dc1177d5cfc37c` exited 0: the new worker function has exactly one explicit Stage2 `open_mxd(path)` call and no save/export/UI calls; the client operation and timeout are exact. Native `git diff --check` for both product files exited 0 (`tsk_1391e68d0313469c97a9afc02cd8b7ec`), with only LF-to-CRLF future-checkout warnings.

## Actual licensed Python 2.7 inspection

One current read-only runtime/existence/hash probe (`tsk_d89df5247a12487a9d911a3de67029b2`) used exact `C:\Python27\ArcGIS10.6\python.exe`: Python 2.7.14, ArcGIS 10.6.1, ArcInfo license, approved disposable input exists.

Only this existing disposable copy was inspected:

`D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform\_validation\headless-probe-d49a9e12de1e41189deddd3eb974f6f7\headless.mxd`

Actual test code loaded the real Python 3 client from its source path, asserted that input exists and matches the expected raw SHA-256, constructed `ArcGISProcessFileWorker(root/'agents/arcmap/engine', python_exe=r'C:\Python27\ArcGIS10.6\python.exe')`, invoked `inspect_mxd(mxd_path=str(p))` exactly once, then hashed the same file again and required `ok=true`, worker exit 0 and equal hashes. The final run used native arguments `-B -X utf8 -c <that assertion/ledger collector>`, native timeout 90 seconds and the client's 60-second worker bound.

First actual protocol receipt: `tsk_f4f06540c4a94c5685cece3963efab1c`. Final-code actual protocol receipt: `tsk_93795b73deb14d419c3f802e5cb531b9`, process exit 0, worker exit 0, duration 8752.451 ms. Complete final response/readback evidence: `_validation/headless-actual-final/result.json`.

Observed: one frame named `Layers`, zero layers, finite extent xmin=-290/ymin=0/xmax=1290/ymax=1000, rotation 0, actual blank document title/author/description, actual spatial-reference name empty and factory code 0. The frame scale was unavailable and was omitted; result correctly has `partial=true`, warning `frames[0].scale: unavailable`. No substitute scale or fake production-data inventory was returned.

Raw input SHA-256 before AND after both actual inspections:

`748263fdc71d482724dbfb74f9989f77702dec522278b3ca77e247ced4e1eaa0`

No owner working MXD, production datasets or additional seed content was opened. This actual proof validates Python 2 syntax/import compatibility, the real process protocol and licensed read-only disk inspection, not public deployed routing.

## Raw-byte source manifest

Raw CAS hashes were obtained natively before existing-file edits; exact targets were read back. Final hashes are bound in the static receipt and final actual inspection evidence:

| Path | Before SHA-256 | Final SHA-256 |
|---|---|---|
| `agents/arcmap/engine/orchestrator/adapters/file_worker/arcgis_process.py` | `8b00a7b9ad0857822153babe1a04a6d9034eaf98fbe3e63bb226a3f00dab9434` | `148c89ec1ec27520c522b6cef6bf77b3d43b2dcad918eb09bdfb30526c0997a1` |
| `agents/arcmap/engine/orchestrator/adapters/file_worker/worker27.py` | `537971c6e536c4643821af141d17aaf59c51527d3cde97f3ac2aff2febe4f7c3` | `a05bb77a0ccc99cef0522509bd07d45a82778c6b0711cbdda9bea3a71a8e7274` |
| `tests/arcmap/test_headless_inspection.py` | new | `1be562b16b41ec3aa3e4f414620834657c7b1fa143d056737a243eb379c684ee` |

## Operational limitations

A serverwide native MCP cooldown occurred while recovering accepted test/readback tasks. All native calls were paused; existing task IDs were recovered after cooldown without replaying commands or bypassing transport. No unresolved runtime blocker remains for this backend. The full authorized caller/mode integration and any deployed-client acceptance remain the coordinator/sibling boundary, not an implied capability of this internal helper.

Quota checks used only `hermes -p ikbal usage --provider openai-codex --json` locally, with explicit cwd `/root`; no Windows source mirror was used. Latest pre-document check at 2026-11-07T02:41:00Z: Session used 70%, Weekly used 68% (remaining 30%/32%), above the strict-any-window-below-10% stop threshold. No model/fallback/auth/global configuration was changed.

# ArcMap execution modes — Headless and Attached

Date: 6 November 2026. Status: DESIGN CONTRACT + BOUNDED WINDOWS PROOF. This document does not claim that a unified public execution-mode selector is implemented or deployed.

## Owner request
- Headless: process maps without opening the ArcMap application window.
- Attached: control the ArcMap already open on the owner's laptop, with visible changes.

Both lanes belong to the existing Zagent Multi Platform Core/Router/ArcMap architecture, not another GIS engine or a replacement installation. Existing native OAuth, principal/resource/profile checks and operation safety remain in force.

## Existing source foundations
- `agents/arcmap/engine/orchestrator/adapters/file_worker/arcgis_process.py` launches the isolated ArcGIS Python worker and bounds its lifetime. It has probe, data discovery, template validation, prepare_template/prepare_blank and render_staging operations.
- `agents/arcmap/engine/orchestrator/adapters/file_worker/worker27.py` opens explicit MXD paths through the Stage2 engine, copies seeds to a working MXD and exports from disk. It is Python2.7-compatible.
- `agents/arcmap/engine/mcp_server/tools/stage2.py` already routes discovery/preview/template validation to that file worker. Other Stage2 tools still call the guarded live service; do not describe every Stage2 tool as headless today.
- `agents/arcmap/engine/mcp_server/services.py`, `arcmap_bridge/core/current_map.py` and `arcmap_bridge/live_bridge.py` underpin the current attached lane, including CURRENT document state and a single UI-bound bridge owner.
- Stage3 contains ArcObjects/UI-bound operations; the existence of a disk worker does not make those operations portable to headless.

## Routing contract to implement
1. New dual-mode operations must explicitly receive `headless` or `attached`; no silent fallback and no mutable global mode shared across callers. Existing live-only public tools retain documented attached semantics until individually adapted.
2. Reject unknown modes before acquiring resources or mutating files. Advertise per-operation supported modes and limitations rather than promising identical capability in both lanes.
3. Return requested mode, actual execution lane and target identity with each result. A filesystem result cannot masquerade as CURRENT/UI readback.
4. Headless failure must never open, attach to or modify an interactive ArcMap document automatically. Attached failure must not silently save/process a different disk MXD.
5. Preserve canonical OAuth scopes, exact owner/device/resource binding, expiry while queued, path/overwrite validation, locks, timeouts, cancellation/outcome uncertainty and audit. Mode selection is not an authorization grant.

### Headless target
- Require an explicit input/template MXD or an explicitly supported new-map seed, an isolated workspace and approved output paths.
- Use the installed licensed ArcGIS Desktop ArcPy Python2.7 process, separate from the Python3 MCP agent. Headless here means no interactive ArcMap window, NOT Linux ArcPy or license-free processing.
- Do not use MapDocument('CURRENT'), ROT/AppRef attachment, UI refresh or a desktop window as a hidden dependency.
- Prefer source preservation and save-as output. Verify original bytes unchanged; require explicit overwrite for existing outputs and never publish partial results as success.
- Data referenced by an MXD remains external. A copied MXD is not a database transaction or complete dataset backup.
- Return explicit unsupported-capability results for UI/ArcObjects-only features unless an independently verified standalone implementation is provided.

### Attached target
- Require a healthy, authenticated live bridge and resolve a specific observed CURRENT document/bridge identity before mutation.
- Revalidate document identity and context expiry under the existing global ArcMap lock. Reject a switched/reopened document, ambiguous layer/frame target, wrong owner or read-only authority before mutation.
- Apply only requested changes to the open map; preserve unsaved work. Refresh and observe the result so the owner can see it. Saving the MXD remains a distinct guarded action.
- If the bridge is absent or ArcMap is busy, report that state instead of starting/replacing an application or attaching to a different document.

## Capability boundaries
- Disk MXD inspection, template/data preparation and exports have existing headless foundations, but require per-operation acceptance.
- CURRENT selection, direct layout-element creation and native application-window capture are attached-dependent unless a separate implementation is demonstrated.
- Headless blank-map construction can begin from a standard MXD seed; it is not proof of arbitrary ArcObjects element creation without UI.
- Symbology, labeling, fonts, extension licenses, data locks and database/service credentials can still limit rendering in either mode.
- Supporting both modes does not require or authorize changing the working QGIS integration.

## Actual Windows proof — 6 November 2026
- Source checkout: D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform, starting revision ade49ed81a0addec93c481bd3c62e2dc3e38c6be.
- Standalone interpreter C:\Python27\ArcGIS10.6\python.exe returned Python2.7.14 32-bit, ArcGIS10.6.1, product ArcInfo. Native receipt tsk_09f998ad5e20458992e8a68dc5cc7422 succeeded with exit0.
- A separate native command opened the installed standard ISO A4 Landscape.mxd by disk path, saved a new disposable MXD, reopened the copy, and exported PNG at120dpi without using CURRENT. Receipt tsk_f294646daf454f4da9a6d46045e4d7d6 succeeded with exit0, no stderr.
- Output directory: `_validation/headless-probe-d49a9e12de1e41189deddd3eb974f6f7/`; artifacts `headless.mxd`, `headless.png`.
- PNG was6489 bytes, signature checked, SHA256 b792ddf82fe733fa2ad2f084cf73f340a437ce42084da574f6eb2691d7c201da. Standard source template hash before/after was equal.
- This is a blank-template disk/save/export proof, not visual/cartographic acceptance on owner data, a unified MCP mode API, or proof of all UI-only capabilities in headless mode. Attached live mutations and mode-switch API acceptance are NOT_RUN.

## Delivery sequence and acceptance
1. Complete Stage3 shared safety and unique-target prerequisites; preserve existing ArcMap backend.
2. Add mode-aware capability/target contracts and deterministic routing with test-first verification: invalid mode, unsupported operation, stale target, wrong resource, expiry, no cross-lane fallback.
3. Route a bounded map inspection/export workflow to either file worker or live bridge under the same authorization contracts; test each independently.
4. Exercise a disposable data-bearing MXD in headless mode and a separately owner-approved disposable CURRENT document in attached mode. Confirm saved outputs reopen, correct page/extent/layers/style, and source preservation.
5. Update docs/WORK, review actual Windows results and commit/push scoped changes. Installation/restart/live client discovery are separate approved gates; do not label source/fixture success as active deployment.

## Test baseline caveat
The pre-existing Windows `tests/arcmap/test_bridge_regression.py` suite executed26 tests and FAILED before new implementation. Diagnostic collection found missing context fields in fixture calls/threads, removed IPC attributes/helper-signature assumptions, and an absent ignored runtime-tools snapshot. These are unresolved baseline findings, not permission to relax security or claim regression PASS. Stage3/layer workers use separate owned tests and the ArcMap Python3.11.9 runtime with MCPServer; the QGIS Python3.12 SDK is incompatible for this suite.

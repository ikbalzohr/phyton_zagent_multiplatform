# ArcMap inspection modes — source acceptance, 7 November 2026

## Scope
Authoritative Windows checkout: D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform; branch zagent-v1, base ade49ed81a0addec93c481bd3c62e2dc3e38c6be. Work used authenticated Files MCP profile agent-dev. This checkpoint covers read-only source routing and inspection, not all125 GIS capability mappings or runtime deployment.

## State-isolation failure and minimal repair
The original coordinator gate ran90 tests without test failures, but exited1 because process state was not restored (tsk_dc122baf0a6e4bb09738b940933bc43a). Per-suite diagnostics tsk_b60dd690f65a4784b5121544b0c19433 identified the baseline fixture retaining37 orchestrator source modules; environment, sys.path, bytecode and temporary roots were unchanged. Other suite deltas were clean.

New test tests/arcmap/test_baseline_fixture_isolation.py reproduced the exact cache failure before repair: one failure, no errors/skips, real exit1 (tsk_80bced120da64b079c8614a6cd98af5e). The saved RED was read and its final cache assertion confirmed in tsk_cb4244cb0cb74a59ad6fa730c8ce59c7. Full log: _validation/baseline-module-isolation-RED.log.

The repair adds only orchestrator to test_bridge_regression.py's owned module prefixes, using native CAS tsk_16b36200877b4c24a98b32153f4cdf08. Exact raw-byte comparison against _validation/baseline-before-module-fix.py proves all26 original test bodies/assertions unchanged. No production source or guard changed in this resumed repair.

## Actual final verification
Coordinator task tsk_75555382eeb6412198d2aecc2a3a38a1 finished with real exit0:
- Focused regression: 1 collected/run, zero failures/errors/skips; discovery and state clean.
- Seven suites forward: 91 collected/run, zero failures/errors/skips; discovery and state clean.
- Same-process reverse: 91 collected/run, zero failures/errors/skips; discovery and state clean.
- Same-process repeat: 91 collected/run, zero failures/errors/skips; discovery and state clean.
- All19 current source/test/doc manifest entries matched; only the exact baseline fixture delta and its new regression differ from the earlier verified manifest.

Counts are outer test cases per phase, not a sum of unique cases across repeated/nested executions. The new guard also runs the existing26 baseline tests; these are overlapping executions, not26 additional distinct tests.

Evidence: _validation/parent-dual-mode-verified.json and _validation/mode-verified-{focused-green,forward,reverse,repeat}.log. Earlier failure evidence remains preserved.

## Real source SDK to licensed backend
Task tsk_aa34c6a682cd4633a3639cd2ddf7a28c exited0 after invoking the registered source arcmap_inspect_map tool with explicit headless mode through the actual MCP SDK, AgentServices and unmodified ArcGISProcessFileWorker/worker27/ArcPy chain. In-process verified synthetic issuer metadata and disposable internal authentication exercised the source ingress; this is NOT public OAuth/Router or installed-catalog acceptance. All Attached transport boundaries remained forbidden; no live CURRENT map was contacted.

A disposable blank MXD returned one frame, zero layers and truthful partial=true with frames[0].scale unavailable. Exact requested target and headless lane were retained. Input raw SHA256 before/after both748263fdc71d482724dbfb74f9989f77702dec522278b3ca77e247ced4e1eaa0. Complete response and bounds: _validation/source-sdk-real-headless.json. Do not represent a blank-map result as real owner-data/cartographic acceptance.

## Review and remaining gates
Independent native-Windows source review deleg_74e350c4 PASSED with no blocking security or logic findings, covering all11 frozen mode/backend source, test and documentation artifacts. Native hash receipts: tsk_d21b0ca20bb44cd89ccd0ec726f5698f and tsk_16345f2027694c0dbbcfb826146abc40. Its only low-priority documentation clarification is that inspect_mxd supplies an explicit60-second operation timeout; the service's300-second constructor default does not override that bound.

Narrow fixture-delta review deleg_e94e1bd3 also PASSED with no concerns or suggestions. Native reads tsk_157d4c1348c241d2a81fc135457b9d15 and tsk_d82a596c8f77468fab9fb9747bbc0018 verified the two final hashes, exact one-line raw-byte replacement and unchanged ASTs for all26 original test functions. Both reviews were static; reviewers executed no tests and made no writes. The coordinator separately verified all19 tested artifact hashes still matched in tsk_03db73902fe949de8a5bd9c2f3338c07, in addition to the real execution gates above. The older interrupted deleg_7e89b85e remains excluded as approval evidence.

The bounded read-only inspection MVP is therefore source/fixture reviewed and verified. This closes neither the entire125-tool roadmap nor the live/deployment gates below.

Live Attached/CURRENT acceptance, deployed payload, public OAuth routing and public catalog activation remain NOT_RUN. No commit/push, deployment, restart, grant/model changes or live owner-map mutation occurred. Export/mutation dual-mode support remains explicitly unsupported by this MVP.

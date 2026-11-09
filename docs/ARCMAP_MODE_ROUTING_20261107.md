# Explicit ArcMap Headless/Attached inspection routing

Date: 7 November 2026. Status: SOURCE IMPLEMENTED / WINDOWS FIXTURES PASS; NOT DEPLOYED.

## Scope: routing, not another inspection audit

The completed 125-tool audit and existing Attached inspector are not unfinished work. This change adds explicit per-call routing over existing capabilities. Attached reuses `AgentServices.call('inspect_current_map', 'read', ...)` unchanged; it does not rebuild the bridge inspector. Headless calls the real `ArcGISProcessFileWorker.inspect_mxd(*, mxd_path)` contract implemented in the separately owned file-worker slice. No production stub, export implementation, new installation, global mode, or cross-lane fallback is introduced.

## Two actual source MCP tools

- `arcmap_execution_capabilities()`: authenticated, read-only source contract. Reports inspection modes, runtime readiness NOT_PROBED, deployment_verified=false, and exports/mutations/UI control unsupported or not yet dual-mode. Existing legacy tools keep their original defaults.
- `arcmap_inspect_map(mode: str, mxd_path: str='', expected_context: dict=None)`: exact lowercase `headless` or `attached` only. Unknown modes and extra action/argument fields are rejected before backend dispatch. Both tools are registered in the actual server and classified in READ_TOOLS, with read-only/nondestructive SDK annotations.

Attached rejects every nonempty disk target. It forwards `_expected_context` only when supplied, makes one existing inspector service call, and reports the observed CURRENT context rather than claiming a disk document was inspected. Bridge errors remain failures.

Headless rejects empty/CURRENT/relative/non-MXD/missing targets and any attached expected_context, including an empty dict. It uses an absolute existing disk MXD and one public file-worker inspect_mxd call; no ping, CURRENT/UI dependency, save, export, or retry. Engine root follows the existing Stage2 source-relative factory pattern; worker timeout is 300 seconds. Backend data/errors are retained under `data`; top-level `ok` mirrors the backend, never fabricates success. Results include `requested_mode`, actual `execution_lane`, and lane-specific `target` identity. Predispatch invalid requests report execution_lane=null.

## Authentication and path authority

The real CorrelatedMCPServer request_meta/verify path remains mandatory: authenticated internal channel, principal/workspace/device, bounded expiry, effective access, and exactly one ArcMap/GIS resource. Files profile agent-dev authorizes this source-development work; it is not an ArcMap grant and is never converted into headless authority.

The dedicated read-only AgentServices seam requires the verified ingress marker, rechecks owner/device/resource/read authority and expiry under the existing shared ArcMap lock, then validates the path and calls the worker. It accepts neither arbitrary callbacks nor action names. The previous service call/live-write health pin, upstream read-only gate, SafetyPolicy composites, TypeError no-replay behavior, and post-action readback handling are unchanged.

The inspected ArcMap verifier/grant consumer exposes resource kind/id, not a per-MXD root-containment contract; existing config/Stage2 factory define no ArcMap input-root allowlist. This change uses that existing authenticated ArcMap/GIS resource authority and does not invent/expand grants or read private policy. Absolute/existing/suffix checks are input validation, NOT a filesystem sandbox. The worker executes with owner-account filesystem rights. A deployment requiring narrower file roots needs an explicit authoritative root-bound grant/consumer contract first; no made-up root list or implicit Files-scope bypass is installed here.

## Vertical RED/GREEN evidence

All commands ran through native Windows Files MCP, profile agent-dev, cwd '.', on the approved ArcMap Python3.11.9 interpreter. Accepted IDs below were retrieved to terminal domain results. RED exits are real exit1, GREEN exits real exit0; full logs remain in ignored `_validation`.

| Slice | RED receipt | GREEN receipt |
|---|---|---|
| Actual Attached tool registration/read dispatch | tsk_4bf2926ecb3547918bffac24f1038563 | tsk_074ded7103a84ebd9e99dce046c5ae93 |
| Invalid mode/target-mix rejection | tsk_091b02ef99844223abbe9c3399dd5476 | tsk_9e2bcca01a874171983d8b720cca06bb |
| One Headless worker dispatch, no UI | tsk_9a16372284ba413e926a525d3a464502 | tsk_a7b532bf248846d287ddc7c045f76d4e |
| Verified service authority/resource/device/owner | tsk_84df61e4000a453b87b09044408ac815 | tsk_eb4e99f55c494f7e991cf5c3b6e4e700 |
| Authenticated source-only capabilities | tsk_2764d719d4e049cb88247a41cf93f6dc | tsk_a5ce6caa0ec24e089ab3c760988e8cd5 |
| Actual SDK read-only annotations | tsk_663ba46ae5f549b08a77d5acadb86374 | tsk_4ac77a7812cb4dc1ab1476c76e1c3c0d |
| SDK rejection of unknown action arguments | tsk_2c519bb4c0564eea8a18f72b82d9e415 | tsk_e469662b4b0549848000f78cfed35887 |

Annotation iteration preserved a failed GREEN attempt, tsk_8c54174ab7094c2db77c273bdd4dbcb8: the installed SDK exposes snake_case model fields. The corrected test and explicit annotations use the inspected SDK contract. A real SDK probe also demonstrated silently ignored extra arguments; only these two new tools now rebuild their own input models with extra='forbid' and refresh their advertised schema. Legacy schemas and ingress are untouched. This narrow registration depends on the verified installed SDK Tool.fn_metadata.arg_model interface; incompatible SDKs must fail registration rather than silently disable validation.

## Final fixture/regression verification

Final receipt `tsk_e469662b4b0549848000f78cfed35887`: real exit0, empty stderr, no output truncation.

- Focused routing suite: 13/13 PASS.
- Existing four-suite regression: 65/65 PASS, no failures/errors/skips; all four existing test-file hashes and the three untouched product hashes match `_validation/parent-isolation-corrected.json`.
- Combined forward, reverse, repeat: 78 collected/run per phase; zero failures/errors/skips. Environment, sys.path, bytecode flag, owned module object identities and task temporary-directory membership restored; preinstalled module sentinels restored exactly.
- Focused suite repeated with bytecode initially False: 13/13 PASS with clean discovery/state.
- Ledger: `_validation/mode-routing-final.json`; logs `_validation/mode-green7.log`, `_validation/mode-final-{baseline65,forward,reverse,repeat,bytecode_false}.log`.
- Tests use real source registration, request_meta/verify/current, AgentServices and lock/expiry checks. Only unavailable IPC and file-worker boundaries are substituted. Coverage includes missing/wrong/expired/read authority, target mixing, one backend invocation, no fallback/replay, raw failure preservation, observed target metadata, module discovery, successful cleanup and injected late setup-failure cleanup.

An earlier broad composition gate (`tsk_b2b223c2f7e744339184f71644a30587`, exit1) had all behavior tests passing but exposed two harness/state assumptions: legacy baseline imports retain orchestrator modules, and the temporary-directory glob incorrectly included newly written log files. Its logs/ledger remain preserved. Corrected gates explicitly warm the observed legacy import cache, compare exact sentinel/module identities thereafter, and count directories only. No existing test or product guard was changed for this correction. Expected nested setup failures in the original isolation suite are asserted outer-test behavior, not outer errors. A server-wide cooldown was honored before resuming the same native transport.

## Not run / integration handoff

Live ArcMap/CURRENT operations, real ArcPy execution through these new public tools, owner-data acceptance, installed payload, Router/public OAuth catalog rediscovery and ChatGPT/Claude activation are NOT_RUN. The file-worker's own implementation/acceptance is documented separately in ARCMAP_HEADLESS_INSPECTION_20261107.md; the coordinator owns joint real-backend integration. This source/fixture result does not imply deployment or license/runtime readiness. No commit, push, publication, restart, private configuration/permission change, or live-map operation occurred.

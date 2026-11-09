# ArcMap public capabilities / Headless isolation — scoped source correction

Date: 2026-11-07. Authoritative checkout: D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform, branch zagent-v1, HEAD ade49ed. Files MCP: profile agent-dev, cwd ".".
Status: SOURCE PATCH VERIFIED / NOT DEPLOYED / PUBLIC ACCEPTANCE BLOCKED.

## Defect and RED evidence

The current AgentServices implementation originally used _ARCMAP_LOCK for Desktop bridge ping, authenticated static execution_capabilities, and Headless inspect_mxd. A stalled Desktop IPC request could therefore block both Desktop-independent operations, even though neither needs CURRENT/UI. This contention is a demonstrated source defect; it has NOT been proven to explain the original public orphaned task.

- Real SDK synthetic authenticated ingress and a simulated stalled Desktop ping: RED tsk_5fb06d28d9014d77b3e1272295075bf8, 14 cases, one intended failure ("Capabilities blocked on Desktop IPC lock"), exit 1. No actual Desktop bridge or user MXD contacted.
- Timeout routing contract: original Router fallback is service timeout (source default 25s); file-worker inspect_mxd uses an explicit subprocess timeout of 60s. The missing headless-only deadline metadata was reproduced in tsk_8e6688f9c6b546da8a37144d61a86265, exit 1. This source mismatch does not establish that it caused the historical HTTP/orphan failure.

## Minimal source corrections

1. agents/arcmap/engine/mcp_server/services.py: capabilities validates verified principal/workspace/device/resource/access/expiry without taking a Desktop lock. Headless work takes a new _HEADLESS_LOCK and repeats the same checks after acquiring it, preserving serialized ArcPy file-worker execution. Existing _ARCMAP_LOCK and the legacy Desktop/Attached call path are unchanged.
2. agents/arcmap/engine/mcp_server/tools/execution_modes.py: the registered arcmap_inspect_map tool publishes server-defined metadata `zagent.mode_worker_timeout_seconds: {headless: 60}`. Its public input parameters remain unchanged, and clients cannot override the bound.
3. agents/tunnel/engine/router/registry.py: the existing _tool_call_timeout_seconds helper reads this bounded mode-specific contract, reserves a 15-second transport margin for headless (75 seconds with the current constants/base), and leaves Attached/other modes on their original timeout mechanism. Existing timeout_seconds schema behavior for other tools is preserved.
4. tests/arcmap/test_execution_modes.py: real SDK concurrent ping/capabilities/Headless test; independent Headless serialization and expiry-under-lock regression; actual advertised tool metadata; narrow production Router timeout-helper test without importing Router HTTP dependencies. No credential/authority bypass or cross-lane fallback introduced.

Final raw SHA256:
- services.py: 4176eccfb8fd47074ad6dfa9731317f045b279c0fa936f40ec580f2bdb8a835b
- tools/execution_modes.py: 9a1460254b629b81c9a9ec5634d21ecd10f8b78da68192c89a27bd3c4a9365f3
- router/registry.py: 053c7e45abb9c035b344de7bdc4c17ce8fa2bb3f05390749c8644bdd391cdd47
- test_execution_modes.py: 72970c0671432aa3d16094efbd381086641f225480adf8e5e56db4ea5aa52554

## Verification

- Post-lock GREEN tsk_e503c55fc73d4d52a9a55cb77a4d7571: 14/14, exit 0.
- Final focused GREEN tsk_7ac5b4b97f7449e7b808bc9797659dad: 17/17, exit 0.
- Final seven-suite combined gate tsk_ed7e0a2e27a6406c80e5b79a66139c6b: 95/95 outer cases in each forward/reverse/repeat phase, no outer failures/errors/skips, process exit 0. Recorded state_clean=true for environment, sys.path, bytecode flag, owned module identities and temporary directory membership. Nested deliberate fixture-setup failure is expected/handled by its outer test; do not count it as an outer error.
- Git diff --check (tracked scoped files): tsk_1a82e741103c45daa71edaccec095534, exit 0; Windows line-ending warnings only, not whitespace errors.
- No actual licensed ArcPy execution re-run for this delta. Earlier installed-SDK-to-licensed-ArcPy proof remains prior evidence, not a new public acceptance.

## Strict remaining gates

- Original public arcmap_execution_capabilities task tsk_cf5119a1a6af4ac9b937bf9d4a38baf1 remains orphaned and officially marked manual_owner_reconciliation_required. Do NOT replay/delete/recover by alternate transport. zagent_reconciliation_status is diagnostic-only in the exposed connector.
- Existing installed payload was not modified by this source correction. Independent source review, managed scoped deployment with exact-byte backup and manifest preservation, and officially authorized task reconciliation are outstanding.
- Public OAuth/Router execution of capabilities and headless inspection after correction remains NOT_RUN. Never report end-to-end success from source tests or catalog discovery.
- ArcMap Desktop was not opened, restarted, or otherwise used; Attached/CURRENT, existing grants, credentials, OAuth, and owner maps were not changed. No Git commit or push.

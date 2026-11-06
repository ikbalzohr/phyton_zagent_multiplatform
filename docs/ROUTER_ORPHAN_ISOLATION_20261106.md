# Router orphan isolation — 6 November 2026

## Problem
A historical ArcMap ping task in Multi Platform entered orphaned state. Router assigned all agents the same installation-wide resource key and blocked every subsequent task sharing that key, even unrelated Files operations on the owner-approved development profile.

The problem was overbroad quarantine, not a Files grant failure. Restart does not erase the durable task. Do not delete the journal or disable all owner protections to work around this.

## Source change
- router/orphan_conflicts.py: classify interrupted tasks by trusted service/tool identity and resource family (Files including QGIS owner-command delegation, ArcMap, or Web). Unknown services and cross-agent workflows continue to fail closed. Historical uncertain writers block only overlapping effect families.
- A canonical read-only ArcMap ping is nonblocking when the tool name, service ID, empty argument object, saved execution context, installation ID, resource ID and device match. Both arcmap:inspect and arcmap:execute are accepted for this exact tool because the real task used the broader OAuth scope, even though ping only checks connectivity. This does not imply that arbitrary ArcMap execute tools are harmless.
- Router executor checks matching orphan records before backend dispatch. Existing OAuth checks, tool grants, Files profile scopes, owner CAS, generation validation, and task idempotency remain unchanged.
- Reconciliation status reports a recognized harmless observation as nonblocking_observation_no_action_required. It preserves the historical orphaned task and audit data.
- This change fixes durable quarantine, but retains the legacy installation-wide lock for in-flight task concurrency. Changing concurrent resource ownership requires a separate cross-agent data-interference audit.

## Windows regression evidence
- Complete Router suite: 189 passed, 3 skipped, 604 subtests passed.
- Test coverage: canonical ping and its real execute scope, cross-service isolation, same-service uncertain writer denial, unknown/mismatched metadata fail-closed, and Router executor pre-dispatch.
- A read-only query against the actual Multi Platform task journal found the historical orphaned ArcMap ping with scope arcmap:execute and matching saved installation/device identity. The revised source returned nonblocking_probe=True, blocks_service(zagent_files)=False, blocks_service(zagent_arcmap)=False. The task was not modified or replayed.

## Deployment
Source is ready; running Python Router processes cannot reload it automatically. Apply the corresponding verified installer package only during a coordinated Multi Platform stop/install/start window, with backup and verification. Do not force-kill live processes or modify Zagent Production. Remote client acceptance is separate.

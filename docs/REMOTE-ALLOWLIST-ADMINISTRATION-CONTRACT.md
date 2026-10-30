# Remote executable allowlist administration — implementation contract

Status: approved functional requirements; implementation in progress. This document is not runtime acceptance or an enrollment grant.

## Scope

Only list, add, replace an exact executable path, and remove an exact executable path for an existing explicitly authorized command profile. No profile creation, root migration, grant/OAuth/scope/tool change, policy enablement, command timeout/output change, arbitrary shell, or remote generic configuration write.

Develop and test Zagent source directly on Windows using Files MCP. Keep the earlier owner-local dotnet helper intact. VPS implements the approval/backup client components only; it is not the alternative Zagent source workspace.

## Four approval choices in the originating chat

1. Allow once: the displayed exact action and payload only.
2. Allow this session: exact rule, owner, chat/topic, session, device, installation, workspace and profile.
3. Always allow this rule: persisted exact rule with an inspectable identifier and explicit revocation.
4. Reject: no mutation.

No wildcard executable, implicit prefix rule, broad trust of a future payload, or LLM-provided approval boolean. Session/permanent rules permit the trusted broker to mint a new operation-specific receipt only while the exact authorized rule still applies. Changed payload requires a new approval. An ordinary chat reply is not a substitute for a verified approval callback.

Bind the real callback sender, chat and topic to the trusted owner. Forged, foreign-user, wrong-chat/topic, stale and replayed callbacks fail closed. Give a short expiry to pending approvals; reject future-dated receipts and bind policy revision, server challenge, operation id, payload digest and placement. The installed Hermes/Telegram integration must be verified before choosing the actual callback implementation; do not imitate approval text without enforcing it.

## Authority boundary

Ordinary command/file capabilities must not imply permission to edit their own execution allowlist. Require a dedicated authenticated owner-administration capability, explicit trusted broker-key enrollment and exact device/installation/workspace/profile placement. A shell interpreter cannot bootstrap or bypass this permission. Existing local-owner enrollment is the trust root; new remote authority is disabled until explicitly enrolled through a legitimate owner path.

Never enable the new capability or alter live private grants by editing application source or by executing a generic MCP command. Preserve local-owner recovery if the VPS is unavailable.

## Executable validation and risk

Use exact existing absolute local executable files, reject alias/symlink/reparse/UNC/device paths and invalid ancestors, and validate old and new paths and finite list bounds. Target must remain an approved enabled read-write profile. Do not expand allowed tools, roots, host-account acknowledgement or limits. Interpreter approvals carry Windows owner-account OS rights: this is not a filesystem sandbox.

## Backup on VPS only

No laptop backup or snapshot file. Transient local atomic-publication candidate is not a backup and must not be retained as one. Hold prior policy in bounded memory as needed for publication verification. A confidential preimage reaches the trusted VPS backup component without entering model context or chat. Encrypt with an authenticated encryption scheme and keep decryption keys separate from ciphertext; never put secrets or backups in Git.

Persist and verify the encrypted backup before authorizing publication. Bind its receipt to the exact preimage digest, policy revision, operation id and approved payload. Backup receipt is not approval. If backup is unavailable or cannot be verified, fail closed with no policy mutation. VPS retention is 30 days; stored approval records and audits must not contain the private policy body or tokens. Document key custody and restore behavior; never invent a trusted receipt or backup on failure.

## Live writer and recovery

Do not stop Core/Tunnel to perform a remote administration operation. One authoritative command-policy writer coordinates every new admin mutation. Validate current revision and target state inside its critical section; reject stale snapshots. Apply with atomic single-file publication and exact readback. Existing local offline helpers must not race the running service.

Use an owner-scoped stable idempotency key and exact payload; persist operation state and audit safely. If a connection fails after publication, query the same operation id and reconcile the actual policy digest. Do not blindly retry with a new key. Conflict, denial, expiry, unavailable backup and unknown commit outcome remain distinct outcomes. Removing/replacing an executable must respect active-command revalidation and existing ownership boundaries.

## Acceptance gates

- Real parser compatibility for v1/v2; no authority-field or sibling-policy changes.
- Once/session/exact-rule/deny semantics with expiry, revocation, wrong identity/topic, payload tampering and replay tests.
- Dedicated capability cannot be impersonated with caller arguments or ordinary verified execution context.
- Encrypted backup persists on VPS only; no token/plaintext leaks; backup failure prevents mutation.
- Concurrent CAS, duplicate requests and interrupted publication recover without double application.
- Windows end-to-end approval, backup, mutation, exact readback and one harmless execution through MCP.

Every gate must be labelled NOT_RUN until real execution proves it. Source presence, tool discovery, a mock callback or a queued receipt is not end-to-end acceptance.

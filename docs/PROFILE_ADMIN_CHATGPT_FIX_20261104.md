# ChatGPT profile administration MCP fix — 4 November 2026

## Symptom and confirmed root cause

The six public profile management tools appeared in the 506-tool
catalog but direct ChatGPT files_profile_admin_list and nested
zagent_task_submit targeting it returned JSON-RPC -32602,
"Invalid arguments or inaccessible resource".
Authenticated Dashboard owner CRUD was already functional.

The public Router handler rejected every extra field in MCP
tools/call.params for profile administration, including standard
client-supplied params._meta used by clients for progress metadata.
An ASGI test reproduced the exact -32602 result before the change.

## Minimal change

The Router now allows an opaque dict params._meta with direct or
nested profile-admin calls. It still rejects unknown extra params
and client attempts to supply zagent.* or profile authority fields.
Client metadata never becomes trusted authority or Files metadata:
the authenticated Router creates private profile_admin_context
and verifies owner grant, workspace/device/installation binding,
scope, revision, and idempotency as before.

Files engine, Keycloak, Core, OAuth grant and Production configs
were not modified for this MCP compatibility issue.

## Testing and live deployment

- ASGI regression: pre-patch -32602 FAIL, post-patch PASS, including
  direct/nested calls and rejection of forged private contexts.
- Router Python full suite: 174 tests, 3 SKIP, remaining PASS.
- Isolated Windows Router-to-Files profile regression: 14/14 PASS.
- Owner Dashboard managed stop and start of system.tunnel only,
  with Core and other agents left running.
- Installed Router source hash and manifest updated and verified:
  12001/12001 files PASS, FilesChanged=0, BackupRoot=null.
- ChatGPT direct files_profile_admin_list: durable task succeeded,
  authoritative 64-character catalog revision and three profiles
  appBridge, projectMapping, agent.
- ChatGPT nested zagent_task_submit targeting files_profile_admin_list
  also completed succeeded and returned the current three profiles.
- ChatGPT direct files_profile_admin_create, get, update, delete:
  all succeeded. Disposable read-only mcpProfileSmoke20261104 was
  committed, inspected, updated, deleted and the empty folder cleaned.
  appBridge remained default; no persistent test profile left.

## Outcome

FIXED in source and deployed to installed Multi Platform; direct
ChatGPT Create/Get/Update/Delete now PASS end to end. This replaces
earlier notes that direct chat profile management was unavailable.
No access tokens, credentials or private principal IDs recorded.
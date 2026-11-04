# Owner profile administration provisioning — 4 November 2026

## Intent and scope
The owner requested full provisioning of the existing Zagent Multi Platform
profile-management features. No Files engine rewrite or new MCP server.

## Config changes actually applied
- On the installed Multi Platform only, enabled a typed version-1
  profile_management capability on the existing single owner grant.
- Preserved the existing workspace, device, installation, default appBridge,
  Files root, profile approval, OAuth issuer/client and six granted scopes.
- Added exactly six explicit owner tool grant names and matching enabled
  tool policies, using files:read for list/get and files:write for mutations.
- Kept the owner wildcard for the independently authorized general tools.
- Config was written atomically from a private owner file and read back.
- No Production, Keycloak, ingress or credential changes were made.
- The Files service remains authoritative for profile revisions, membership,
  generations, access sync, idempotency and atomic profile writes.

## Live acceptance evidence
- Connected ChatGPT Multi Platform capabilities advertised 506 distinct tools
  instead of 499, including six files_profile_admin operations and the
  separately gated zagent_allowlist_access.
- Authenticated Dashboard workspaces API returned HTTP 200, a valid catalog
  revision and the appBridge default, without read-only inventory fallback.
- Through Dashboard's real owner session, CSRF token, same-origin check,
  If-Match revision and idempotency key, created disposable read-only profile
  zmpOwnerSmoke20261104. The backend returned committed and access_sync
  committed.
- A live ChatGPT files_list call targeting the new profile succeeded,
  confirming that Files membership reached the MCP Router correctly.
- Dashboard get/update/default/delete operations all committed. The final
  profile inventory contains only appBridge, still the active/default
  profile. The empty disposable folder was removed after profile deletion.
- Core profile binding/response contract tests PASS; Dashboard owner
  authentication tests PASS; ProfileDiagnostics tests PASS.
- Isolated Windows Router/Files fixture regression 14 of 14 PASS. The
  fixture was updated to represent current FastMCP CallToolResult responses
  and to provide an isolated Core data root. No installed engine changes.
- A mutation lacking the required Dashboard origin/CSRF context received
  HTTP 403. The authorized mutation succeeded; no security bypass.

## Caveat: direct ChatGPT action refresh
The current conversation's callable tool inventory was established before
the new six tools were provisioned. Although the live discovery catalog now
advertises them, they are not directly callable in this same session.
The owner can refresh/reconnect the existing ChatGPT MCP app and invoke
the six public files_profile_admin tools without a new MCP server.

A live generic zagent_task_submit wrapping files_profile_admin_list returned
Invalid arguments or inaccessible resource. An isolated source dispatch
simulation for the direct and generic contexts passed, but it is not live
acceptance of generic nested calls. The direct public profile admin tools
should be used after tool schema refresh; do not claim generic nested
submission is verified.

## Files changed / release
Only mutable owner config in the installed Multi Platform and the existing
test harness files tests/run_direct_profile_router_windows.py,
tests/test_direct_profile_router_windows.py and documentation were changed.
No installation binaries, Production config, or QGIS integration changed.
No restart, commit or push was requested or performed. Exclude artifacts
and runtime files from any later Git staging.
## 4 November 2026 — profile admin direct ChatGPT acceptance now PASS

The earlier direct ChatGPT/admin-tool verification blocker above
was resolved through a Router protocol fix accepting ordinary MCP
params._meta without trusting client-supplied authority. Owner
OAuth and the existing six grants were not changed.
Direct ChatGPT list/create/get/update/delete succeeded; temporary
test profile was cleaned up and appBridge remains default.
See docs/PROFILE_ADMIN_CHATGPT_FIX_20261104.md.
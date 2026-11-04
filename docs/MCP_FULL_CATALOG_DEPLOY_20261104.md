# Zagent Multi Platform MCP Full Catalog — Deployment Record (2026-11-04, WITA)

## Owner goal
Expose all **currently present and supported** MCP tools of the installed Zagent
Multi Platform via a new ChatGPT custom MCP plugin; the user independently removes
the prior plugin. Do not introduce a second MCP server, copy Zagent Production
grants, bypass executable allowlists or rewrite the existing agent engines.

## Installation results — VERIFIED OFFLINE

- Source root: `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`.
- Installed root: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform`.
- Source deployment: `agents/tunnel/engine/router/{server.py,access.py,profile_admin.py,full_catalog.py}`.
- The installed `payload-manifest.json` now tracks **7,015** files. Installed
  `Zagent.Setup.exe verify --source <install> --target <install>` returned
  `Success=true`, `FilesVerified=7015`, `FilesChanged=0`.
- Program files and private config were backed up **before modification** under
  `<install>\data\backups\mcp-full-catalog-20261104_141804`.
  The marker `<install>\data\backups\full-catalog-rollback-pointer.txt`
  identifies the complete backup directory. Intermediate copies moved into
  that directory's `intermediate` subtree, instead of being left alongside
  application source/config files.
- Source Router regression: **173 tests, 3 skipped, PASS**, including new
  `all_discovered` unit/ASGI integration tests. No general production release
  acceptance was claimed.

## Owner-only configuration — VERIFIED READBACK

- Existing `data/tunnel/config/tunnel.json` was **merged**, not replaced.
  `catalog_exposure.mode = all_discovered` and the existing owner grant uses
  `tools = ["*"]`. Existing issuer/resource URI/client identifiers, placement,
  grant expiry and files-resource membership were preserved.
- Router `resource_server.scopes_supported` and the existing owner grant now
  include exactly: `files:read`, `files:write`, `files:execute`,
  `web:control`, `arcmap:execute`, `arcmap:inspect`.
  Explicit `tool_policy.files_stat` remains enabled and takes precedence.
- Approved `appBridge` Files profile was switched from `read-only` to
  `read-write`, retaining its existing, exact installed workspace root.
- Created an explicit owner-account command policy using the Files native v2
  schema for 13 command tools and 6 installed executable paths (PowerShell,
  Git, Node, npm, npx, dotnet). No ambient wildcard executable path was added.
  Native `_policy_profiles` and installed profile loader checks PASS:
  correct root, approved `read-write`, all policy entries valid.
- Offline installed Router configuration loader found **3 enabled upstream
  services**: `zagent_files`, `zagent_web`, `zagent_arcmap`.
  Inferred policy validated for examples `files_stat`, `files_write`,
  `files_git`, `web_snapshot`, `arcmap_status`.
  QGIS upstream is **not registered in installed services** at this check.
- Management-only legacy Files update/cross-profile APIs remain intentionally
  private; owner `profile_management` capability still needs separate
  provisioning to expose the six owner administration APIs. The Files
  `files_process_start` endpoint is defined but its backend is marked
  unsupported; do not claim execution parity for it.

## Keycloak — PARTIALLY VERIFIED

- HTTPS OIDC discovery on existing issuer returned **HTTP 200** and the exact
  issuer, PKCE S256 and realm-advertised scopes:
  `files:read`, `files:write`, `files:execute`, `web:control`,
  `arcmap:execute`, `arcmap:inspect`.
- An unauthenticated sample Authorization Code/PKCE authorization request
  using the expected public client returned **HTTP 403** without a recognized
  OAuth error in the body. Do **not** interpret scope advertisement as proof
  that the ChatGPT client may request/receive those scopes.
- SSH noninteractive authentication to the previously recorded VPS IP was
  rejected, and strict hostname key validation also prevented the DNS-name
  connection. No Keycloak Admin API/realm/client changes were made. Full-scope
  access token claim issuance and client redirect acceptance: **NOT VERIFIED**.

## Live activation and ChatGPT catalog — BLOCKED / NOT RUN

- Before and after offline deployment, installed Multi Platform service
  processes/listeners were absent; `127.0.0.3:19110` was not listening.
- Attempt to start `Zagent.Launcher.exe` via the existing **Production** Files
  `files_process_start` was rejected by its executable allowlist.
  No bypass or change to Production allowlist/service/config was performed.
- Existing ChatGPT Multi Platform connector `zagent_capabilities` call failed
  internally while Router was offline. Live OAuth `initialize`, full
  `tools/list`, `tools/call`, receipt retrieval and cross-agent actions:
  **NOT VERIFIED**.
- The user must start the **Multi Platform Launcher** locally using Windows,
  independently create the new ChatGPT custom MCP plugin and complete OAuth.
  User's deletion of the previous plugin is not performed by this deployment.
  No Cloudflare/domain/ingress changes, Production changes, Git commit or push.

## Next acceptance checklist

1. Start `<install>\Zagent.Launcher.exe` **locally on Windows**.
   Verify Dashboard `https://localhost:19444` and Router
   `http://127.0.0.3:19110/mcp` are actually listening, and inspect
   upstream discovery counts and errors.
2. Verify the existing Keycloak public client can issue an access token with
   all six requested scopes and the MCP resource audience. Correct client
   allowed scopes/redirect if needed through an authorized Keycloak admin;
   do not disable PKCE, issuer validation or TLS.
3. Create a new ChatGPT custom MCP connection pointing at
   `https://zagent.ikbalzohr.web.id/mcp` with pre-registered public
   `chatgpt-zagent-mp`, correct OAuth callback, OIDC enabled, and request
   these six scopes. Verify the real callback from the plugin builder rather
   than guessing.
4. From that **new connected ChatGPT session**, call
   `zagent_capabilities`, verify discovered tool counts per agent and test
   `files_list`, `files_write`, `files_powershell_run`, Web and ArcMap
   calls, checking task receipts/results. Document blocked per-agent features
   separately; do not assert that all 82 source definitions are public.

## Rollback rule

Only with Multi Platform stopped, restore the original
`server.py`, `access.py`, `profile_admin.py`,
`payload-manifest.json`, `data/tunnel/config/tunnel.json`, and
`data/files/config/profiles.json` from the backup; remove newly deployed
`full_catalog.py` and newly created
`data/files/config/remote_execution_policy.json`.
Then run `Zagent.Setup verify` again. Never restore into/modify Zagent
Master, and retain this backup until live acceptance.
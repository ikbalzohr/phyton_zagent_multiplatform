# Multi Platform MCP: full discovered catalog (source-only, 2026-11-04)

**Owner decision:** delete the old ChatGPT custom plugin manually and create a new
ChatGPT MCP plugin that exposes all usable *currently discovered* agent tools,
without a second MCP server or a rewrite of Files/Web/ArcMap/QGIS.

## Implementation

- Opt-in Router configuration: `"catalog_exposure": {"mode": "all_discovered"}`.
- `router.full_catalog.inferred_policy` adds a fallback only for tools actually
  discovered by the Router from trusted core service IDs: `zagent_files`,
  `zagent_web`, `zagent_arcmap`, and optional `zagent_qgis`.
- Files scope is exact from `FILES_TOOL_SCOPES` and `PROFILE_ADMIN_SCOPES`.
  Web defaults to `web:control`, ArcMap to `arcmap:execute`, and QGIS to
  `files:execute` under the already-existing QGIS command-authority check.
- The preexisting explicit `tool_policy` **wins** over the inferred fallback:
  `enabled:false` remains disabled, and a mismatched Files scope is rejected.
- Owner-grant `tools:["*"]` is now supported for a deliberately opted-in
  principal. This only bypasses *per-name enumeration* in the grant, never
  bearer validation, token scopes, per-profile root approval, the Files command
  policy, or the source-side profile-management capability.
- Legacy Files management-only APIs and the private profile catalog are not
  remapped into public tools: they retain their existing management-plane rules.
  Discoverable tools whose backend implementation is explicitly unsupported
  (e.g., `files_process_start`) are not guaranteed to execute.

## Owner-controlled activation after code deployment (NOT PERFORMED)

1. **Do not start by deleting runtime folders.** Preserve the current Multi
   Platform installation and back up its private tunnel/profiles configuration
   using the approved Core/owner maintenance procedure.
2. Publish a tested Router candidate (including the new
   `router/full_catalog.py`) to the **Multi Platform only**, with a valid Setup
   manifest and independent rollback; never copy Production config/secrets.
3. Under the existing private tunnel.json, merge the following *fields* into
   the existing objects, without replacing the OAuth issuer, resource URI,
   introspection client, owner principal, device/installation placement or
   existing credentials:

   ```json
   {
     "catalog_exposure": {"mode": "all_discovered"},
     "resource_server": {
       "scopes_supported": [
         "files:read", "files:write", "files:execute",
         "web:read", "web:control", "arcmap:read", "arcmap:execute"
       ],
       "grants": {
         "<existing-owner-principal>": {
           "scopes": [
             "files:read", "files:write", "files:execute",
             "web:read", "web:control", "arcmap:read", "arcmap:execute"
           ],
           "tools": ["*"]
         }
       }
     }
   }
   ```

   **Important:** this is a partial merge illustration, not a replacement
   tunnel.json. Preserve the grant's original `files_resource`, `revoked`,
   expiry, and all other fields. Extend `profile_management` only via the
   established explicit owner capability; `tools:["*"]` does not create it.

4. Configure issuance of matching scopes on the **existing** Keycloak public
   client (PKCE); `scopes_supported` alone does not give a token those scopes.
   If the registered ChatGPT client is reused, keep its exact redirect URI and
   resource audience. Do not reconfigure Production.
5. For write/execute, locally authorize the selected Files profile as
   `read-write` and approve the executable allowlist and command execution
   policy. Neither is escalated by this source change.
6. Restart **only** Multi Platform after its own owner maintenance/rollback
   preflight, then inspect Router discovery and actual OAuth `tools/list`.
   Discovery shows only agents that are available; offline peers reappear after
   discovery retries. Create the new ChatGPT plugin pointing to the same MCP
   endpoint and complete its new OAuth flow **only after those gates pass**.
7. Test representative read, write, execution, Web, ArcMap and QGIS tasks,
   inspect task receipts/results, and reconcile any unsupported or
   management-only tool names separately.

## Verification log

- Router unit tests: 9/9 PASS.
- MCP ASGI plugin integration: 6/6 PASS, including all-discovered mode,
  explicit disable override, and default mode off.
- Full Router regression: 173 tests, 3 skipped, exit 0.
- Code is in source working tree only. Installed binaries/config, Keycloak
  client, existing ChatGPT plugin, domain/Cloudflare and Production: unchanged.
- No live full-catalog OAuth `tools/list`, install, restart, deploy, or
  production acceptance test has been performed.
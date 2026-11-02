# Zagent Multi Platform — MCP OAuth for ChatGPT, Claude and Hermes

Status: SOURCE + OFFLINE TESTS. No public deployment, DNS change, OAuth owner enrollment,
client login, or token issuance is authorized by this document.
**Arsitektur target yang disetujui pengguna:** [ARCHITECTURE_TARGET.md](ARCHITECTURE_TARGET.md).
Zagent Multi Platform dan Zagent Production adalah produk yang terpisah, tanpa dependensi tunnel atau API key bersama.

## Deployment contract

- **MCP resource URI:** `https://zagent.ikbalzohr.web.id/mcp` adalah endpoint yang ditujukan untuk Zagent Multi Platform dan **sebelumnya pernah terkoneksi dengan Hermes** menurut pemilik proyek. Ini **bukan** alamat yang akan dimigrasikan dari Zagent Production. Status koneksi OAuth multi-client pada layanan publik masih harus diverifikasi dengan pemeriksaan live.
- **Issuer:** a separately verified Keycloak HTTPS origin + `/realms/zagent`.
  Issuer in discovery, the authorization-server list, and token `iss` MUST match exactly.
- **Resource server:** `agents/tunnel/engine/router`; it validates introspection
  `active/iss/sub/exp/nbf/aud/scope` and an independent, per-owner authorized grant.
  No token/client label creates a grant; missing/revoked grants deny all tools.
- **Authorization server:** Keycloak 26.8.1, built with experimental features
  `cimd,resource-indicators`; HTTPS + PostgreSQL + private secrets.
  The `resource` query parameter MUST accompany both authorization and token
  requests, and the returned token MUST have exact `aud == resource` (or a list
  containing the exact resource) before Router admits it.
- **No anonymous MCP tools:** even `initialize` requires a valid bearer token;
  if configured but unauthenticated the Router returns HTTP 401 with
  `WWW-Authenticate: Bearer resource_metadata="https://.../.well-known/oauth-protected-resource/mcp"`.
  The Router serves both `/.well-known/oauth-protected-resource/mcp` and
  `/.well-known/oauth-protected-resource`; ingress MUST expose both on the
  **MCP resource host** with correct TLS certificate.
- **Keycloak OIDC discovery:** `https://<issuer-origin>/realms/zagent/.well-known/openid-configuration`
  must advertise PKCE `S256`, `token_endpoint_auth_methods_supported`
  with public-client method `none`, `issuer`, token and authorize endpoints,
  and `authorization_response_iss_parameter_supported` only if EVERY callback
  including error responses sends the exact RFC9207 `iss`.
- **Scopes:** begin with `files:read` only. No `files:write`, `files:execute`,
  `web:control`, `arcmap:execute` or QGIS writes until separately reviewed
  and approved through owner grants and permission enforcement.

## Client identity mechanisms

| Client | Safe choice | Client ID / callback |
|---|---|---|
| ChatGPT | **Pre-registered public PKCE client** in Keycloak (not its incompatible CIMD parser) | `chatgpt-zagent-mp` / exact `https://chatgpt.com/connector_platform_oauth_redirect` **only once live RFC9207 issuer callbacks are confirmed** |
| Claude Code + Claude Desktop | CIMD, a **single** reviewed Keycloak client policy matching `claude.ai` | Client-supplied HTTPS metadata, client-supplied verified redirect. One policy supports both localhost (Code) and HTTPS Claude callback (Desktop). |
| Hermes Agent | CIMD via its published `nousresearch.github.io` document; alternatively existing pre-registered PKCE `hermes-zagent` | `mcp_servers.zagent_multi_platform.url = <resource>`, `auth: oauth`. If preregistered, add `oauth.client_id: hermes-zagent`, `oauth.redirect_port: <approved port>`. |

**Important Keycloak compatibility constraint:** Keycloak 26.8.x's default CIMD parser
does **not** accept ChatGPT's plural `token_endpoint_auth_methods_supported` field.
A simple `KC_FEATURES=cimd` switch does not solve this. Do not advertise CIMD
support for ChatGPT unless you install and validate the separate custom Keycloak
policy executor required by the provider. Use its pre-registered public client
instead; never allow wildcard redirect URIs. Source:
https://www.keycloak.org/securing-apps/mcp-authz-server

For Claude Code and Desktop, enable **one** `client-id-metadata-document` policy,
not two conflicting profiles:

1. Run the renderer and review `cimd-policy-review.json` (an **intent document,
   NOT an importable Keycloak policy**). It binds both profile conditions to the
   exact resource, and restricts CIMD URLs to `claude.ai` or
   `nousresearch.github.io`.
2. In Keycloak Admin Console, configure the CIMD executor/URI condition for the
   appropriate profile. Claude requires trusted domains `claude.ai`,
   `localhost`, `127.0.0.1`, same-domain restriction OFF,
   *Accept Public Client with Confidential-only Grant Types* ON to handle
   Desktop metadata. Hermes requires its current metadata hosts and
   redirect(s) verified before its policy is enabled.
3. Set **Resource indicator allow list** to the exact MCP URI for each CIMD
   executor. The feature flags alone do not activate client policies.
4. Keep Keycloak's anonymous Dynamic Client Registration **closed** until a
   separately reviewed least-privilege DCR policy can be demonstrated.

The pre-registered ChatGPT and Hermes clients are public Authorization Code +
PKCE S256 clients, not confidential machine clients. Keycloak rotates refresh
tokens (`revokeRefreshToken=true`, `refreshTokenMaxReuse=0`) and issues
short-lived access tokens. Do not store client secrets in repository, CLI args,
browser URLs, or MCP responses.

## Rendering, staging and tests (NO live activation)

The deployment template is `packaging/oauth/deployment.example.json`, intentionally
nondeployable. Prepare a private Linux-only copy with verified actual issuer
origin, the exact MCP resource URI, an approved **Hermes** loopback callback and
private TLS/secret paths. Render into a NEW empty directory on the Linux host:

```bash
python3 packaging/oauth/render.py /private/zmp-oauth.json --output /private/zmp-render-001
python3 -m unittest discover -s packaging/oauth -p 'test_deployment.py' -v
```

Renderer generates a Keycloak realm import, nginx issuer proxy snippets,
deployment environment, and `cimd-policy-review.json`. Review certificate,
`resource_url`, exact callbacks, domain restrictions, resource indicator
allow-list, client scopes, issuer response `iss`, and policy activation BEFORE
opening ingress. The template presently does not automatically install CIMD
policies or create the Windows owner grant. The existing Keycloak image remains
isolated on an internal Docker network and does not publish database/admin
ports to the host.

After authorization-server owner enrollment and DNS/TLS/ingress approval, test
the Multi Platform staging endpoint **tanpa mengubah Zagent Production**:

```bash
python3 packaging/oauth/check_mcp_readiness.py "https://<approved-mcp-host>/mcp" \
  "https://<approved-issuer-host>/realms/zagent"
```

This performs GET metadata, OIDC PKCE discovery, and **unauthenticated POST
initialize must be HTTP 401**. It sends no credentials and performs no writes.
Then run authorized, owner-approved tests for each of ChatGPT, Claude Code,
Claude Desktop and Hermes: browser consent, callback `iss/state`, PKCE S256,
resource in authorize and token requests, refresh rotation, token introspection,
wrong audience/scope/issuer, revoked grant, `tools/list` and one read-only tool.
Do not assume any routing, tunnel credential, or public endpoint is currently owned by Zagent Production; verify Multi Platform's ingress independently before activation.

## Outstanding release gates

- Owner-approved issuer domain, DNS records, TLS and VPS runtime/secret provisioning.
- Keycloak CIMD client-policy activation verified against deployed 26.8.1,
  including Claude Desktop grant-type workaround and Hermes metadata URLs.
- Actual ChatGPT **pre-registered** client selection/callback from ChatGPT's
  management UI; verify `iss` before relying on the stable callback.
- Exact external token resource/audience claim and public issuer introspection.
- Local owner principal grant derived from actual access-token `sub`, in
  Core-managed private Router config; never guess it or copy Production grants.
- External end-to-end connection and refresh tests on **each** supported client.
- Independent Multi Platform public activation, rollback plan, and proof that Zagent Production is untouched.

Dashboard local-owner login changes are not involved in this OAuth flow.

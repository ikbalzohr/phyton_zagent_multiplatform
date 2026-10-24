# External OAuth deployment: Keycloak → Windows Zagent → Hermes

## Verified initial deployment (coordinator)

The VPS disk blocker was resolved by the owner. Docker, Compose v2, nginx and Certbot are now installed. Keycloak 26.8.1 runs in production mode with PostgreSQL; realm `zagent` was read back via the private Admin API. nginx trusted HTTPS discovery returns the exact issuer `https://vmi3669591.contaboserver.net/realms/zagent`. The Let's Encrypt certificate was issued successfully and expires 2027-01-22. Public `/admin/`, master discovery and health routes return 404. Public `/mcp` also returns 404: it is a reserved future audience, NOT a working Windows bridge.

The registered `hermes-zagent` client remains DISABLED, with exact loopback callback and S256 configured. No owner login, Hermes token, Windows introspection credential transfer or local grant activation is complete. Bootstrap administrator is still temporary and requires secure replacement/removal before operational use. Generated bootstrap credentials are CSPRNG-created, owner-protected outside source, never displayed; this coordinated bootstrap differs from the optional interactive helper below.

Docker 29 did not publish a loopback port for the internal network. The deployed design instead fixes private container addresses (PostgreSQL `.2`, Keycloak `.3`) on `172.30.88.0/24`; host nginx reaches `172.30.88.3:8080`, with only gateway `172.30.88.1/32` trusted. Neither container publishes a host port. Both have bounded container logs.

Five deployment-template tests and live HTTPS discovery/private-path checks passed. **Renewal dry-run failed twice with CA-reported CAA DNS SERVFAIL for the provider-owned domain.** Existing certificate remains valid, but renewal is NOT verified; timer and nginx reload hook exist. An owned domain is advisable for durable production use. No Windows Zagent runtime tests were run on VPS.

The remaining sections describe the original prerequisites and generic operator procedure; historical discovery is not the current host state.

## Original prerequisites / deployment procedure

**SOURCE PREPARED; LIVE DEPLOYMENT NOT RUN.** This package is a real production-mode
Keycloak/PostgreSQL deployment candidate, not a token mock or replacement OAuth endpoint.
No package installation, image pull/build, service start, firewall change, secret generation,
Windows run, or Hermes gateway restart was performed by this workstream.

Parent's VPS discovery (not re-measured by this source-only workstream): Ubuntu 24.04.5,
Java 21 present, Docker/Podman/nginx/PostgreSQL absent; root filesystem 100% used with
233 MB available, available RAM about 4.9 GiB. **Installation/deployment is blocked by disk.**
`/var/lib/harry-fb-browser` belongs to another profile: **do not delete it**. Obtain explicit
owner approval for expansion or a separately reviewed cleanup, then measure free space again.
A Java-only launcher does not solve database/image/log/backup disk requirements.

`vmi3669591.contaboserver.net` is a discovered hostname, **not proof of DNS control,
TLS certificate eligibility, or a usable OAuth issuer**. No owned issuer domain is known.
Existing public ports 22/20128 must be left unchanged; 80/443 were not listening at discovery.
The parent must independently approve TLS ingress/firewall changes; this package does not make them.

## Operator prerequisites (all mandatory)

1. Resolve disk exhaustion with owner approval; retain capacity for OS updates, image build/pull,
   PostgreSQL growth/WAL, protected backups and logs. No fixed space promise is made.
2. Approve and install Docker Engine with Compose v2 and nginx using the platform's official
   packages. These are absent now. Do not start with the 233 MB free-space condition.
3. Supply a **stable public HTTPS issuer DNS hostname**, prove control and configure DNS.
   Windows, the Hermes VPS, and the human login browser must all resolve/reach it with a
   trusted certificate. Obtain/renew the certificate (e.g. approved DNS-01 flow) before nginx
   is enabled. No self-signed TLS or `verify=false` workaround.
4. Supply the **exact public HTTPS Windows MCP resource URI**, including path and trailing
   slash convention, plus the **actual Hermes callback URI** from the client integration owner.
   Do not guess the callback port/path. Public HTTPS callbacks or exact
   `http://127.0.0.1:PORT/PATH` native-loopback callbacks are accepted by the renderer.
   For a remote VPS login callback the browser must actually reach that callback (e.g. an
   explicitly configured SSH local-forward); registering loopback alone does not establish this.
5. Verify no subnet conflict with `172.30.88.0/24`, no port conflict with local 8088, sufficient RAM,
   and that Docker host→container forwarded traffic is observed as gateway `172.30.88.1`.
   Restrict trusted proxy addresses to the actual measured source; never use `0.0.0.0/0`.
6. Provide a protected, root-controlled runtime directory outside the repository, a password
   manager/vault for the temporary admin credential, secure Windows credential provisioning,
   and backup/restore ownership. Never send credentials in chat or put them in source.

A random temporary HTTPS tunnel can help experiments, but is **not silently interchangeable
with a stable issuer**. If its hostname changes, issuer, discovery, token `iss`, audience/resource
bindings, callbacks and principal IDs may change; old refresh credentials/grants can fail.
Named tunnels require provider/account/domain prerequisites. This package assumes a host nginx
TLS endpoint; adopting a tunnel requires a separately reviewed route/header/certificate design.

## Included artifacts

- `compose.yaml`: persistent PostgreSQL 17, no published DB port, isolated bridge, Keycloak
  reachable by host nginx at **private `172.30.88.3:8080`**, with no published host port; management port 9000 unpublished, service memory limits.
- `Containerfile`: optimized production Keycloak 26.8.1, PostgreSQL driver built in, nonroot UID
  1000; no `start-dev`, H2/dev database, or public admin bootstrap endpoint.
- `realm.template.json`: no users/passwords; separate interactive and introspection clients.
- `render.py`: stdlib-only NONSECRET config renderer; refuses example/malformed URLs,
  redirect wildcards, runtime paths inside this repo, and overwriting existing output files.
  Outputs realm JSON, nginx public site/snippet, and nonsecret Compose environment file.
- `create-secrets.py`: explicit operator-only, interactive secret-file creation; not called by
  rendering/tests. Root-controlled directory mode 0700, files 0600 owned by container UID 1000.
  This ownership is necessary because local Compose file secrets are bind mounts and their
  `uid`/`mode` declarations cannot reliably change the source file's permissions.
- `start.sh`: fails before startup if required secret files are absent/unreadable/empty;
  loads secrets into the Keycloak process, never into Docker's configured environment or argv.
- `check-discovery.py`: read-only trusted-HTTPS discovery/PKCE/private-path check, explicitly
  not an end-to-end OAuth or MCP test.
- `test_deployment.py`: offline fixture checks, including actual renderer file output/refused overwrite.

Compose is intentionally a **single-node** deployment (local cache), not HA. Database and
proxy/backend traffic are cleartext only on this same trusted Docker host/isolated bridge;
public traffic uses nginx TLS edge termination. The official proxy guide now prefers TLS
re-encryption for general production. If other workloads on this host cannot be trusted, do
not deploy this single-host edge design: use re-encryption plus authenticated DB TLS/isolation.
Root/Docker access and process memory/environment are trusted boundaries; file secrets do not
protect against a malicious host administrator. Avoid unrestricted container log collection.

## Minimal realm/client model

Realm: `zagent`; registration, password-reset-by-email, implicit flow, password grant,
client service accounts, CIBA and device grants disabled in the defined clients. No imported
users, passwords, realm-management roles or local Zagent grants. Access token lifetime 300s;
SSO idle/max 1800s/28800s; refresh rotation enabled with max reuse zero. A client must serialize
refresh and atomically retain the replacement refresh token; parallel reuse can revoke sessions.
No `offline_access` scope is assigned.

| Client | Purpose | Credentials/permissions |
|---|---|---|
| `hermes-zagent` | Interactive authorization code + required PKCE S256 | Public client; exact callback; no client secret; standard flow only; consent required |
| `zagent-resource-server` | Windows RFC 7662 introspection | Confidential HTTP Basic client; own secret; **all issuance grants disabled**, no admin roles |

Optional client scopes are exactly the router example's `zagent:read`, `files:read`,
`files:write`, `web:control`, `arcmap:inspect`, `arcmap:execute`, `artifacts:read`. The
interactive client requests only those approved for its intended work. Merely requesting a
scope never creates a Windows grant; privileged scopes remain gated by local owner policy.
The automatically attached audience scope emits `aud` containing **the exact resource URI**
and the introspection client's ID. `introspection.token.claim=true` is explicit. The client-ID
audience supports separate-client introspection checks; the URI audience satisfies Zagent's
exact comparison. Do not replace the URI audience with only `zagent-resource-server`.

This is **one pre-registered client for one resource** with a static audience mapper, not a
claim of general RFC 8707 dynamic resource selection, CIMD, anonymous DCR, or MCP client
compatibility. Hermes must use this registered client ID and real callback. Its actual PKCE,
resource-parameter, registration and refresh behavior must be verified by the integration owner.
Do not enable anonymous registration or password grants as a fallback.

## Explicit operator commands — only AFTER prerequisites and approval

These commands are a future checklist, **not execution evidence**. Run from `/root/zagent-v1`.
Choose real absolute runtime paths; `/root/zagent-oauth-runtime` below is an operator-owned
example path, not a pre-existing installation. No secret values belong in `deployment.json`.

```sh
# Create only after resource/ownership approval:
install -d -m 0700 /root/zagent-oauth-runtime
cp packaging/oauth/deployment.example.json /root/zagent-oauth-runtime/deployment.json
# Edit all REQUIRED fields with verified origins/callback/certificate paths.
# Set secret_dir to /root/zagent-oauth-runtime/secrets (directory must not exist yet).
python packaging/oauth/render.py /root/zagent-oauth-runtime/deployment.json \
  --output /root/zagent-oauth-runtime/rendered
python packaging/oauth/create-secrets.py --directory /root/zagent-oauth-runtime/secrets
# Bootstrap prompt: enter a password-manager-stored 24+ ASCII alphanumeric password.
# This is the ONLY step that generates DB/introspection secrets, and was NOT RUN here.

docker compose --env-file /root/zagent-oauth-runtime/rendered/deployment.env \
  -f packaging/oauth/compose.yaml config --quiet
# Inspect resource/subnet/trusted-proxy choices BEFORE building.
docker compose --env-file /root/zagent-oauth-runtime/rendered/deployment.env \
  -f packaging/oauth/compose.yaml build --pull
docker compose --env-file /root/zagent-oauth-runtime/rendered/deployment.env \
  -f packaging/oauth/compose.yaml up -d
```

Compose `config --quiet` avoids printing resolved configuration. No secret is passed through
its environment file. Never use `docker compose down -v`: that destroys issuer identity,
users, signing keys and client secrets stored in PostgreSQL. Startup import **skips an
existing realm**; editing source then restarting is not a realm migration or secret rotation.
Never run an overriding import against a live server.

nginx is a host prerequisite, not another service started by Compose. Parent reviews the
rendered files, checks that cert/key exist with appropriate permissions, installs
`zagent-keycloak-proxy.conf` as `/etc/nginx/snippets/zagent-keycloak-proxy.conf`, installs/enables
`keycloak.nginx.conf` using the host's chosen site convention, runs **`nginx -t`**, then only
with explicit authorization starts/reloads nginx and exposes 443. Do not blindly copy over
an existing/default site. Port 80 is not configured; certificate issuance/renewal is separately
owned. Check unknown-host/default-vhost behavior in the final host nginx configuration.

Public allowlist includes only zagent OIDC protocol, login actions, discovery and static
resources. `/admin/`, master realm, account console, health/metrics and registration paths
return 404. Forwarded host/proto/port/source headers are overwritten and prefix is cleared.
Do not put Cloudflare/another proxy in front without adjusting and testing the trust chain.

### Private administration and initial user

Use a root-authorized local container Admin CLI, not a public `/admin` route. For example,
after the server is healthy:

```sh
docker compose --env-file /root/zagent-oauth-runtime/rendered/deployment.env \
  -f packaging/oauth/compose.yaml exec keycloak \
  /opt/keycloak/bin/kcadm.sh config credentials --config /tmp/zagent-admin.config \
  --server http://localhost:8080 --realm master --user bootstrap-admin
# kcadm prompts interactively; obtain the credential from the operator password manager.
# Never use --password VALUE in shell history or logs.
```

The local `master` token endpoint is used only from inside the container; it is not public.
`/tmp/zagent-admin.config` contains an admin token: keep it owner-only and remove after use.
Parent must provision a permanent, MFA-protected administrator and an owner login in `zagent`
via authenticated private Admin API/CLI tooling with **protected file/stdin credential input**,
verify the owner login, remove the temporary `bootstrap-admin` account, and delete the cached
admin CLI config. No owner account is preseeded or guessed here. If no secure credential
provisioning route is available, stop; do not temporarily expose Admin UI to the internet.
The bootstrap secret file is still required by this entrypoint after bootstrap; delete the
*account* first. A future reviewed post-bootstrap override may remove the mount/startup option;
do not remove a required file alone and expect this fail-closed entrypoint to start.

## Windows and Hermes bindings (integration-owner work)

Keep authoritative Windows configuration in its owner-approved DataRoot, not this repository.
For issuer origin `ORIGIN` selected above, configure these exact nonsecret values:

```text
resource_uri             = exact approved public Windows MCP URI
issuer                   = ORIGIN/realms/zagent
authorization_servers    = [ORIGIN/realms/zagent]
introspection_endpoint   = ORIGIN/realms/zagent/protocol/openid-connect/token/introspect
introspection_client_id  = zagent-resource-server
introspection_secret_env = ZAGENT_OAUTH_INTROSPECTION_SECRET
```

Transfer **only** the introspection secret to the Windows installation owner's protected
credential store through an approved secure channel; child1 owns the concrete secret-store
integration. It must arrive in the router's process environment without plaintext source,
`.env`, launcher arguments, chat or logs. Do not transfer the DB/admin secrets. Do not confuse
this OAuth secret with Core's internal DPAPI secret; these are separate security domains.

Obtain the actual owner user's `sub` from the real issuer. Existing router principal derivation
is `principal_v1_` + SHA-256 of UTF-8 compact JSON `[issuer, sub]` (`ensure_ascii=False`, JSON
separators comma/colon); compute it with code, not by hand. A renamed hostname changes this
binding. The Windows owner must create an explicit, expiring/revocable grant with workspace,
policy revision, minimal scopes, tool allowlist and approved profiles/resources. Keep `grants`
empty until that owner approval; a valid OAuth token alone intentionally receives 403.
Hermes interactive credentials/refresh state must remain separate from introspection credentials.

## Acceptance gates before claiming working

1. Offline checks (safe on the current disk-constrained host):
   `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s packaging/oauth -p 'test_*.py' -v`.
2. After parent deployment, from VPS and Windows run equivalent trusted-TLS discovery checks;
   on VPS: `python packaging/oauth/check-discovery.py https://REAL_ISSUER_HOST`.
   Match the complete issuer string, all endpoints and S256. No HTTP redirects allowed by this checker.
3. Inspect public/private sockets and outside reachability: only approved ingress, no 8088,
   5432, 9000, master/Admin API/UI, health or metrics exposed. Confirm proxy source trust and
   that forged forwarded headers cannot change scheme/issuer/client address.
4. Use real Hermes code+PKCE login (no password grant, fake tokens, token pasted into chat,
   TLS bypass or mocked introspection). Verify bad callback/missing-or-bad S256 rejected.
5. Using the router's actual Basic-auth client, verify real introspection JSON has
   `active: true`, exact `iss`, nonempty stable `sub`, numeric future `exp`, exact URI in `aud`,
   and string `scope` with requested approved scope. Wrong introspection secret must fail.
   Keep tokens/secret-bearing request/response data out of reports/logs.
6. Prove real Windows StreamableHTTP MCP initialize/tools plus one owner-approved read-only
   operation. Wrong audience, expired/revoked token, absent/revoked local grant, wrong workspace,
   denied tools/scopes and issuer outage must fail closed; no arbitrary command bypass.
7. Wait for/access token expiry, verify serialized refresh with rotated refresh token and
   continuity of identity/grant; verify restart persistence and revocation behavior.
8. Create a consistent PostgreSQL backup (including signing keys/client identity), protect it
   with encryption/access controls, restore in an isolated approved environment and verify.
   Realm export alone is not a complete backup of sessions/events/revocations.

## Verified inputs and official references

Registry metadata was retrieved without image downloads. Pinned upstream multi-architecture
manifest digests (tag movements do not change these pinned references):

- Keycloak 26.8.1:
  `sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b`
  from https://quay.io/api/v1/repository/keycloak/keycloak/tag/?specificTag=26.8.1
- Official PostgreSQL `17-bookworm`:
  `sha256:858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27`
  from https://hub.docker.com/v2/repositories/library/postgres/tags/17-bookworm
  (exact installed minor must be read from the approved image after deployment; not guessed).

Parent must review security advisories and refresh pins deliberately before deployment;
these lookups do not claim vulnerability-scanned images or a successfully built container.

Official documentation consulted:
- https://www.keycloak.org/2026/10/keycloak-2681-released — release/security fixes.
- https://www.keycloak.org/server/containers — optimized build and production container start.
- https://www.keycloak.org/server/db — PostgreSQL supported; dev-file unsuitable for production.
- https://www.keycloak.org/server/hostname — fixed HTTPS origin and issuer security.
- https://www.keycloak.org/server/reverseproxy — edge mode, trusted addresses, headers, private management.
- https://www.keycloak.org/server/importExport — environment substitution, startup skip, backup limitations.
- https://www.keycloak.org/server/bootstrap-admin-recovery — temporary bootstrap account lifecycle.
- https://www.keycloak.org/securing-apps/oidc-layers — real discovery/token/introspection endpoints,
  confidential-client introspection, authorization-code and redirect guidance.
- https://raw.githubusercontent.com/keycloak/keycloak/26.8.1/services/src/main/java/org/keycloak/protocol/oidc/endpoints/TokenIntrospectionEndpoint.java
  — implementation confirms confidential client authorization and separate token provider.

**Not verified here:** Docker Compose runtime validation, image build/start, nginx parser/TLS,
DNS ownership, live realm import, actual client login/refresh, Windows introspection/MCP, backups.
No deployment readiness claim is justified until the stated blockers and acceptance gates pass.

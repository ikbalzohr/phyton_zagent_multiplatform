# Router → Files resource policy (source contract, runtime NOT_RUN)

The Streamable HTTP perimeter and OAuth RFC7662 authorizer are unchanged. This contract does not provision an authorization server, tunnel, token, local profile or remote command execution.

## Server-owned profile binding

An owner provisions one `files_resource` on each approved principal grant in the actual DataRoot `tunnel/config/tunnel.json`:

```text
resource_server.workspace_id / policy_revision
resource_server.grants[principal_id].files_resource
```

Use `agents/tunnel/engine/config/files-grant.provisioning.example.json` as the **grant value**, not a complete tunnel configuration. It is deliberately revoked at both grant and resource level; it is not loaded automatically. Keep the main template's `grants: {}` until the owner has approved the principal, workspace, exact local profile/root, placement, read tools and scopes. Principal IDs are computed by the existing issuer/subject function; never invent one from a client label. Example placeholders are not provisioned identifiers.

The mapping is described by `schemas/zagent-files-resource-v1.schema.json`: `resource_id`, exact `kind: files`, `profile_id`, `device_id`, `installation_id`, optional boolean `revoked`. The workspace is the resource server's configured workspace, and the principal is the grant map key. Files requires a **profile name**, not a path or a global default. Mapping absence, malformed/empty profile, wrong kind/placement, resource revocation, absent/revoked/expired grant, workspace/revision mismatch all deny dispatch. No fallback to `appBridge` or any other profile exists.

The Router cannot establish local root approval merely from JSON. Files must independently find that profile enabled, `authorized_by_user`, and approved for its local root/mode. A nonexistent, disabled or locally revoked profile stays denied by Files; adding a server mapping never creates or approves it. Start with a read-only grant. Write authorization and a canary are separate owner gates.

The mapping emits only `{resource_id, kind, profile_id}` inside trusted `effective_resources`. `effective_resources`, `files_resource`, `_meta` and `metadata` cannot be authority in public tool arguments. Existing `profile_id` arguments on workspace status/switch remain **selectors only**: Files checks membership in the trusted resource scope and local approval. No public argument can change the resource emitted by Router.

Scopes remain the intersection of introspection and local grant policy; the tool allowlist remains server-owned on the grant. The existing conservative `effective_access: write` scheduling envelope is not a new write scope, and the scheduler continues locking `installation:<installation_id>` (not individual profile resource IDs). Scope/tool authorization is still required before dispatch. No Files command/update restriction changes.

## Queues, refresh and workflows

`_dispatch` resolves the resource from current local policy before journaling a task. `_revalidate` re-introspects the in-memory bearer and resolves the current mapping again before each executor call; it compares it exactly with the original context. Mapping deletion, revocation, replacement or placement changes reject old queued tasks, even if an operator forgot to bump `policy_revision`. Do bump the revision when changing policy. Revalidation never mints a new context, replaces its resource, extends its deadline, or broadens scopes. Tokens are not persisted; restart still loses execution authorization.

Scheduler journal stores the context unchanged, and its idempotency comparison includes `effective_resources`. Workflow step authorization already calls `_revalidate`; ArcMap/browser resource generation is otherwise unchanged. The ArcMap-specific live adapter has a separate exact loopback validator and is not expanded by this Files patch. This is not a claim that ArcMap workflows on `.3` are connected.

## Exact Core loopback alias

Core defaults to `127.0.0.3` and writes it into `security.allowed_hosts`. Router service validation now accepts **that exact literal only when explicitly present in `allowed_hosts`**, including when the legacy local-only switch is false. It does not allow `127/8`, CIDR entries, wildcard hosts, `.2`, other numeric aliases, or non-loopback hosts. Existing credentials/query/fragment and HTTP policy checks stay in place. The provisioning example includes `.3`; checked-in unprovisioned `tunnel.json` remains unchanged.

Router startup also accepts exact configured bind `.3` (otherwise Core still fails before upstream discovery). This adds no public bind and changes no port or `/router/*` peer/token checks. Core source did not need modification for this seam.

## Verification boundary

VPS validation is non-executing source inspection only: AST/JSON parse, textual/AST regression checks, fixture path resolution, and `git diff --check`. No product imports, tests, agents, server, build or service connections are run on VPS. Test sources are authored for the Windows gate and remain **NOT_RUN**; source checks are not a runtime RED→GREEN result.

Focused Windows test sources: `agents/tunnel/engine/tests/test_files_resource_policy.py` and `test_mcp_host_sessions.py`. They cover server policy, negative bindings, scheduler preservation, actual Files channel consumer shape, auth-refresh comparison and exact loopback rejection. The refresh fixture imports Router server (which opens journals): run only in an isolated owner-approved Windows test DataRoot with its dependencies, never in a live install. No Windows execution, read/write canary or OAuth/transport readiness has been proved by this patch.

# Owner-authorized allowlist tool access

`zagent_allowlist_access` is an immediate native MCP administrative control, not a durable Files job or arbitrary grant editor. Existing OAuth must already identify the current owner with exact `files_profile_admin_update` tool permission, both `files:read` and `files:write`, and the strict existing `profile_management` capability including action `update`, bound to the current workspace/device/installation. A valid unrevoked/unexpired grant and Files resource are required. Existing managed catalog ownership is validated through the normal catalog consumer.

Plan: call with `{}`. This makes no config changes. Inspect `add`, `tools`, `revision`, and `expected_plan`. Apply explicitly:

```json
{"plan_only":false,"expected_revision":"<raw-byte revision from plan>","expected_plan":"<fingerprint from plan>"}
```

Only these memberships can be added to the authenticated actor's existing `grant.tools`: `files_allowlist_list`, `files_allowlist_add`, `files_allowlist_remove`, `files_allowlist_replace`. No tool-name, principal, scope, path, executable, or command argument exists. Unknown fields fail schema validation. No scope, policy, capability, resource, other grant, credential, or unrelated configuration value is modified. Explicitly disabled or malformed policies are never overridden. All four canonical upstream names must already be discovered on a Files backend. Fresh authentication at commit checks revocation and existing authority again.

Publication uses the installed Router `config.TUNNEL_FILE`, the installation read lease, a shared writer lock (also used by `config.atomic_write_json`), unique same-directory staging, fsync, raw-byte CAS, and atomic publication. Existing Windows files use `ReplaceFileW` without a fallback to ACL-changing replacement. A sibling `.access-audit.jsonl` records only projection hashes, identity, additions and fingerprint, not configuration contents or credentials. It is an fsynced **intent** record: an intent alone is not a success. Exact resulting raw-config digest readback determines `audit_verified`; publication failure leaves the old grant intact and unmatched intent is not reported verified. A subsequent plan is read-only and reports `state: enabled` when all memberships exist. A stale apply is rejected; already enabled plans can be applied as no-ops. Refresh MCP discovery after authentication reloads the updated grant.

Windows ACL/cross-process behavior, deployment/restart through Core, live owner OAuth, and actual client visibility require target verification. Disposable Linux ASGI tests exercise the real introspection consumer against a fixture issuer and do not certify live ChatGPT/Claude acceptance. Installed private configuration is never used by those tests.

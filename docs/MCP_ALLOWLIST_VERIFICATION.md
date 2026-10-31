# MCP-first allowlist: source verification and handoff

## Delivered scope

Four native MCP tools manage exact executable membership for one existing authorized Files profile: `files_allowlist_list`, `files_allowlist_add`, `files_allowlist_remove`, and `files_allowlist_replace`. Existing OAuth and principal/resource/profile authorization remain required. These tools do not depend on Hermes sessions, Telegram approval, legacy broker enrollment or runtime checker services. No legacy broker code was removed or activated.

See [MCP_ALLOWLIST.md](MCP_ALLOWLIST.md) for argument/result contracts and client/Windows acceptance boundaries.

## Final exercised gates (Linux disposable fixtures)

- Native Files + in-process HTTP Router integration + Router discovery/policy regressions: **30 passed, 119 subtests passed**, exit 0.
- Complete Router directory: **126 passed, 565 subtests passed**, exit 0.
- These suites overlap; the counts are not a unique-test total.
- Python AST and staged whitespace checks are required before commit.
- Pytest emitted a deprecation warning about unset `asyncio_default_fixture_loop_scope`; neither gate failed or skipped on that account.

Native gate, from repository root using a Python environment with the repository requirements plus pytest installed:

```text
python agents/files/engine/tests/run_native_allowlist.py agents/files/engine/tests/test_router_allowlist_native.py agents/tunnel/engine/tests/test_allowlist_router_discovery.py
```

The full Router gate used this runner's disposable config setup with only its test target changed to `agents/tunnel/engine/tests` and its injected installation identity empty. Router tests supply their own installation identities. This prevents fixture contamination; no product identity check was modified. Running every test in the same native fixture environment without this separation can produce an unrelated installation-identity mismatch.

Verified behavior includes:

- Real native registration, trusted context and permitted non-default profile selection.
- HTTP ASGI tools/list -> durable tools/call receipt -> worker execution -> terminal task result; OAuth authentication in this fixture is a synthetic test adapter, not a real token/login.
- Add/remove/replace consumed by the actual command-policy parser and executable resolver; unrelated validated policy fields preserved.
- Stale/malformed revisions, wildcard/non-exact paths, duplicate entries, unknown fields and final-entry removal rejected without policy writes.
- Two competing in-process writers at the same revision: one commit, one revision conflict. This is not proof against arbitrary owner-local writers ignoring the shared lock.
- Failed publication leaves policy unchanged in the simulated pre-publication failure case.
- Profile-administration read lease is used. Expected validation/conflict codes retain MCP `isError`; unknown/private exceptions still use existing diagnostics.
- Router `tool_policy` remains authoritative; only the four exact new native tool names have defaults when no explicit entry exists. Existing explicit disables, malformed entries and canonical Files scope checks remain intact.

## Explicitly not accepted here

- Windows `ReplaceFileW` DACL preservation, cross-process lock, reparse defenses and failure recovery on the actual target.
- Actual Windows tool discovery, installed grants/tool membership, live OAuth, refresh and ChatGPT/Claude/Hermes application acceptance.
- Build/deployment/restart, production policy mutation or permission provisioning.
- Resolution of orphaned task `tsk_0bd717b5538149d78797d45e29abc4ec` / installation quarantine. Source pull does not clear its journal; restarting is not evidence of reconciliation.

No private configuration, grant, credential or production policy was used or changed by these gates. Pull source on the laptop after preserving local changes, then run target-side isolated acceptance before production use. Existing grants that enumerate exact tool names still require legitimate owner-controlled provisioning; this source commit does not modify them.

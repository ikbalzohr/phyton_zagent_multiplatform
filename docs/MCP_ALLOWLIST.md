# MCP-first executable allowlist: Windows and client handoff

## Status and trust boundary

The native MCP source now implements the four tools below; this is **source delivery, not deployed Windows acceptance**. The handoff record is `docs/MCP_ALLOWLIST_VERIFICATION.md`. Windows publication/ACL, live policy mutation and each client login remain **NOT_RUN**. Existing legacy broker code remains present but is not a dependency of these native tools.

The selected boundary is existing authenticated MCP authorization plus the caller's existing Files resource/profile membership. No Hermes checker, chat/session identity, Telegram approval, signed backup, new owner enrollment or separate broker approval is a prerequisite for this feature. Existing OAuth issuer/audience/expiry/revocation checks, exact tool permissions, scopes, placement and profile-generation checks remain mandatory. Do not weaken other tools or rewrite grants through generic Files commands.

An authenticated client admitted to these tools can administer executable permission. An allowed interpreter executes with Windows owner-account rights, not a Files-root OS sandbox. Removing a rule is not termination of an already running process.

## Native public surface

| Proposed exact tool | Scope | Intent |
|---|---|---|
| `files_allowlist_list` | `files:read` plus exact tool permission | Read only the selected authorized profile's executable projection and full-policy revision. |
| `files_allowlist_add` | `files:write` plus exact tool permission | Add one validated exact executable at an expected revision. |
| `files_allowlist_remove` | `files:write` plus exact tool permission | Remove one exact existing executable at an expected revision. |
| `files_allowlist_replace` | `files:write` plus exact tool permission | Exchange one existing executable for one new executable atomically. |

All calls require `profile_id`. List returns `ok`, `profile_id`, `revision` (SHA-256 of the full raw policy) and `executables`. Add/remove require `executable` and `expected_revision`; replace also requires `replacement_executable`. Mutations return `ok`, `profile_id`, `previous_revision`, `revision`, `changed`, `added` and `removed`. Inputs reject extra fields; revision must be 64 lowercase hex characters. Use exact executable paths, not basenames or wildcards. The last entry cannot be removed (`NONEMPTY_ALLOWLIST_REQUIRED`); use replace to exchange it atomically. `REVISION_CONFLICT` requires a new list and reassessment. Discover the deployed schema before use; source schemas do not prove live discovery.

A receipt is not success. Capture its task ID, retrieve the ordinary owner-bound terminal task/domain result, inspect MCP `isError` separately, then read back the same profile projection. Re-list after revision conflict and reassess intent; never blindly replay an unknown outcome.

Existing command execution still needs its existing `files:execute` and `files:write` scopes, local command policy and tool admission. Adding executable membership must not turn execution on, add execution scopes/tools, widen roots or change unrelated profiles/limits. Ordinary `files_execute` must not become an allowlist administration bypass.

## Actual storage/consumer facts from source

`agents/files/engine/app/mcp/managed_commands.py` reads `CONFIG_DIR / 'remote_execution_policy.json'` at authorization time. Policy v1 is one strict profile entry; v2 is a strict profile map. The member is **`allowed_executables`**, not `allowedExecutables`. Existing consumer code admits only a nonempty bounded list and can resolve an unambiguous executable basename from already admitted absolute entries; it does not resolve arbitrary PATH requests. The new administration input must remain exact-path-only without silently broadening those consumer semantics.

Baseline parser rejects unknown policy keys. Therefore unknown-field preservation is **not established** merely by copying a JSON object; integration must explicitly reconcile preservation with the actual parser and show tests. Final-entry removal semantics must also agree with the consumer rather than reporting success for a policy it cannot consume. The legacy `app/allowlist/engine.py` has a Windows cross-process `.allowlist.lock` and atomic replacement, but its enrollment/broker authority is not the requested native MCP authority. Do not expose its legacy host as the new API without independent native context verification.

## Windows handoff: smallest gated sequence

1. **Resolve quarantine first.** Original task `tsk_0bd717b5538149d78797d45e29abc4ec` was reported orphaned on resource `installation:7c82db6b-f6f2-4072-bd38-7ed763aa45d3`; subsequent Files tasks returned `RESOURCE_RECONCILIATION_REQUIRED`. Current recovery status is **NOT_RUN** here. Preserve and reconcile that original task through authorized recovery. Restart is not evidence of reconciliation. Do not delete journals, mark unknown work successful, change resource/idempotency keys or switch transport to evade the gate.
2. **Accept source independently.** In `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`, inspect branch/HEAD and local changes before pulling the parent's verified delivered commit. Preserve local work and resolve divergence; no reset/clean shortcut. No commit or push was performed by this documentation worker.
3. **Run integrated disposable fixtures.** After all source edits finish, run the implementation's exact focused Router/Files suites and combined gates. Require authentic native registration → strict schema → trusted context → selected-profile effect → consumer/readback evidence. Cover revoked/expired auth, denied tool/scope/profile, forged metadata, queued profile changes, stale revision, competing writer, invalid path, failed publication and unknown outcome. Linux fixture passes are not Windows ACL/reparse/publication acceptance.
4. **Build the launcher-selected artifact, not generic Release.** Both `src/Zagent.Launcher/LaunchPlan.cs:6` and the default in `packaging/scripts/Start-OwnerCore.ps1:39` select `src\Zagent.Core\bin\Debug\net10.0\Zagent.Core.exe`. After confirming the current launcher and approved portable SDK, the matching owner-local build command is:

   ```powershell
   & 'D:\3-Ikbalzohr\Agent\appBridge\toolchain\dotnet10\dotnet.exe' build 'D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform\src\Zagent.Core\Zagent.Core.csproj' -c Debug
   ```

   This command is guidance, **NOT_RUN**, and does not prove Python dependency readiness or update an already running process. Verify the selected EXE and companion payload/hash, the final Python source, configured environment and dependencies separately. Launcher source sets Files/Tunnel Python under `%LOCALAPPDATA%\Zagent-Envs\files` and `\tunnel`; do not install into a guessed system interpreter.
5. **Publish/reload only with owner authorization.** Preserve existing DataRoot/enrollment and Core supervision. No config, grant, service or restart action is authorized by this document. Use the existing approved lifecycle only after source/fixture acceptance; verify the selected running payload after any authorized restart. Refreshing a browser is not deploying a backend. Test list first; production add/remove is a separate explicit effect, not an authentication smoke test.
6. **Record actual acceptance.** Keep source commit, test results, selected binary hash, runtime version, native discovered tools, terminal task IDs and same-profile readback distinct. Redact bearer/refresh tokens, internal keys, private config and credentials. Do not print full policy just to prove one membership change.

## Portable client setup and acceptance

Chosen remote endpoint from the design: `https://zagent.ikbalzohr.web.id/mcp` over Streamable HTTP, OAuth authorization-code + PKCE S256; issuer `https://vmi3669591.contaboserver.net/realms/zagent`. Public discovery observations in the earlier profile handoff are historical evidence, not newly verified deployment or successful login.

Official docs describe standard remote MCP clients; no Hermes-specific protocol is needed:

| Surface | Connection route | Acceptance status here |
|---|---|---|
| ChatGPT web | Add a custom MCP server/plugin in the account's available UI, set HTTPS endpoint and OAuth. Product/workspace rollout and write-tool approval UI vary. | **NOT_RUN**; account entitlement, callback, login, list/call and writes unverified. |
| Codex CLI | Remote MCP configuration and its OAuth login route; not the same setup as ChatGPT web. | **NOT_RUN**; does not certify ChatGPT web. |
| Claude web/Desktop remote connector | Add custom remote connector, use OAuth. Hosted connector access comes from Anthropic infrastructure. | **NOT_RUN** for each application; do not confuse local Desktop stdio with remote connector support. |
| Claude Code | Remote HTTP MCP configuration; authenticate through `/mcp`. Local loopback OAuth callbacks differ from hosted Claude. | **NOT_RUN**; does not certify Claude web/Desktop. |
| Hermes native MCP | A standard remote MCP OAuth client, not an extra Zagent authorization service. | **NOT_RUN**; installed build/client behavior unverified. |

For each selected application independently: verify unauthenticated `401` with correct protected-resource metadata pointer; exact resource URL and issuer discovery; accepted client registration/pre-registration and exact displayed callback; PKCE code exchange and audience; initialize → initialized → tools/list → read-only tools/call; refresh and revocation; and denied scope/profile behavior. Only then exercise a separately authorized disposable mutation. Verify durable task retrieval works in that client; protocol support alone does not prove a model follows a multi-call job workflow.

DCR endpoint publication is not proof registration is accepted; CIMD, DCR and predefined client support depend on both client and issuer. Do not advertise unsupported CIMD, copy another application's redirect URI, allow wildcard redirects, put tokens in chat/config examples or replace user OAuth with a client-credentials workaround. Existing grants enumerating exact tool names may need legitimate deployment provisioning; this is not permission to bypass them or add a new feature-specific enrollment requirement.

### Official references

Reviewed official OpenAI auth and Claude auth/Code documentation during this task; remaining surface details derive from the earlier `MCP-FIRST-CLIENT-COMPATIBILITY.md` profile research and require live acceptance:

- OpenAI OAuth/resource/client registration: https://developers.openai.com/plugins/build/auth
- ChatGPT connection: https://developers.openai.com/plugins/deploy/connect-chatgpt
- Codex MCP: https://learn.chatgpt.com/docs/extend/mcp?surface=cli
- Claude connector authentication, discovery and callbacks: https://claude.com/docs/connectors/building/authentication
- Claude custom connectors: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Hermes MCP: https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp
- MCP authorization revision referenced by OpenAI docs: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

Client documentation is not evidence that the current Zagent issuer, native catalog or deployed Windows payload meets these contracts. All unexecuted client and target checks remain **NOT_RUN**.

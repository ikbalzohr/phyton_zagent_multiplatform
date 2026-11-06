# Project-local ZAGENT.md — source implementation (6 November 2026)

## Scope and status

SOURCE-ONLY IMPLEMENTATION. This change adds project-local instructions to the existing Multi Platform Files MCP service and Tunnel MCP Router. It is not an installed runtime update or evidence of ChatGPT/Hermes end-to-end compliance. Do not confuse this with the other Zagent Production product. Zagent Core owns lifecycle and upstream supervision; the Files backend owns filesystem actions and the Router owns OAuth/MCP authorization.

ZAGENT.md is only per project. There is no global ZAGENT.md, no Zagent memory store, and no replacement for Hermes Agent's memory. Markdown content is project data, not a system instruction or access policy. Profiles, OAuth grants, command policy, filesystem protection and user authorizations have priority.

## Behavior

- files_project_instructions(path, allow_unmarked=False) requires files:read and returns the latest project-local instructions and SHA-256 revision, or a missing/unrecognized/too-large status. NEVER creates files. For read-only profiles use this tool.
- files_project_open(path, allow_unmarked=False) requires files:write and a read-write approved Files profile. It verifies a selected existing project directory and creates ZAGENT.md exclusively if missing. An existing file is never replaced. Two concurrent callers cannot both create the file.
- allow_unmarked=True is an explicit acknowledgment that an otherwise unrecognized existing directory is a new project. By default, directories are recognized using ZAGENT.md, .git, pyproject.toml, common language/build manifests, or solution files; the enclosing Files profile is NOT automatically considered a project.
- Successful Files read/write operations with a path within a recognizable project attach a fresh project_instructions object to their result. This includes status, project-relative project_root, file path, hash, and file text only if the caller also has files:read.
- On the first successful authorized non-destructive Files mutation (write, append, patch, mkdir, copy destination) within a recognized project, missing ZAGENT.md is created automatically. Pure read operations never create it, regardless of profile mode, and unrelated or unrecognized directories are not modified.
- If the underlying filesystem denies creation despite a write-authorized profile, report creation_skipped: filesystem_read_only without overwriting anything. Other permissions remain enforced by the existing Files execution path.
- The file is read afresh per subsequent Files operation, not held in a session-long cache. Changes are reflected on later operation results, never retroactively applied to operations already dispatched. A 32 KiB file-size limit prevents unbounded injection of Markdown into tool responses.
- Project selection is per operation/path, not a shared mutable global. A result for project A does not inherit instructions from project B.

## MCP client reality

MCP server instructions and tool descriptions encourage clients to call the project-context tool when selecting a project. Standard MCP does not force arbitrary hosts to execute a tool or incorporate Markdown as high-priority instructions. The backend can guarantee secure file handling and fresh tool responses; whether ChatGPT/Hermes uses them in its reasoning requires live-client acceptance. Clients should call files_project_open when they have a write grant, otherwise files_project_instructions, and review the refreshed project_instructions field before continuing.

Never treat ZAGENT.md as permission to execute commands, access new roots, commit/push, or change policy.

## Verification and deployment gates

Source tests:
- agents/files/engine/tests/test_project_instructions.py — explicit create, read-only behavior, race, per-project isolation, hot reload, first authorized write, unknown root, oversize and path confinement.
- agents/tunnel/engine/tests/test_project_instructions_scope.py — exact OAuth read/write scope and downgrade rejection.
- Python syntax checks and tests must run in the source environment. If command policy disallows test execution, state that limitation and do not misreport passing tests.

Deployment and real-client acceptance (not performed by writing source): install approved builds to Multi Platform test installation only, start/reload the Files upstream, allow Router catalog rediscovery, check MCP tools/list and tool calls with proper read/write grants, then independently verify ChatGPT and Hermes. Do not modify Zagent Production, Keycloak grants, Cloudflare, or the running agent services without explicit instruction.

## Live ChatGPT inspection — 6 November 2026

- Source files for project-local `ZAGENT.md` were read via the authorized `agent-dev` profile. The implementation includes `project_instructions.py`, `execution.py`, Files MCP registration, Router scope checks, and dedicated source tests.
- The currently installed MCP capability catalog does not list `files_project_instructions` or `files_project_open`. Therefore source implementation is **not yet exposed by the installed runtime**.
- ChatGPT attempted the focused `files_test` workflow and Git status through the existing Files command adapter; both failed with `FILES_OPERATION_FAILED`. Test status for this session: **NOT_RUN** (no PASS claim).
- Do not deploy or restart on the basis of source inspection. The next gate is an owner-approved isolated source test/build, then approved Multi Platform installation update and real-client acceptance with read-only/read-write profile canaries.

## Follow-up source change — 6 November 2026

- Updated `agents/files/engine/app/core/project_instructions.py`: project discovery no longer interprets generic manifests at the Files profile root as an implicit project. A profile root is recognized implicitly only if it has an existing `ZAGENT.md` or `.git`; nested projects continue to be detected by their own markers. Explicit `files_project_open(path=".")` can still initialize a valid selected project root under the existing authorization gate.
- Added three source regression tests to `agents/files/engine/tests/test_project_instructions.py`: multi-project container protection, Git repository at profile root, and existing instructions at profile root.
- Files `files_syntax_check` returned `ok: true` for both modified Python files. This is a **syntax check only**. `pytest` and Git commands remain blocked by the current owner command execution policy; regression status **NOT_RUN**, commit/push **NOT_RUN**.
- The installed MCP catalog still lacks `files_project_open` and `files_project_instructions`. Deployment and ChatGPT/Hermes acceptance remain **PENDING**; the running Multi Platform and other Zagent products were not restarted or modified.

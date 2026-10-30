# Diagnostics: owner-local error tracking

## Purpose and boundaries

Diagnostics correlates failures reported by Core, the Router and Files with an opaque request ID. A responding dashboard or a running Core process does not prove that MCP initialization, OAuth validation, Files access or a durable task succeeded.

This feature is not a repair wizard. Reading or exporting diagnostics must not refresh OAuth, change grants, expand executable allowlists, restart agents, replay tasks, or change policy. Failures that happened before instrumentation was installed cannot be reconstructed unless another existing log already recorded them.

Instrumentation covers explicit application error boundaries, not every possible operating-system, browser, Cloudflare or third-party failure. Power loss, abrupt process termination and exceptions before initialization may prevent an event from being written. An empty event list is not a healthy-system assertion.

## Owner interface

The Core dashboard provides a Diagnostics view and an authenticated read/export API under `/api/management/v1/diagnostics`. Existing local-owner authentication, Administrator authorization, loopback HTTPS and browser protections still apply. The endpoint is not exposed as a public MCP tool.

Use the Diagnostics view to inspect recent events, narrow by component or severity, and find the request ID reported by an application error. Export only the bounded structured diagnostic report when sharing evidence. Never send raw configuration files, OAuth tokens, credentials or private command policies.

## Structured event contract

Components share version 1 records:

- `version`: integer `1`.
- `timestampUtc`: UTC timestamp.
- `requestId`: application-generated lowercase UUID hex (32 characters), not a trusted client header.
- `component`: `core`, `router` or `files`.
- `stage`: a bounded application-defined stage label.
- `code`: an allowlisted diagnostic category.
- `severity`: `info`, `warning` or `error`.
- `message`: a curated safe hint, never the exception's message or stack trace.

The reader validates records and reconstructs hints from trusted code. It must not blindly return an arbitrary `message` found in a log file. Authentication headers, request bodies, user-provided paths, account identifiers, credential payloads and policy preimages do not belong in these records.

Under the existing Core DataRoot, component files are:

```text
logs/diagnostics/core.jsonl
logs/diagnostics/router.jsonl
logs/diagnostics/files.jsonl
```

Rotation bounds each active file to approximately 1 MiB plus one rotated sibling (`.jsonl.1`). Reports have their own bounded read and result budgets; they are not arbitrary file downloads. Missing, malformed, unavailable or rejected sources must be distinguishable from successfully read sources containing no events. Diagnostic I/O failures must not override an authorization decision or make a failed operation succeed.

## Investigating an MCP failure

1. Distinguish the actual configured bind address from an assumed localhost address. In this installation the Router was observed listening on `127.0.0.3:18810`; `127.0.0.1:18810` was not an equivalent probe.
2. A GET response of HTTP 405 with `Allow: POST` proves an HTTP route responded, not that MCP initialized.
3. Inspect the JSON-RPC response body. HTTP 200 with an `error` object is a failed MCP request.
4. Look up the returned request ID in Diagnostics, when that boundary supplies one. Otherwise inspect the newest events around the request time and component; do not invent an ID or claim correlation from time alone.
5. Separate authentication, current grant/capability checks, catalog retrieval, upstream transport, and operation execution. An expired token is not proof that native refresh is unusable. A local Router error is not automatically a Cloudflare error.
6. For uncertain durable tasks, retain the original task/operation ID and query that exact task. Diagnostics is not permission to resubmit a mutation.

## Source delivery and Windows activation

Pulling source does not replace a running Core binary or reload Python modules already imported by a process. Build/publish and owner-controlled activation on Windows are separate acceptance gates.

Before pulling, inspect the Windows checkout:

```powershell
git status --short
```

Previous development through Files MCP may have left uncommitted Router/Files/allowlist changes. Do not run `git reset --hard`, `git clean`, overwrite those changes, or discard them merely to make a pull succeed. Reconcile overlapping changes explicitly. If the working tree is clean, use a fast-forward-only pull from the actual configured upstream.

Use the owner's selected portable .NET SDK for Windows builds. Do not start an alternative standalone Router or Files server to avoid the Core-managed lifecycle. Installing or rebuilding the dashboard does not enroll remote allowlist administration or change its readiness gates.

## Bounded storage and current limitations

- The Core reader allocates at most 2 MiB plus a one-byte growth sentinel per file, rejects over-budget files and returns at most 500 events. Router and Files rotate before the next event would exceed 1 MiB. Core rotates on the following write after reaching 1 MiB, so one small static record can exceed that threshold.
- On a failed dashboard refresh, the global freshness indicator changes to offline/unavailable. The Diagnostics-local summary may still describe the last successful report; check its capture time and global freshness before interpreting it as current.
- Python components without an explicit Core DataRoot, or unable to write it, retain at most 64 events in process memory and emit a static storage-unavailable warning. That fallback is not a persistent report and is lost when the process exits.
- Writes are best effort, not a transaction journal. Existing symlinks/reparse paths are rejected, but these checks are not a sandbox against a hostile process already running as the same Windows owner or Unix root.

## Verification levels

A passing VPS build and isolated fixture prove source compilation and the tested application behavior on that host. They do not prove Windows ACL inheritance, an existing enrolled dashboard login, the displayed browser page, the running production Router, or live Windows process supervision. Record those as separate target acceptance checks after owner-controlled deployment.

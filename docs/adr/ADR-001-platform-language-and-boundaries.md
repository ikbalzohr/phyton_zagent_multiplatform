# ADR-001 — Platform Language and Boundaries
Status: Accepted

Zagent uses a polyglot architecture. C#/.NET owns the Windows control plane, Manager, local IPC, lifecycle, installer-facing integration and process ownership. Python remains valid for Files/Tunnel/ArcMap domain code; TypeScript/Node remains valid for Web/Chrome automation.

Reason: rewrite only where architecture benefits. Stable domain logic is migrated behind a common protocol instead of rewritten merely for language uniformity.

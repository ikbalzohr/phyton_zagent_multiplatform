# ADR-002 — Single Lifecycle Owner
Status: Accepted

Zagent Core is the only authoritative owner of Zagent child-process lifecycle. UI and agents request lifecycle actions through Core and never independently spawn/kill peer agents.

Core uses native Windows process identity, Job Objects where compatible, global/per-agent locking, graceful shutdown, bounded timeout, force-kill fallback and desired-state tracking. This directly addresses Zagent v1 orphan/overlap problems.

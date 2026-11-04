# Owner-managed parent-root Files profiles — 4 November 2026

## Problem and resolution
The user requested root D:\3-Ikbalzohr\Agent for the agent Files
profile in read-only mode. The prior PRIVATE_ROOT_OVERLAP rule denied
any ancestor containing private Zagent stores. Dashboard reported
503 RESPONSE_VALIDATION when the rejected profile was submitted.

The source and the installed Multi Platform now permit an existing,
owner-approved absolute Windows ancestor as a profile root, regardless
of read-only/read-write mode. Authentication, owner grant, profile
approval, reparse protection, generation/revision, idempotency and
file-mode checks remain unchanged.

The per-file Files target guard denies direct access to service-private
Core/Files data, config, runtime, logs and backups, even through an
approved ancestor profile. Secret name protection also remains. This is
not a blanket exemption for private credentials. Bulk recursive tools
over a parent containing private stores can still fail closed; skip/
prune improvements were not deployed or claimed as tested. The generic
503 rendering for *other* rejected paths was not separately fixed.

## Deployment and verification
- Modified and installed two Files engine files:
  agents/files/engine/app/profiles/administration.py and
  agents/files/engine/app/core/fsops.py.
- Stopped and started only files.service via authenticated owner Core
  Dashboard lifecycle. Did not restart Core, Router, Web, ArcMap or QGIS.
  No Zagent Production changes or new backup archive.
- Updated installed payload manifest. Setup verify 12001/12001 PASS,
  FilesChanged=0 and BackupRoot=null.
- Source Windows profile CRUD/owner/idempotency fixture PASS.
- Isolated Windows Router/Files profile regression 14/14 PASS.
- Router Python unit suite 173 tests, 3 SKIP, others PASS.
- Dashboard committed a new profile named agent at exact root
  D:\3-Ikbalzohr\Agent, read-only and enabled, with committed access
  synchronization. Existing appBridge and projectMapping retained,
  and appBridge remains the active/default profile.
- Live authenticated ChatGPT Files list and ordinary README read using
  profile_id=agent both succeeded. Attempts to stat private tunnel
  config or write a harmless file via read-only profile were denied;
  the probe write file does not exist.
- Final installed Core/Router/Files/Web/ArcMap/QGIS ports were listening,
  and source/install hashes for the two Files files matched.

## Git and outstanding issues
Changes to source tests and docs remain uncommitted; no commit/push was
requested for this turn. Previously existing dirty tests/docs and
artifacts were preserved. Direct parent root registration now succeeds;
bulk tree/search over protected areas and generic error representation
for other invalid targets are separate issues.
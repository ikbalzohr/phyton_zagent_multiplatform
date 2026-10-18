# ArcMap Smart Corner Digitizer v1 — Developer Handoff
Date: 2026-10-08 (Asia/Makassar)
Status: DESIGN REGISTERED; NOT IMPLEMENTED, NOT TESTED, NOT DEPLOYED.

Canonical local-memory spec:
D:\3-Ikbalzohr\Agent\appBridge\memori\projects\ZAGENT_ARCMAP_SMART_CORNER_DIGITIZER_PLAN_20261008.md

Unified pending update register:
D:\3-Ikbalzohr\Agent\appBridge\memori\projects\ZAGENT_V3_PENDING_UPDATE_REGISTER_20261008.md

Machine-readable checkpoint:
D:\3-Ikbalzohr\Agent\appBridge\memori\checkpoints\zagent_arcmap_smart_corner_design_20261008.json

## Critical lesson
Previous procedure used FeatureVerticesToPoints ALL and inserted 109 unique original polygon vertices into PT_WCL_PT. Geometrically each point coincided exactly with a polygon vertex and the order was clockwise, but the user rejected the result: many vertices did not form meaningful corners. DO NOT treat all vertices as corners. Current target may contain the rejected 109 points. No replacement is authorized by this planning record.

## Implementation requirement
Pure geometry: closed ring normalization, signed area orientation, local turn angle, perpendicular chord offset, small-segment/noise policy, visually reviewable reason codes, preserving the original vertex coordinates. Output candidates with deterministic clockwise sequence and user-selected/automatic start anchor. Preview/dry-run FIRST; do not write to source polygon or existing point layer while preparing preview. Avoid centroid polar-angle sorting on concave boundary.

A 45-degree turning threshold is only an initial tuneable preview parameter. No claim that it correctly identifies PT WCL corner count without reviewed ground truth.

Backend safety: nonempty target guard, full shapefile backup/rollback, no double append on retry, source fingerprint and stale preview detection, identity/device/operator enforcement, CURRENT MXD owner, no implicit MXD save. Existing ArcMap bridge Python 2.7 compatibility and MCP service Python 3 separation must be preserved.

Reference phase IDs: SCD-00..SCD-10 and gates G1..G10 in the canonical spec. The source tree is v3 only. All source-level changes, unit tests, Dev live testing, install, restart and promotion are **different milestones**. This document itself implements no new functions.

## Integration with other pending work
- Native Layer Properties, Edit Existing Grid/Graticule and Vision vertical flip: docs/ARCMAP_NATIVE_PROPERTIES_GRIDS_VISION_20261008.md
- Master/User installation isolation: docs/ZAGENT_V3_MASTER_USER_INSTALLATION_20261008.md
- Zagen ArcMap Orchestrator integration: read unified register, then audit source current status (older master plan may be stale).
- Exact update queue/status is in canonical unified pending update register, not in this reminder document.

## Recall instruction
When the user says "implement all updates" in Zagent v3, read the unified register, reconcile source/checkpoints, run only authorized phases and verification gates. Do not modify external WCL shapefiles or save MXD unless specifically ordered.

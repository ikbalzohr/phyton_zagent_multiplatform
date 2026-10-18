# Zagent v2 — Feature Parity Matrix (Phase 0 Draft)

Status legend: **FROZEN** = source/reference secured; **REQUIRED** = must exist in Zagent; **DEV** = will be integrated through Development Gateway; **NORMALIZE** = legacy behavior/version must be standardized.

| Source capability | Zagent owner | Requirement | Phase 0 status |
|---|---|---:|---|
| Plugin transport / routing | Zagent Tunnel/Core | REQUIRED | FROZEN |
| Router health/status | Zagent Core/Tunnel | REQUIRED | FROZEN |
| Multi-chat stable identity | Zagent Core | REQUIRED | FROZEN |
| Chat alias/work title | Zagent Manager/Core | REQUIRED | FROZEN |
| Persistent task journal | Zagent Core/Tunnel | REQUIRED | FROZEN |
| Fast-path + async task path | Zagent Core/Tunnel | REQUIRED | FROZEN |
| Priority scheduling / fast lane | Zagent Core/Tunnel | REQUIRED | FROZEN |
| Resource locking | Zagent Core + agent contract | REQUIRED | FROZEN |
| Task cancellation | Zagent Core + agents | REQUIRED | FROZEN |
| Recovery / idempotency | Zagent Core/Tunnel | REQUIRED | FROZEN |
| Files read/write/list/tree/search/hash/diff | Zagent Files | REQUIRED | FROZEN |
| Files profiles + approvals | Zagent Files/Core | REQUIRED | FROZEN |
| Cross-profile operations | Zagent Files | REQUIRED | FROZEN |
| Command execution layer | Zagent Files | REQUIRED | FROZEN |
| PowerShell/exec/Node/npm/npx/Git/build/test | Zagent Files | REQUIRED | FROZEN |
| Cooperative subprocess-tree cancel | Zagent Files/Core | REQUIRED | FROZEN |
| Files self-update behavior | Zagent Update subsystem | REQUIRED, redesign | FROZEN |
| Browser automation / Playwright | Zagent Web | REQUIRED | FROZEN |
| Native Chrome attach | Zagent Web | REQUIRED | FROZEN |
| Chrome Bridge pairing/approval | Zagent Web | REQUIRED | FROZEN |
| Persistent browser profiles | Zagent Web | REQUIRED | FROZEN |
| Multi-chat browser sessions | Zagent Web/Core | REQUIRED | FROZEN |
| Dashboard + agent lifecycle controls | Zagent Manager | REQUIRED | FROZEN |
| Monitoring active/recent tasks | Zagent Manager/Core | REQUIRED | FROZEN |
| Per-task STOP | Zagent Manager/Core | REQUIRED | FROZEN |
| Technical Logs | Zagent Manager/Core | REQUIRED | FROZEN |
| Human-friendly Log Chat | Zagent Manager/Core | REQUIRED | FROZEN |
| Multi-chat Log Chat columns | Zagent Manager | REQUIRED | FROZEN |
| Notifications / approval alerts | Zagent Manager | REQUIRED | FROZEN |
| ArcMap current-map inspection | Zagent ArcMap | REQUIRED | FROZEN / NORMALIZE |
| ArcMap layers/layout/labels/symbology | Zagent ArcMap | REQUIRED | FROZEN / NORMALIZE |
| ArcMap geoprocessing | Zagent ArcMap | REQUIRED | FROZEN / NORMALIZE |
| ArcMap checkpoint / QA / export | Zagent ArcMap | REQUIRED | FROZEN / NORMALIZE |
| ArcMap profiles/recipes | Zagent ArcMap | REQUIRED | FROZEN / NORMALIZE |
| Exclusive ArcMap Desktop ownership | Zagent Core/ArcMap | REQUIRED | DESIGN LOCKED |
| Capability Registry | Zagent Core | REQUIRED NEW | DESIGN LOCKED |
| DEVELOPMENT/STAGING/PRODUCTION registry states | Zagent Core | REQUIRED NEW | DESIGN LOCKED |
| Development Gateway 18900-18999 | Zagent Core | REQUIRED NEW | DESIGN LOCKED |
| Native .NET lifecycle supervisor | Zagent Core | REQUIRED NEW | DESIGN LOCKED |
| Installer repair/upgrade/rollback | Zagent Setup | REQUIRED NEW | DESIGN LOCKED |

## Rule
Zagent v1 is not the code foundation. It is only a prototype/lessons-learned reference. The latest Zohr System agents are the capability reference; Zagent v2 is a clean architecture implementation.

# Zagent v3 — Master / User Installation Isolation

> HISTORICAL / SUPERSEDED untuk produk MCP v1. Dokumen ini menyimpan konteks baseline, bukan routing/approval/instalasi aktif. Gunakan [runbook v1](RELEASE-V1.md); UI hanya dashboard web Core dan semua produk termasuk Files versi 1.0.0.
Date: 2026-10-08
Status: SOURCE UPDATED / NOT BUILT / NOT TESTED / NOT INSTALLED
Source: D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3
Production installation: unchanged.

## Product identity
- MASTER: Zagent Master, operator Ikbal, technical plugin audience zagent-production.
- USER: Zagent User, operator Harry, technical plugin audience tryplugin.
- Installation role is different from operator alias/device ID/tunnel ID.
- New installs set alias to Ikbal/Harry. Existing aliases stay unchanged.
- New default install folders: Zagent Master and Zagent User. An explicitly selected legacy install root remains in place.

## Reserved network ranges
| Component | Master | User |
|---|---:|---:|
| Core reserved | 18800 | 19100 |
| Tunnel router | 18810 | 19110 |
| Tunnel health | 18811 | 19111 |
| Files | 18820 | 19120 |
| Web and Chrome Bridge | 18830 | 19130 |
| ArcMap MCP | 18840 | 19140 |
| Production allocation | 18800–18899 | 19100–19199 |
| Development Gateway | 18900–18999 | 19200–19299 |
| Dev runtime allocation | 19000–19099 | 19300–19399 |

A port fallback is allowed only inside the same installation role's assigned range. The machine configuration validates this. Tunnel and ArcMap workflow clients receive their own instance's URLs, and automatic Chrome legacy endpoint fallback to other environments is disabled.

## Isolation beyond ports
- Manager named pipes: Zagent.Manager.Master.v1 / Zagent.Manager.User.v1.
- Supervisor leases: Local\Zagent.Master.Supervisor.v3 / Local\Zagent.User.Supervisor.v3.
- Machine configuration, workspace, state, logs, device identity, ArcMap IPC, Web and Files data live under the selected installation's root/data.
- Plugin approval state: %LOCALAPPDATA%\Zagent\<Role>\PluginAccess.
- Transport credentials: %LOCALAPPDATA%\Zagent\<Role>\Credentials\production.
- Windows Installed Apps entries, Manager shortcuts and uninstall caches have role-specific names/paths.
- Old global credentials or approval data are not silently copied between roles.

## Install/upgrade
1. In the bundled installer choose Zagent Master — Ikbal or Zagent User — Harry.
2. Fresh install targets <base>\Zagent Master or <base>\Zagent User.
3. For in-place upgrade, explicitly choose the existing installation root. Never automatically move folders, regenerate existing identities or remove data.
4. Upgrade can reallocate old role ports only through an explicit install initializer; unrelated running installations are not changed.
5. Existing installations with old global credentials or Chrome pairing may require reviewed reauthorization and Bridge re-pairing.

## Not performed — release gates
- No build, syntax verification, unit/integration tests, installer bundle, or runtime restart.
- Before release, verify Master and User installation and upgrade flows, all bound ports, identity/operator binding, Manager pipes, supervisor lease, credential and plugin approval separation, browser/ArcMap isolation, installer uninstall entries and regression.
- The intended primary deployment is one instance on Ikbal's laptop and one on Harry's laptop. Same-Windows-user concurrent ArcMap COM/Chrome instances require separate ownership acceptance before being supported.

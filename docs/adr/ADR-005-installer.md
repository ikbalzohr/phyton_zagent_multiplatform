# ADR-005 — Installer
Status: Accepted with toolchain prerequisite

Preferred stack: WiX Toolset v7 + Burn bootstrapper + custom .NET/WPF UX.

Required behavior: user-selected base folder, real progress, preflight, staged extraction, integrity verification, rollback, repair, upgrade, reinstall, uninstall, keep/delete-data option and Installed Apps registration.

Installer technology is replaceable and must not leak assumptions into Zagent Core.

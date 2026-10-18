# Zagent v1 — Lessons Learned Reference

Status: Reference only. Not a code foundation for v2.

## Confirmed implementation constraints
- Installer and uninstaller derive install root from `Environment.SpecialFolder.ProgramFiles`.
- Manager directly invokes `powershell.exe`.
- Lifecycle depends on `scripts\zagent-supervisor.ps1`.
- Manager has close-time Stop All logic, but v1 still required multiple lifecycle hotfixes on clean machines.

## What v2 may reuse
- User-facing feature concepts.
- Manager interaction patterns that proved useful.
- Known clean-PC failure cases and regression tests.
- Stable domain behavior from current Zohr agents, after capability/contract adaptation.

## What v2 must not inherit as architecture
- Hard-coded Program Files / ProgramData assumptions.
- PowerShell as the primary lifecycle owner.
- UI-owned or overlapping process lifecycle.
- Recovery runners that can race explicit Start/Stop.
- Environment-dependent global Python/Node assumptions.
- Version identity derived from README text.

## Rule
When a v1 feature is ported, port the capability and acceptance behavior, not the v1 implementation by default.

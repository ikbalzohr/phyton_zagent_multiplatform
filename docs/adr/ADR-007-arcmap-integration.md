# ADR-007 — ArcMap Integration
Status: Accepted

Zagent bundles ArcMap Agent/Bridge, not ArcMap 10.6.1. ArcMap Desktop is an external dependency.

ArcMap health is multi-state: package installed, agent online, ArcMap Desktop detected, bridge connected, tunnel route registered. Absence of ArcMap Desktop must not fail the whole Zagent platform.

ArcMap control uses exclusive ownership per ArcMap Desktop session.

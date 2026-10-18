# ADR-003 — Capability Registry and Development Gateway
Status: Accepted

Every agent registers through Agent Protocol v1. Capabilities, permissions, lifecycle, health, runtime and environment are explicit registry data. New agents enter DEVELOPMENT through port range 18900-18999 and cannot become production routes without promotion gates.

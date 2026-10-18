# ADR-004 — Path Topology
Status: Accepted

Developer machine base: D:\3-Ikbalzohr\Agent

DEV source: D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v2
Installed production: D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent\v2
Default Files workspace/profile: D:\3-Ikbalzohr\Agent\appBridge

After migration, only appBridge and ZohrSystem are intended as top-level folders beneath the base. Installer must derive paths from the selected base and persist the actual installation manifest.

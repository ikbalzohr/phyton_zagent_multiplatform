# Zagent Development Gateway Contract v1

## Purpose
Development Gateway is the mandatory isolation lane for new or modified agents before production registration.

## Network policy
- Development range: **18900-18999**.
- Default bind is loopback only.
- A port is allocated only after conflict preflight.
- An agent may not self-assign a production route.
- Core records port ownership by agent_id + process identity.
- Losing process ownership invalidates the lease.

## Registration states
DISCOVERED -> VALIDATING -> REGISTERED

Failure at any gate:
DISCOVERED/VALIDATING -> QUARANTINED

Manual disable:
REGISTERED -> DISABLED

## Minimum admission
An agent must provide an Agent Protocol v1 manifest and pass:
1. schema validation;
2. startup and bounded shutdown;
3. health/ready probe;
4. capability discovery;
5. permission/approval declaration;
6. resource-lock declaration;
7. port/path isolation;
8. crash and restart test;
9. cancellation semantics where advertised;
10. no orphan process after Core stop.

## Promotion
DEVELOPMENT -> STAGING -> PRODUCTION is explicit. Promotion never occurs only because the agent is online.

Production approval requires:
- stable version identity;
- source/build fingerprint;
- contract test PASS;
- integration test PASS;
- concurrency/resource test PASS;
- recovery test PASS;
- security/path boundary PASS;
- upgrade/rollback compatibility declared.

## ArcMap special rule
ArcMap Agent may be registered in DEVELOPMENT while ArcMap Desktop is absent. Health must distinguish AGENT_READY from ARCMAP_DESKTOP_NOT_DETECTED and BRIDGE_NOT_CONNECTED. Only one registered controller may own the same ArcMap Desktop session.

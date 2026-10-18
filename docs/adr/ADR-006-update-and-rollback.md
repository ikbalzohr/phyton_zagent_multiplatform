# ADR-006 — Update and Rollback
Status: Accepted

Updates are staged and verified before activation. Configuration/state migration is explicit. Failed activation reverts to the previous known-good component set. Running production must never execute from the development tree. Component versions and fingerprints come from component-manifest.json / installed manifest, not README text.

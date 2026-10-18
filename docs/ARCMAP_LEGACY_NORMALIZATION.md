# ArcMap Legacy Source Normalization

## Frozen source identity
Canonical import ID: **arcmap-legacy-20260926**

This identity deliberately replaces ambiguous legacy version labels for migration purposes.

## Legacy labels found
- `VERSION`: 0.1.1-integration-safe
- `README.md`: Stage 2 Full Production Pack v2.0.0
- `BUILD_INFO.json`: 2.1.0
- `BUILD_INFO.json`: expected MCP tools 99
- `BUILD_MANIFEST.json`: public MCP tool count 33

None of those labels is treated as the canonical Zagent ArcMap version.

## Zagent rule
The first ArcMap Agent adapted to Agent Protocol v1 will receive a new Zagent-controlled version identity. The frozen legacy source remains immutable reference input.

ArcMap 10.6.1 remains an external dependency and is never bundled by Zagent.

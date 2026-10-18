# Zagent ArcMap 3.0.1-zagent.1

ArcMap integration module for Zagent.

- MCP runtime: Python 3.11
- External desktop runtime: ArcMap Desktop 10.6.1 / Python 2.7
- Runtime-verified tools: 123
- Stage 2 tools: 8
- Stage 3 tools: 20
- Default production export: PDF + PNG, 400 DPI
- Default output folder: Hasil Peta
- Naming: PETA A4 <nama perusahaan> – <jenis peta>
- ArcMap Desktop remains external and is never owned/killed by Zagent Core.
- A single ArcMap session may have only one active agent bridge.
- Mutable config, IPC, logs, checkpoints, and style state live outside the engine source under the Zagent ArcMap data root.

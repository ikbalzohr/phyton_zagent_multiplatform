# Zagent v2 Developer Toolchain

Audit date: 2026-09-26

## Available
- Node.js 24.19.0
- npm 10.9.0
- Git 2.47.0.windows.1
- Windows SDK
- SignTool (inside Windows SDK; not currently on PATH)
- .NET runtimes 6.0 and 8.0

## Missing — required before relevant implementation
1. **.NET 10 SDK** — required before Phase 1 C#/.NET Core/Manager development and compile validation.
2. **WiX Toolset v7** — required before Phase 9 installer implementation/build.

## Important environment rule
Global `python` currently resolves to Python 2.7.5. Zagent must not use global Python for modern services. Python agents must use a bundled/managed modern Python runtime with explicit executable paths.

Do not start uncompiled C# implementation merely to save time. Install the SDK first so every code increment can compile/test immediately.

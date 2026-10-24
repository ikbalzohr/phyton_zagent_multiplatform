# Recovery of ArcMap artifact source

Recovered `agents/arcmap/engine/orchestrator/artifacts/{__init__,publisher,validation}.py` from the owner's original Windows installation `D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3\agents\arcmap\engine\orchestrator\artifacts`, provided as a three-source-file archive. Restored bytes are unchanged; no generated map, credential or binary is included.

SHA-256:
- __init__.py: 3303adaec24c6fb5c4d7e66c4bbbdcedc43b7e9201205dc6810bdcd457d97f2d
- publisher.py: b70ad166321b5d00e241c3764a2c01b5a9cb82bcf404ec33c1a05dde7aee871a
- validation.py: f689bd6f05d52cc043f0bce4c7edcff290874f666dbf122d809e0c21d125b910

The whole source package had been excluded by .gitignore. The corrected rule admits Python source only; generated artifacts remain ignored. `python dev/check_router_import_sources.py` checks the local source import graph using AST, including deferred executor imports. It does not execute the product or prove third-party dependency availability, Windows startup or ArcMap operation.

The startup guard keeps missing artifact execution explicitly blocked rather than synthesizing a Publisher. With this recovered package present, that missing-source blocker is absent; workflow authorization, strategy policy and other runtime checks remain applicable.

Recovery is not a security certification of the legacy publisher. Its validation checks signatures/dimensions and declared DPI rather than fully parsing documents, and its collision/copy behavior needs isolated Windows tests before publication is enabled. Do not enable production export/write strategies merely because router import succeeds.

"""Zagent ArcMap goal orchestrator domain package.

The orchestrator runs in the Python 3 MCP process. It never imports ArcPy or
ArcObjects; live ArcMap access stays behind JSON-compatible adapters.
"""
ORCHESTRATOR_SCHEMA_VERSION = "2.0"

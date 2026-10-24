from __future__ import annotations

import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

from app.paths import LOG_DIR
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "mcp_runtime.log"


def _windows_batch_wrap(executable: str, args: list[str]) -> tuple[str, list[str]]:
    lower = executable.lower()
    if os.name == "nt" and lower.endswith((".cmd", ".bat")):
        cmd = shutil.which("cmd.exe") or "cmd.exe"
        return cmd, ["/d", "/c", "call", executable, *args]
    return executable, args


with LOG_FILE.open("a", encoding="utf-8", buffering=1) as log:
    sys.stdout = log
    sys.stderr = log
    print("\n" + "=" * 72)
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] Zagent Files 1.0.0 MCP boot")
    try:
        from app.mcp import server
        from app.mcp import command_tools

        command_tools._windows_batch_wrap = _windows_batch_wrap
        command_tools.register_command_tools(server.mcp)

        print(f"Loaded server.py from: {Path(server.__file__).resolve()}")
        print(f"Configured endpoint: http://{server.HOST}:{server.PORT}/mcp")
        print("Command Execution Layer: registered; explicit local owner policy required")
        server.mcp.run(transport="streamable-http")
    except BaseException:
        print("FATAL MCP STARTUP ERROR")
        traceback.print_exc()
        raise

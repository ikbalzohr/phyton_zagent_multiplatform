from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
RUNTIME_DIR.mkdir(exist_ok=True)
PID_FILE = RUNTIME_DIR / "router.pid"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class RouterRuntime:
    def __init__(self, cfg: dict, log_callback: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.log_callback = log_callback or (lambda _: None)

    def router_cfg(self) -> dict:
        return self.cfg.get("router", {})

    def health_url(self) -> str:
        cfg = self.router_cfg()
        return f"http://{cfg.get('host','127.0.0.1')}:{cfg.get('port',8016)}/healthz"

    def mcp_url(self) -> str:
        cfg = self.router_cfg()
        return (
            f"http://{cfg.get('host','127.0.0.1')}:{cfg.get('port',8016)}"
            f"{cfg.get('mcp_path','/mcp')}"
        )

    def health_ready(self) -> bool:
        try:
            with urlopen(self.health_url(), timeout=0.7) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    def owned_process_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _read_pid(self) -> int | None:
        try:
            return int(PID_FILE.read_text(encoding="utf-8").strip())
        except Exception:
            return None

    def _write_pid(self, pid: int) -> None:
        PID_FILE.write_text(str(pid), encoding="utf-8")

    def _clear_pid(self) -> None:
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass

    def running(self) -> bool:
        return self.health_ready() or self.owned_process_running()

    def start(self) -> None:
        if self.health_ready():
            self.log_callback("[ROUTER] sudah RUNNING / READY")
            return
        if self.owned_process_running():
            self.log_callback("[ROUTER] proses sedang start")
            return

        py = ROOT / ".venv" / "Scripts" / "python.exe"
        exe = str(py if py.exists() else Path(sys.executable))
        self.proc = subprocess.Popen(
            [exe, "-m", "router.server"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        self._write_pid(self.proc.pid)
        self.log_callback(f"[ROUTER] start -> {self.mcp_url()}")

    def wait_ready(self, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.health_ready():
                return True
            if self.proc is not None and self.proc.poll() is not None:
                return False
            time.sleep(0.2)
        return self.health_ready()

    def stop(self) -> None:
        pid = self.proc.pid if self.owned_process_running() else self._read_pid()

        if self.owned_process_running():
            assert self.proc is not None
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
            self.log_callback(f"[ROUTER] stopped exit={self.proc.returncode}")
            self.proc = None
            self._clear_pid()
            return

        if pid:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                self.log_callback(f"[ROUTER] stopped PID={pid}")
            else:
                self.log_callback("[ROUTER] PID lama sudah tidak aktif")
            self._clear_pid()
            return

        if self.health_ready():
            self.log_callback(
                "[ROUTER] masih aktif tetapi PID tidak tercatat. Tutup proses Python pemilik port 8015 secara manual."
            )
            return

        self.log_callback("[ROUTER] tidak sedang berjalan")
        self._clear_pid()

    def attach_log_reader(self, callback: Callable[[str], None]) -> None:
        if not self.proc or not self.proc.stdout:
            return

        def reader() -> None:
            log_path = ROOT / "logs" / "router.log"
            with log_path.open("a", encoding="utf-8") as f:
                for line in self.proc.stdout:
                    f.write(line)
                    f.flush()
                    callback("[ROUTER] " + line.rstrip())

        import threading
        threading.Thread(target=reader, daemon=True).start()

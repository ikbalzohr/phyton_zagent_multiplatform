from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


ENGINE_ROOT = _env_path(
    "ZAGENT_FILES_ENGINE_ROOT",
    Path(__file__).resolve().parents[1],
)
DATA_ROOT = _env_path(
    "ZAGENT_FILES_DATA_ROOT",
    ENGINE_ROOT / "data",
)
CONFIG_DIR = _env_path(
    "ZAGENT_FILES_CONFIG_DIR",
    DATA_ROOT / "config",
)
RUNTIME_DIR = _env_path(
    "ZAGENT_FILES_RUNTIME_DIR",
    DATA_ROOT / "runtime",
)
LOG_DIR = _env_path(
    "ZAGENT_FILES_LOG_DIR",
    DATA_ROOT / "logs",
)
BACKUP_ROOT = _env_path(
    "ZAGENT_FILES_BACKUP_ROOT",
    RUNTIME_DIR / "backups",
)
UPDATE_STATE_ROOT = _env_path(
    "ZAGENT_FILES_UPDATE_STATE_ROOT",
    DATA_ROOT / "updates",
)

for directory in (
    DATA_ROOT,
    CONFIG_DIR,
    RUNTIME_DIR,
    LOG_DIR,
    BACKUP_ROOT,
    UPDATE_STATE_ROOT,
):
    directory.mkdir(parents=True, exist_ok=True)

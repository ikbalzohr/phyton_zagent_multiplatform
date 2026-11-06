"""Run managed command fixtures with disposable config, only on owner Windows."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.name != 'nt':
        raise SystemExit('NOT_RUN: Windows owner interpreter required')
    engine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(engine))
    with tempfile.TemporaryDirectory(prefix='zagent-managed-command-tests-') as directory:
        base = Path(directory)
        mapping = {
            'ZAGENT_FILES_DATA_ROOT': base,
            'ZAGENT_FILES_CONFIG_DIR': base / 'config',
            'ZAGENT_FILES_RUNTIME_DIR': base / 'runtime',
            'ZAGENT_FILES_LOG_DIR': base / 'logs',
            'ZAGENT_FILES_BACKUP_ROOT': base / 'backups',
            'ZAGENT_FILES_UPDATE_STATE_ROOT': base / 'updates',
        }
        previous = {key: os.environ.get(key) for key in mapping}
        try:
            for key, path in mapping.items():
                path.mkdir(parents=True, exist_ok=True)
                os.environ[key] = str(path)
            import pytest
            return pytest.main(['-q', str(engine / 'tests/test_managed_commands_windows.py'),
                                str(engine / 'tests/test_profile_execution_access_windows.py')])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == '__main__':
    raise SystemExit(main())

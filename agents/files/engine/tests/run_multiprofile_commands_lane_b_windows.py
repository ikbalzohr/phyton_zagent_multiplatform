"""Disposable Windows-only entrypoint for Lane B multi-profile command tests."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.name != 'nt':
        raise SystemExit('NOT_RUN: Windows owner interpreter required')
    engine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(engine))
    with tempfile.TemporaryDirectory(prefix='zagent-lane-b-multiprofile-') as directory:
        base = Path(directory)
        mapping = {
            'ZAGENT_COMMAND_MULTIPROFILE_FIXTURE_ROOT': base,
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
            # Environment isolation precedes all pytest/product imports.
            import pytest
            return pytest.main(['-q', '-p', 'no:cacheprovider', '--basetemp', str(base / 'pytest'), str(engine / 'tests/test_multiprofile_commands_lane_b_windows.py')])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == '__main__':
    raise SystemExit(main())

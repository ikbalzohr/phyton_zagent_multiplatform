"""Owner Windows-only fixture runner. No real owner configuration is used."""
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.name != 'nt':
        raise SystemExit('NOT_RUN: Windows owner interpreter required')
    engine = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(engine))
    with tempfile.TemporaryDirectory(prefix='zagent-consumer-authority-') as directory:
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
            (base / 'config/settings.json').write_text(json.dumps(dict(host='127.0.0.1', port=8011,
                max_read_bytes=10485760, max_write_bytes=52428800, secret_names=['.env'])), encoding='utf-8')
            (base / 'config/profiles.json').write_text(json.dumps(dict(active_profile=None, profiles=[])), encoding='utf-8')
            import pytest
            return pytest.main(['-q', str(engine / 'tests/test_execution_context.py'),
                                str(engine / 'tests/test_consumer_authority_windows.py')])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == '__main__':
    raise SystemExit(main())

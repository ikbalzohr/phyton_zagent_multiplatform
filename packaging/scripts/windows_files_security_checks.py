"""Run focused Windows security fixtures in disposable configuration directories.

Not a product launcher; never points tests at the real owner DataRoot. Runtime
validation is intentionally forbidden on the Linux source-authoring host.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile


def main():
    if os.name != 'nt':
        raise SystemExit('NOT_RUN: use the Windows owner Files Python 3.11 interpreter')
    if sys.version_info[:2] != (3, 11):
        raise SystemExit('Use the verified Files Python 3.11 environment')
    import pytest  # noqa: F401 - fail before creating any disposable fixture if absent
    repo = Path(__file__).resolve().parents[2]
    files = repo / 'agents/files/engine'
    tunnel = repo / 'agents/tunnel/engine'
    with tempfile.TemporaryDirectory(prefix='zagent-files-security-') as directory:
        base = Path(directory)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith('ZAGENT_')}
        env.pop('PYTHONPATH', None)
        for key, name in {
            'ZAGENT_FILES_DATA_ROOT': 'data', 'ZAGENT_FILES_CONFIG_DIR': 'config',
            'ZAGENT_FILES_RUNTIME_DIR': 'runtime', 'ZAGENT_FILES_LOG_DIR': 'logs',
            'ZAGENT_FILES_BACKUP_ROOT': 'backups', 'ZAGENT_FILES_UPDATE_STATE_ROOT': 'updates',
        }.items():
            path = base / name
            path.mkdir(parents=True, exist_ok=True)
            env[key] = str(path)
        config = Path(env['ZAGENT_FILES_CONFIG_DIR'])
        (config / 'settings.json').write_text(json.dumps({
            'host': '127.0.0.1', 'port': 8011, 'max_read_bytes': 10485760,
            'max_write_bytes': 52428800, 'secret_names': ['.env']}), encoding='utf-8')
        (config / 'profiles.json').write_text(json.dumps({
            'active_profile': None, 'profiles': []}), encoding='utf-8')
        commands = [
            (tunnel, [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
                      '-p', 'test_files_scope_authority.py', '-v']),
            (files, [sys.executable, '-m', 'pytest', '-q',
                     'tests/test_execution_context.py',
                     'tests/test_consumer_authority_windows.py',
                     'tests/test_managed_commands_windows.py']),
        ]
        for cwd, command in commands:
            print('Running:', subprocess.list2cmdline(command), flush=True)
            result = subprocess.run(command, cwd=cwd, env=env)
            if result.returncode:
                return result.returncode
    print('FOCUSED_WINDOWS_FILES_CHECKS_PASSED; review pytest skipped cases separately. '
          'This is not every product test or proof of every MCP tool.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

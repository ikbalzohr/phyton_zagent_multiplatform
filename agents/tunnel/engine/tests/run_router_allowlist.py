"""Disposable Windows owner runner. Never imports product on the source host."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if os.name != 'nt':
        raise SystemExit('NOT_RUN: Windows owner interpreter required')
    repo = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory(prefix='zagent-router-allowlist-') as directory:
        base = Path(directory)
        env = dict(os.environ)
        for key, child in {
            'ZAGENT_FILES_DATA_ROOT': 'files', 'ZAGENT_FILES_CONFIG_DIR': 'files/config',
            'ZAGENT_FILES_RUNTIME_DIR': 'files/runtime', 'ZAGENT_FILES_LOG_DIR': 'files/logs',
            'ZAGENT_FILES_BACKUP_ROOT': 'files/backups', 'ZAGENT_FILES_UPDATE_STATE_ROOT': 'files/updates',
            'ZAGENT_TUNNEL_CONFIG_DIR': 'tunnel/config', 'ZAGENT_TUNNEL_RUNTIME_DIR': 'tunnel/runtime',
        }.items():
            path = base / child
            path.mkdir(parents=True, exist_ok=True)
            env[key] = str(path)
        env.update(ZAGENT_DEVICE_ID='fixture-device', ZAGENT_INSTALLATION_ID='fixture-installation',
                   ZAGENT_INTERNAL_TOKEN='fixture-channel-' + 'x' * 40,
                   ZAGENT_NATIVE_ALLOWLIST_FIXTURE=str(base))
        env['PYTHONPATH'] = os.pathsep.join(str(repo / p) for p in ('agents/files/engine', 'agents/tunnel/engine'))
        config = Path(env['ZAGENT_FILES_CONFIG_DIR'])
        (config / 'settings.json').write_text(json.dumps(dict(host='127.0.0.1', port=8011, secret_names=['.env'])))
        (config / 'profiles.json').write_text(json.dumps(dict(schema_version='2.0', active_profile='A', profiles=[])))
        for name, value in [('core_services.json', {'services': []}), ('additional_services.json', {'services': []}), ('tunnel.json', {})]:
            (Path(env['ZAGENT_TUNNEL_CONFIG_DIR']) / name).write_text(json.dumps(value))
        return subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
            '--basetemp', str(base / 'pytest'),
            str(repo / 'agents/files/engine/tests/test_router_allowlist_native.py'),
            str(Path(__file__).with_name('test_allowlist_router_discovery.py'))], cwd=repo, env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())

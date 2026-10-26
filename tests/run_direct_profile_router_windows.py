"""Run only on owner Windows; redirect all state BEFORE product imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if os.name != 'nt':
        raise SystemExit('NOT_RUN: Windows owner interpreter required')
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='zagent-direct-profile-router-') as directory:
        base = Path(directory)
        env = dict(os.environ)
        paths = {
            'ZAGENT_FILES_DATA_ROOT': base/'files', 'ZAGENT_FILES_CONFIG_DIR': base/'files/config',
            'ZAGENT_FILES_RUNTIME_DIR': base/'files/runtime', 'ZAGENT_FILES_LOG_DIR': base/'files/logs',
            'ZAGENT_FILES_BACKUP_ROOT': base/'files/backups', 'ZAGENT_FILES_UPDATE_STATE_ROOT': base/'files/updates',
            'ZAGENT_TUNNEL_CONFIG_DIR': base/'tunnel/config', 'ZAGENT_TUNNEL_RUNTIME_DIR': base/'tunnel/runtime'}
        for key, path in paths.items():
            path.mkdir(parents=True, exist_ok=True); env[key] = str(path)
        env.update(ZAGENT_DEVICE_ID='fixture-device', ZAGENT_INSTALLATION_ID='fixture-installation',
                   ZAGENT_INTERNAL_TOKEN='fixture-private-channel-'+'x'*40, ZAGENT_DIRECT_PROFILE_FIXTURE_ROOT=str(base))
        env['PYTHONPATH'] = os.pathsep.join([str(repo/'agents/files/engine'), str(repo/'agents/tunnel/engine')])
        (paths['ZAGENT_FILES_CONFIG_DIR']/'settings.json').write_text(json.dumps({'host':'127.0.0.1','port':8011}), encoding='utf-8')
        (paths['ZAGENT_FILES_CONFIG_DIR']/'profiles.json').write_text(json.dumps({'schema_version':'2.0','active_profile':None,'profiles':[]}), encoding='utf-8')
        for filename, value in [('core_services.json', {'services': []}), ('additional_services.json', {'services': []}), ('tunnel.json', {})]:
            (paths['ZAGENT_TUNNEL_CONFIG_DIR']/filename).write_text(json.dumps(value), encoding='utf-8')
        return subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
            str(Path(__file__).with_name('test_direct_profile_router_windows.py'))], cwd=repo, env=env, check=False).returncode

if __name__ == '__main__':
    raise SystemExit(main())

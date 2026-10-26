"""Windows-only paired seam: actual emitted C# HTTP body -> actual Files request_meta/_verify.
No live credentials, service startup, profile mutation, or secret output. NOT_RUN until Windows.
"""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

def main():
    if os.name != 'nt':
        print('WINDOWS_ONLY; NOT_RUN')
        return 2
    if len(sys.argv) != 3:
        raise SystemExit('usage: check_profile_admin_wire_windows.py EMITTED_WIRE_JSON DISPOSABLE_ROOT')
    root = Path(sys.argv[2]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    # Set EVERY product directory before importing any product module.
    paths = {'ZAGENT_FILES_CONFIG_DIR':'config', 'ZAGENT_FILES_DATA_ROOT':'data',
             'ZAGENT_FILES_RUNTIME_DIR':'runtime', 'ZAGENT_FILES_LOG_DIR':'log',
             'ZAGENT_FILES_BACKUP_ROOT':'backup', 'ZAGENT_FILES_UPDATE_STATE_ROOT':'update'}
    saved = {key:os.environ.get(key) for key in (*paths,'ZAGENT_INTERNAL_TOKEN','ZAGENT_DEVICE_ID','ZAGENT_INSTALLATION_ID')}
    try:
        for key, name in paths.items():
            directory = root / name
            directory.mkdir()
            os.environ[key] = str(directory)
        os.environ.update(ZAGENT_INTERNAL_TOKEN='a'*64,ZAGENT_DEVICE_ID='fixture-device',ZAGENT_INSTALLATION_ID='fixture-installation')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'agents/files/engine'))
        from app.core.execution_context import request_meta
        from app.profiles.administration import _verify
        wire = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        parameters = wire['params']
        def context(header, meta):
            return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={'x-zagent-internal-token':header}),meta=meta))
        metadata = request_meta(context('a'*64,parameters['_meta']))
        verified = _verify(metadata,parameters['name'],parameters['arguments'])
        assert verified['actor_id'] == 'dashboard-session-actor'
        assert verified['principal_id'] == 'fixture-principal'
        def deny(fn):
            try: fn()
            except PermissionError: return
            raise AssertionError('spoof unexpectedly accepted')
        deny(lambda: request_meta(context('b'*64,parameters['_meta'])))
        deny(lambda: _verify(parameters['_meta'],parameters['name'],parameters['arguments']))
        changed = dict(parameters['arguments'],description='tampered')
        deny(lambda: _verify(metadata,parameters['name'],changed))
        print('PASS actual C# wire / Files private token-context-digest verifier seam; no live profile writes')
    finally:
        for key,value in saved.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value
    return 0
if __name__ == '__main__': raise SystemExit(main())

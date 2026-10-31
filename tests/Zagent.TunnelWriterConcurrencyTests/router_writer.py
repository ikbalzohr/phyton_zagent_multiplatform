"""Disposable fixture: real Router publication; POSIX byte-range lock contract.

Use --product-lock to verify the Router writer itself uses the same primitive.
No production configuration or credentials are read.
"""
import json
from pathlib import Path
import sys
import time
from contextlib import contextmanager

repo, root = map(Path, sys.argv[1:3])
sys.path.insert(0, str(repo / 'agents/tunnel/engine'))
from router.allowlist_access import writer, publish, TOOLS

@contextmanager
def byte_lock(path):
    # Identical Windows contract; lockf is the POSIX fcntl byte-range equivalent.
    import fcntl
    import os
    lock_path = Path(str(path) + '.access.lock')
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600), 'r+b') as stream:
        fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
        try:
            yield
        finally:
            fcntl.lockf(stream, fcntl.LOCK_UN, 1, 0)

path = root / 'tunnel.json'
lock = writer if '--product-lock' in sys.argv or sys.platform == 'win32' else byte_lock
if '--probe-lock' in sys.argv:
    try:
        with lock(path):
            pass
    except OSError:
        print('PASS: Router cannot enter while Core holds publication lock')
        sys.exit(0)
    raise AssertionError('Router entered while Core was publishing')
lock = writer if '--product-lock' in sys.argv or sys.platform == 'win32' else byte_lock
with lock(path):
    (root / 'locked').touch()
    deadline = time.monotonic() + 15
    while not (root / 'publish').exists():
        if time.monotonic() > deadline:
            raise TimeoutError('fixture publication signal missing')
        time.sleep(.01)
    raw = path.read_bytes()
    cfg = json.loads(raw)
    cfg['resource_server']['grants'][0]['tools'] += list(TOOLS)
    cfg['router_marker'] = 'published-by-router'
    publish(path, (json.dumps(cfg) + '\n').encode(), raw, lambda: None)
(root / 'published').touch()

"""Execute the production PowerShell process guard with captured CIM fixtures.

These are process-topology regressions, not native Windows ACL acceptance.
"""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which('pwsh') or ('/opt/pwsh/pwsh' if Path('/opt/pwsh/pwsh').is_file() else None)
pytestmark = pytest.mark.skipif(not PWSH, reason='PowerShell 7 required for process-contract tests')
LAUNCHER = r'C:\Users\fixture\Zagent-Envs\files\Scripts\python.exe'
BASE = r'C:\Users\fixture\Python311\python.exe'


def process(pid, parent, path, name='python.exe'):
    return dict(ProcessId=pid, ParentProcessId=parent, ExecutablePath=path, Name=name)


def evaluate(hosts, *, guard_parent=2116, launcher=LAUNCHER):
    script = (ROOT / 'packaging/scripts/Assert-OwnerSearchRecovery.ps1').read_text()
    start = script.index(" $stage='STOPPED_PRODUCERS'")
    stop = script.index(" $stage='ENROLLMENT'", start)
    body = script[start:stop]
    fixture = json.dumps(dict(hosts=hosts, parent=guard_parent, launcher=launcher, base=BASE))
    command = r'''
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$fixture=ConvertFrom-Json ([Console]::In.ReadToEnd())
$RecoveryPid=2116
$RecoveryLauncher=$fixture.launcher
$RecoveryExecutable=$fixture.base
function Assert-ProfileAdminCoreStopped {}
function Get-CimInstance {
 param($ClassName,$Filter,$ErrorAction)
 if ($Filter -like 'ProcessId=*') { return [pscustomobject]@{ParentProcessId=$fixture.parent} }
 return @($fixture.hosts)
}
try {
''' + body + r'''
 @{state='accepted'} | ConvertTo-Json -Compress
} catch {
 @{state='denied';guard=$stage} | ConvertTo-Json -Compress
}
'''
    result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-Command', command],
                            input=fixture, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def captured_chain():
    return [process(14468, 13184, LAUNCHER), process(2116, 14468, BASE)]


def test_windows_venv_redirector_is_not_an_unrelated_executor():
    assert evaluate(captured_chain())['state'] == 'accepted'


def test_direct_interpreter_is_accepted():
    assert evaluate([process(2116, 13184, BASE)], launcher=BASE)['state'] == 'accepted'


@pytest.mark.parametrize('extra', [
    process(3000, 13184, LAUNCHER),
    process(3000, 13184, r'C:\other\python.exe'),
    process(3000, 13184, r'C:\other\node.exe', 'node.exe'),
])
def test_other_executors_still_block(extra):
    assert evaluate(captured_chain() + [extra])['state'] == 'denied'


def test_wrong_launcher_path_is_denied():
    rows = captured_chain()
    rows[0]['ExecutablePath'] = r'C:\other\python.exe'
    assert evaluate(rows)['state'] == 'denied'


def test_wrong_base_path_is_denied():
    rows = captured_chain()
    rows[1]['ExecutablePath'] = r'C:\other\python.exe'
    assert evaluate(rows)['state'] == 'denied'


def test_wrong_guard_parent_is_denied():
    assert evaluate(captured_chain(), guard_parent=14468)['state'] == 'denied'


def test_missing_interpreter_is_denied():
    assert evaluate([process(14468, 13184, LAUNCHER)])['state'] == 'denied'

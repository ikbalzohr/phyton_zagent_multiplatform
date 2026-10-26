"""Lane B stdlib AST guard; no product imports or runtime claims."""
import ast
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
path = BASE / 'app/mcp/managed_commands.py'
tree = ast.parse(path.read_text(encoding='utf-8'))
functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
assert '_policy_profiles' in functions, 'missing strict v1/v2 in-memory policy reader'
reader = ast.unparse(functions['_policy_profiles'])
for required in ("{'version', 'profiles'}", '128', '_POLICY_KEYS', "entry['profile_id'] != profile_id", "entry['version'] != 1"):
    assert required in reader, required
authorize = ast.unparse(functions['authorize_command_call'])
assert '_policy_profiles(_json(POLICY_FILE))' in authorize
assert 'policies[profile_id]' in authorize
assert "arguments.get('profile') is not None" in authorize
assert 'next(' not in authorize
assert 'write_text' not in reader and 'write_bytes' not in reader
owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CommandGrant')
assert 'self.principal, self.workspace, self.profile, self.resource, str(self.root)' in ast.unparse(owner)
worker = ast.unparse(functions['_run_owned'])
assert worker.count('authorize_command_call(tool, arguments, authority)') == 2, 'reload approval at worker entry and before resume'
assert "COMMAND_APPROVAL_CHANGED" in worker, 'changed grant must deny, never retarget'
execute = ast.unparse(functions['execute'])
assert '_run_owned, tool, arguments, grant, cancel, record_id, authority' in execute
command_tree = ast.parse((BASE / 'app/mcp/command_tools.py').read_text(encoding='utf-8'))
for function in ast.walk(command_tree):
    if isinstance(function, ast.AsyncFunctionDef):
        defaults = dict(zip([arg.arg for arg in function.args.args][-len(function.args.defaults):], function.args.defaults))
        if 'profile' in [arg.arg for arg in function.args.args]:
            assert isinstance(defaults['profile'], ast.Constant) and defaults['profile'].value is None
for name in ('owned_record', 'list_owned'):
    assert 'grant.owner' in ast.unparse(functions[name]), name
assert "r['owner'] == grant.owner" in execute, 'stop must filter exact owner before pid'
environment = ast.unparse(functions['child_environment'])
assert "{'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL'}" in environment
assert 'environ.copy' not in environment
job = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_WindowsJob')
resume = ast.unparse(next(n for n in job.body if isinstance(n, ast.FunctionDef) and n.name == 'assign_and_resume'))
assert resume.index('AssignProcessToJobObject') < resume.index('NtResumeProcess')
assert worker.index('authorize_command_call', worker.index('subprocess.Popen')) < worker.index('job.assign_and_resume')
assert worker.index('job.terminate()') < worker.index('thread.join(')
runner = ast.parse((BASE / 'tests/run_multiprofile_commands_lane_b_windows.py').read_text(encoding='utf-8'))
runner_source = ast.unparse(runner)
assert runner_source.index("os.name != 'nt'") < runner_source.index('import pytest')
assert runner_source.index('os.environ[key] = str(path)') < runner_source.index('import pytest')
fixture = ast.parse((BASE / 'tests/test_multiprofile_commands_lane_b_windows.py').read_text(encoding='utf-8'))
fixture_source = ast.unparse(fixture)
assert fixture_source.index("os.name != 'nt'") < fixture_source.index('from app.')
print('PASS Lane B multi-profile policy source contracts (not Windows runtime evidence)')

"""AST-only guard. Safe on authoring host: never imports product modules."""
import ast
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'app' / 'mcp'
command = ast.parse((BASE / 'command_tools.py').read_text(encoding='utf-8'))
managed_path = BASE / 'managed_commands.py'
assert managed_path.exists(), 'missing explicit owner-policy command authority'
managed = ast.parse(managed_path.read_text(encoding='utf-8'))
functions = {n.name: n for n in managed.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
assert 'authorize_command_call' in functions, 'missing authorization seam'
authorize = functions['authorize_command_call']
assert [a.arg for a in authorize.args.args] == ['tool', 'arguments', 'authority']
source = ast.unparse(authorize)
for required in ('VerifiedContext', 'public_tool', 'files:execute', 'files:write', 'effective_resources', 'effective_access', 'profile_id'):
    assert required in source, required
assert 'COMMAND_TOOL_NAMES' in ast.unparse(command)
assert 'execute' in functions, 'missing fail-closed managed dispatcher'
assert "type(authority) is not VerifiedContext" in source, 'exact trusted marker required'
assert "profile.get(field) != authority.get(field)" in source, 'local profile optional identity must bind'
assert "resource[field] != authority.get(field)" in source, 'resource optional identity must bind'
assert 'SUPPORTED_COMMAND_TOOLS' in ast.unparse(functions['execute']), 'capabilities must not advertise unsupported wrappers'
assert 'deadline' in source, 'independent deadline must bound grant'
assert '_npm_entrypoint' in functions, 'npm must use approved node plus fixed reviewed CLI, not batch execution'
assert 'npm-cli.js' in ast.unparse(functions['_npm_entrypoint'])
assert 'npx-cli.js' in ast.unparse(functions['_npm_entrypoint'])
managed_source = ast.unparse(managed)
for required in ('CREATE_SUSPENDED', 'AssignProcessToJobObject', 'TerminateJobObject', 'JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE', 'NtResumeProcess', 'child_environment', 'owned_record'):
    assert required in managed_source, required
assert 'os.environ.copy' not in managed_source
assert 'shutil.which' not in managed_source
assert 'Get-CimInstance' not in managed_source
assert 'taskkill' not in managed_source
assert 'communicate' not in managed_source
registered = [n.name for n in ast.walk(command) if isinstance(n, ast.AsyncFunctionDef) and n.decorator_list]
assert len(registered) == 13 and len(set(registered)) == 13
for n in ast.walk(command):
    if isinstance(n, ast.AsyncFunctionDef) and n.decorator_list:
        assert any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == 'execute' and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == n.name for c in ast.walk(n)), n.name
print('PASS command authority + owned-job source contracts (not Windows runtime evidence)')

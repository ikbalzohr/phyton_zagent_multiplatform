"""Non-importing AST/source integration checks, NOT Windows behavioral evidence."""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'agents/files/engine'
ROUTER = ROOT / 'agents/tunnel/engine/router'


def source(path):
    text = path.read_text(encoding='utf-8')
    ast.parse(text, filename=str(path))
    return text


def check_workers():
    domain = source(FILES / 'app/profiles/administration.py')
    assert 'async def catalog_worker(' in domain, 'worker must own a cancellation-resistant catalog lease'
    helper = next(n for n in ast.parse(domain).body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'catalog_worker')
    text = ast.get_source_segment(domain, helper)
    for required in ('read_lease(control=True)', 'asyncio.shield', 'while True:', 'asyncio.CancelledError'):
        assert required in text, required
    assert 'catalog_worker(asyncio.to_thread(' in source(FILES / 'app/mcp/managed_commands.py')
    assert 'catalog_worker(asyncio.get_running_loop().run_in_executor(' in source(FILES / 'app/core/execution.py')


def check_capability():
    text = source(ROUTER / 'profile_admin.py')
    fn = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'has_owner_capability')
    fragment = ast.get_source_segment(text, fn)
    assert "if 'profile_management' not in grant:" in fragment, 'explicit null capability must deny, not fall back to legacy'


def check_generation():
    commands = source(FILES / 'app/mcp/managed_commands.py')
    assert 'profile_generation(profile, profiles)' in commands, 'command worker must recheck committed profile generation'
    assert 'self.generation' in commands, 'owned command namespace must include generation'
    text = source(ROUTER / 'execution_context.py')
    assert "if selected_profile_id is None and default not in allowed:" in text, 'disabled default must not block explicitly selected authorized profiles'


def check_fixture_repairs():
    text = source(FILES / 'tests/test_multiprofile_commands_lane_b_windows.py')
    assert "ZAGENT_COMMAND_MULTIPROFILE_FIXTURE_ROOT" in text, 'direct collection must not import live paths'
    assert "rows['active_profile'] = 'B'" in text and "rows['default'] = 'B'" not in text
    assert "manager.default_profile_name() == 'B'" in text
    text = source(ROOT / 'agents/tunnel/engine/tests/test_files_resource_policy.py')
    assert 'self.assertEqual(verified["session_id"], consumer.owner_key(context))' in text


CHECKS = {'workers': check_workers, 'capability': check_capability, 'generation': check_generation, 'fixtures': check_fixture_repairs}
if __name__ == '__main__':
    for name in sys.argv[1:] or CHECKS:
        CHECKS[name]()
        print('PASS source-only:', name, '(Windows runtime NOT_RUN)')

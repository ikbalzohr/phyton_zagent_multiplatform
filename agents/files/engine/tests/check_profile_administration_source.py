"""Source-only acceptance; never imports Windows product modules."""
import ast
from pathlib import Path
base = Path(__file__).resolve().parents[1]
p = base / 'app/profiles/administration.py'
assert p.exists(), 'single-writer administration module missing'
s = p.read_text(encoding='utf-8')
t = ast.parse(s)
for name in ('catalog_snapshot', 'admin_call', 'read_lease', 'profile_generation', 'current_catalog'):
    assert any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name for n in ast.walk(t)), name
for token in ('os.replace', 'os.fsync', 'IDEMPOTENCY_CONFLICT', 'REVISION_CONFLICT', 'TrustedMetadata', 'profile_management', 'FILE_ATTRIBUTE_REPARSE_POINT'):
    assert token in s, token
server = (base / 'app/mcp/server.py').read_text(encoding='utf-8')
assert 'PROFILE_ADMIN_TOOLS' in server and 'read_lease' in server
manager = (base / 'app/profiles/manager.py').read_text(encoding='utf-8')
assert 'MANAGED_PROFILE_SINGLE_WRITER_REQUIRED' in manager
context = (base / 'app/core/execution_context.py').read_text(encoding='utf-8')
assert 'PROFILE_GENERATION_MISMATCH' in context
fixture = base/'tests/run_profile_administration_windows.py'
f = ast.parse(fixture.read_text(encoding='utf-8'))
guard_line = next(n.lineno for n in f.body if isinstance(n, ast.If) and "os.name" in ast.unparse(n.test))
assert guard_line < next(n.lineno for n in ast.walk(f) if isinstance(n, ast.ImportFrom) and (n.module or '').startswith('app.'))
assert 'new_admin_context' in fixture.read_text(encoding='utf-8') and 'request_meta(ctx)' in fixture.read_text(encoding='utf-8')
# Generation guard must not be unreachable inside the approval-rejection block.
validation = next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name == 'profile_generation')
assert 'owner_management' in ast.unparse(validation)
ctx_tree = ast.parse(context)
vp = next(n for n in ctx_tree.body if isinstance(n,ast.FunctionDef) and n.name == 'validate_profile')
assert any(isinstance(n,ast.If) and 'PROFILE_GENERATION_MISMATCH' in ast.unparse(n) and 'profile_generation' in ast.unparse(n.test) for n in vp.body)
for file in (p, base/'app/profiles/manager.py', base/'app/mcp/server.py', base/'app/core/execution_context.py', base/'app/core/execution.py', fixture):
    compile(file.read_text(encoding='utf-8'), str(file), 'exec')
print('PASS: administration source contract (AST/compile/text only; Windows behavior NOT_RUN)')

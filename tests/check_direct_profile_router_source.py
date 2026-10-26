"""Source-only contract guard; never imports product on Linux."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'agents/tunnel/engine/router'

def check():
    p = R / 'profile_admin.py'
    assert p.exists(), 'missing separate profile administration authority module'
    tree = ast.parse(p.read_text(encoding='utf-8'))
    values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
              and n.targets[0].id == 'PROFILE_ADMIN_SCOPES'}
    scopes = values['PROFILE_ADMIN_SCOPES']
    assert len(scopes) == 6
    assert scopes['files_profile_admin_list'] == 'files:read'
    assert scopes['files_profile_admin_delete'] == 'files:write'
    for name in ['profile_admin.py', 'registry.py', 'server.py', 'execution_context.py', 'files_policy.py', 'files_selection.py', 'access.py']:
        ast.parse((R/name).read_text(encoding='utf-8'), filename=name)
    s = (R/'server.py').read_text(encoding='utf-8')
    assert 'require_profile_management' in s
    assert 'await registry.profile_catalog_snapshot' in s
    assert 'if public_tool in PROFILE_ADMIN_SCOPES:' in s, 'admin receipts must not require administered row'
    registry = (R/'registry.py').read_text(encoding='utf-8')
    assert 'zagent.profile_admin_context' in registry
    assert 'zagent.profile_catalog_context' in registry
    assert 'CATALOG_TOOL' in registry and 'files_profile_catalog_snapshot' in p.read_text(encoding='utf-8')
    assert 'profile_generation' in (R/'execution_context.py').read_text(encoding='utf-8')
    owned = next(n for n in ast.parse(s).body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_owned_task')
    owned_source = ast.get_source_segment(s, owned) or ''
    assert 'enabled' in owned_source, 'receipt must recheck current enabled exact tool policy'
    assert 'PROFILE_ADMIN_PUBLIC_META_DENIED' in s, 'admin must reject public channel-meta spoof, not silently ignore it'
    assert 'isfinite' in p.read_text(encoding='utf-8')
    domain = ast.parse((ROOT/'agents/files/engine/app/profiles/administration.py').read_text(encoding='utf-8'))
    common = next(ast.literal_eval(n.value) for n in domain.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'COMMON')
    catalog_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'catalog_context')
    ret = next(n for n in ast.walk(catalog_fn) if isinstance(n, ast.Return))
    assert {ast.literal_eval(k) for k in ret.value.keys} == common
    schema_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'revalidate_admin')
    envelope_fields = next(ast.literal_eval(n.value) for n in ast.walk(schema_fn) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'fields')
    assert envelope_fields == common | {'action','public_tool','request_id','operation_id','capability_revision','payload_digest','bootstrap_resource'}
    print('PASS Router direct-profile source contracts (NOT Windows/runtime evidence)')

if __name__ == '__main__':
    check()

"""Stdlib, non-importing source contract guard (not behavioral evidence)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def source(path):
    text = (ROOT / path).read_text(encoding='utf-8')
    ast.parse(text, filename=path)
    compile(text, path, 'exec')  # compilation only; never execute/import product
    return text

router = source('agents/tunnel/engine/router/execution_context.py')
server = source('agents/tunnel/engine/router/server.py')
registry = source('agents/tunnel/engine/router/registry.py')
consumer = source('agents/files/engine/app/core/execution_context.py')
engine = source('agents/files/engine/app/core/execution.py')
assert 'allowed_profile_ids' in router, 'grant allowlist is not implemented'
helper = source('agents/tunnel/engine/router/files_selection.py')
assert 'files_tool_schema(tool)' in server, 'visible/invocation schema must use common augmentation'
assert 'selected_profile_id=selected_profile' in server
assert 'selected_profile_id=context["effective_resources"][0]["profile_id"]' in server
assert 'forward_files_arguments' in registry
assert 'selected_files_profile' in registry, 'Files result profile must come from verified selection, not legacy scheduler hints'
assert "forbidden.discard('profile_id')" in consumer
assert "'profile_id', 'source_profile', 'destination_profile'" in consumer
assert "'device_id', 'installation_id'" in consumer
assert "'owner_files_v2_'" in consumer
assert "'context_version' not in context and 'effective_resources' not in context" in consumer, 'legacy private owner-key helper contract must remain compatible'
assert 'installation:' in router and '"access_mode": "write"' in router
assert "profile = self.bind_named(sid, meta['profile_id'])" in engine
assert 'CLIENT_AUTHORITY_NOT_ALLOWED' in consumer
assert "'profile_id'" in helper and 'deepcopy' in helper
assert 'reject_authority(inner)' in helper, 'public wrapper must reject nested authority before queuing'
mcp_server = source('agents/files/engine/app/mcp/server.py')
assert "engine.ensure_session(authority['session_id'], authority['profile_id'])" in mcp_server, 'remote session controls must seed from selected resource, not local default'
assert "owner_key(metadata)" in engine, 'owner must be derived from verified context before copying metadata'
for path in ('agents/files/engine/tests/test_native_multiprofile_windows.py',
             'agents/files/engine/tests/run_native_multiprofile_windows.py'):
    source(path)

# Extract only literal declarations: never import product or execute functions.
def literal_assignment(text, name):
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == 'frozenset':
                value = value.args[0]
            return ast.literal_eval(value)
    raise AssertionError('missing declaration ' + name)

catalog = literal_assignment(source('agents/tunnel/engine/router/files_policy.py'), 'FILES_TOOL_SCOPES')
for name in ('NATIVE_READ', 'NATIVE_WRITE', 'READ_CONTROLS', 'WRITE_CONTROLS', 'COMMAND_TOOLS'):
    entries = literal_assignment(consumer, name)
    for entry in entries:
        tool = entry if entry.startswith('files_') else 'files_' + entry
        assert tool in catalog, ('consumer/catalog drift', tool)
assert literal_assignment(helper, 'COMMAND_TOOLS') == literal_assignment(consumer, 'COMMAND_TOOLS')
assert literal_assignment(helper, 'DOMAIN_PROFILE_ID_TOOLS') == {'files_workspace_status', 'files_workspace_switch'}
print('PASS native multi-profile AST/compile/text source checks (Windows runtime NOT_RUN)')

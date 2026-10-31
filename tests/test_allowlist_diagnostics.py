"""Sanitized native allowlist visibility projection; no installed config reads."""
from pathlib import Path
from types import SimpleNamespace
import time

from router.access import AuthContext, AuthorizationError

MODULE = Path(__file__).resolve().parents[1] / 'agents/tunnel/engine/router/allowlist_diagnostics.py'
TOOLS = ('files_allowlist_list', 'files_allowlist_add', 'files_allowlist_remove', 'files_allowlist_replace')


def project(**overrides):
    assert MODULE.exists(), 'allowlist visibility diagnostic implementation missing'
    from router.allowlist_diagnostics import allowlist_diagnostics
    auth = overrides.get('auth', AuthContext('p', 'w', frozenset({'files:read', 'files:write'}),
        frozenset(TOOLS), 'r', time.time() + 60))
    registry = SimpleNamespace(tool_index={name: ('files', name) for name in overrides.get('upstream', TOOLS)})
    def lookup(name):
        return {'scope': 'files:read' if name.endswith('_list') else 'files:write', 'enabled': True}
    return allowlist_diagnostics(auth, registry, overrides.get('lookup', lookup))


def test_reports_upstream_absence_without_guessing_permission_cause():
    rows = project(upstream=())
    assert len(rows) == 4
    assert all(r['blockers'] == ['UPSTREAM_NOT_DISCOVERED'] for r in rows)


def test_visible_tools_have_no_blockers():
    assert all(r['blockers'] == [] for r in project())


def test_missing_exact_tool_grant_is_distinct_from_missing_scope():
    auth = AuthContext('p', 'w', frozenset({'files:read'}), frozenset({'files_allowlist_list'}), 'r', time.time()+60)
    rows = {r['name']: r for r in project(auth=auth)}
    assert rows['files_allowlist_list']['blockers'] == []
    assert rows['files_allowlist_add']['blockers'] == ['SCOPE_MISSING', 'TOOL_NOT_GRANTED']


def test_policy_rejection_does_not_echo_private_exception_text():
    def lookup(name):
        raise AuthorizationError('private bearer secret and file path')
    rows = project(lookup=lookup)
    assert all(r['blockers'] == ['POLICY_REJECTED'] for r in rows)
    assert 'secret' not in repr(rows)


def test_explicit_disabled_policy_is_projected():
    rows = project(lookup=lambda name: {'scope': 'files:read' if name.endswith('_list') else 'files:write', 'enabled': False})
    assert all(r['blockers'] == ['POLICY_DISABLED'] for r in rows)


def test_expired_auth_is_not_reported_visible():
    auth = AuthContext('p','w',frozenset({'files:read','files:write'}),frozenset(TOOLS),'r',0)
    assert all('AUTH_EXPIRED' in r['blockers'] for r in project(auth=auth))

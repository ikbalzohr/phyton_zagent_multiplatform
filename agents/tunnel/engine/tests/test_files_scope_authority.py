"""Windows behavioral fixtures: authored only; NEVER run/import on the VPS.

On the Windows owner host, from agents/tunnel/engine:
python -m unittest discover -s tests -p test_files_scope_authority.py -v
"""
import copy
import time
import unittest
from unittest.mock import patch

from router.access import AuthContext, AuthorizationError, ResourceAuthorizer
from router.execution_context import new_context, reject_authority, scheduler_meta, validate_context
from router.files_policy import FILES_TOOL_SCOPES, MANAGEMENT_ONLY_TOOLS, scope_for_files_tool, validate_files_tool_scope
from router.identity import Placement


class FilesScopeAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.placement = Placement('device', 'install')
        self.policy = ResourceAuthorizer({'workspace_id': 'ws', 'policy_revision': '1',
            'grants': {'p': {'files_resource': {'resource_id': 'workspace:ws:approved',
                'kind': 'files', 'profile_id': 'appBridge', 'device_id': 'device',
                'installation_id': 'install', 'revoked': False}}}})

    def context(self, tool='files_stat', scopes=None, scope=None):
        required = scope_for_files_tool(tool)
        auth = AuthContext('p', 'ws', frozenset(scopes if scopes is not None else {required}),
                           frozenset({tool}), '1', time.time()+120)
        return new_context(auth, self.placement, scope or required, tool,
                           resource_authorizer=self.policy)

    def test_all_catalog_entries_derive_expected_access(self):
        for tool, scope in FILES_TOOL_SCOPES.items():
            with self.subTest(tool=tool):
                scopes = {scope} | ({'files:write'} if scope == 'files:execute' else set())
                expected = 'read' if scope == 'files:read' else 'write'
                self.assertEqual(validate_files_tool_scope(tool, scope, scopes), expected)
                context = self.context(tool, scopes)
                self.assertEqual(context['effective_access'], expected)
                self.assertEqual(context['public_tool'], tool)
                self.assertEqual(context['effective_resources'], [{'kind': 'files',
                    'profile_id': 'appBridge', 'resource_id': 'workspace:ws:approved'}])
                self.assertEqual(validate_context(context, self.placement), context)

    def test_unknown_management_and_noncanonical_names_fail_closed(self):
        for tool in list(MANAGEMENT_ONLY_TOOLS) + ['files_new_tool', 'stat', 'files_files_stat',
                                                  ' files_stat', 'FILES_STAT', '', None, []]:
            with self.subTest(tool=tool), self.assertRaises(AuthorizationError):
                scope_for_files_tool(tool)

    def test_scope_configuration_cannot_downgrade_or_alias(self):
        for tool, required in FILES_TOOL_SCOPES.items():
            for scope in {'files:read', 'files:write', 'files:execute', 'web:read', 'file:read'} - {required}:
                with self.subTest(tool=tool, scope=scope), self.assertRaises(AuthorizationError):
                    self.context(tool, {'files:read', 'files:write', 'files:execute', scope}, scope)

    def test_execute_requires_both_write_and_execute_even_for_process_list(self):
        for tool, scope in FILES_TOOL_SCOPES.items():
            if scope != 'files:execute':
                continue
            for scopes in ({'files:execute'}, {'files:write'}, {'files:read'}, set()):
                with self.subTest(tool=tool, scopes=scopes), self.assertRaises(AuthorizationError):
                    self.context(tool, scopes)

    def test_write_is_not_implied_by_read_or_execute(self):
        for tool in ('files_write', 'files_delete', 'files_execute'):
            for scopes in ({'files:read'}, {'files:execute'}):
                with self.subTest(tool=tool, scopes=scopes), self.assertRaises(AuthorizationError):
                    self.context(tool, scopes)

    def test_tool_grant_is_still_required(self):
        auth = AuthContext('p', 'ws', frozenset({'files:read'}), frozenset(), '1', time.time()+60)
        with self.assertRaises(AuthorizationError):
            new_context(auth, self.placement, 'files:read', 'files_stat', resource_authorizer=self.policy)

    def test_consumer_rejects_tampered_tool_scope_access_and_resource(self):
        original = self.context()
        for changes in ({'public_tool': 'files_write'}, {'public_tool': 'files_unknown'},
                        {'public_tool': 'files_update_status'}, {'public_tool': 'stat'},
                        {'required_scope': 'files:write'}, {'required_scope': 'web:read'},
                        {'scopes': []}, {'effective_access': 'write'},
                        {'effective_resources': [{'kind': 'browser', 'resource_id': 'installation:install'}]},
                        {'effective_resources': [{'kind': 'files', 'resource_id': 'r'}]},
                        {'scopes': ['files:read', 1]}):
            context = copy.deepcopy(original)
            context.update(changes)
            with self.subTest(changes=changes), self.assertRaises(AuthorizationError):
                validate_context(context, self.placement)
        command = self.context('files_exec_command', {'files:write', 'files:execute'})
        command['scopes'] = ['files:execute']
        with self.assertRaises(AuthorizationError):
            validate_context(command, self.placement)

    def test_validation_never_extends_original_deadline(self):
        context = self.context()
        deadline = context['deadline']
        with patch('router.execution_context.time.time', return_value=deadline-1):
            self.assertEqual(validate_context(context, self.placement)['deadline'], deadline)
        with patch('router.execution_context.time.time', return_value=deadline+1):
            with self.assertRaises(AuthorizationError):
                validate_context(context, self.placement)
        self.assertEqual(context['deadline'], deadline)

    def test_read_authority_keeps_installation_write_scheduler_lock(self):
        meta = scheduler_meta(self.context(), 'owner')
        self.assertEqual(meta['execution_context']['effective_access'], 'read')
        self.assertEqual(meta['access_mode'], 'write')
        self.assertEqual(meta['resource_key'], 'installation:install')

    def test_client_cannot_override_effective_authority(self):
        for field in ('effective_access', 'required_scope', 'public_tool', 'effective_resources',
                      'execution_context', '_meta', 'metadata'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                reject_authority({field: 'write'})

    def test_web_arcmap_existing_write_authority_is_unchanged(self):
        for scope, tool, kind in [('web:read', 'web_snapshot', 'browser'),
                                  ('arcmap:read', 'arcmap_status', 'arcmap')]:
            auth = AuthContext('p', 'ws', frozenset({scope}), frozenset({tool}), '1', time.time()+60)
            context = new_context(auth, self.placement, scope, tool)
            self.assertEqual(context['effective_access'], 'write')
            self.assertEqual(context['effective_resources'], [{'resource_id': 'installation:install', 'kind': kind}])
            self.assertEqual(validate_context(context, self.placement), context)


if __name__ == '__main__':
    unittest.main()

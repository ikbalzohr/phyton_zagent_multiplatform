"""Router-side discovery/scope/schema regressions for native allowlist tools.

Pure-router; runs on Linux. No Files backend, OAuth or live transport is involved.
"""
import copy
import time
import unittest

from router.access import AuthContext, AuthorizationError, ResourceAuthorizer
from router.execution_context import new_context, reject_authority, validate_context
from router.files_policy import FILES_TOOL_SCOPES, MANAGEMENT_ONLY_TOOLS, scope_for_files_tool, validate_files_tool_scope
from router.files_selection import files_tool_schema, selected_profile, profile_id
from router.identity import Placement
from unittest.mock import patch

from router.server import _policy


PLACEMENT = Placement('device', 'install')


class AllowlistRouterDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.policy = ResourceAuthorizer({'workspace_id': 'ws', 'policy_revision': '1',
            'grants': {'p': {'files_resource': {'resource_id': 'workspace:ws:approved',
                'kind': 'files', 'profile_id': 'appBridge', 'device_id': 'device',
                'installation_id': 'install', 'revoked': False}}}})

    def auth(self, tools=frozenset()):
        return AuthContext('p', 'ws', frozenset({'files:read', 'files:write'}), tools, '1', time.time()+60)

    def test_four_exact_tool_names_are_canonical_and_scoped(self):
        self.assertEqual(scope_for_files_tool('files_allowlist_list'), 'files:read')
        for tool in ('files_allowlist_add', 'files_allowlist_remove', 'files_allowlist_replace'):
            self.assertEqual(scope_for_files_tool(tool), 'files:write')

    def test_unknown_allowlist_shapes_fail_closed(self):
        for name in ('files_allowlist_get', 'files_allowlist_modify', 'files_allowlist',
                     'files_allowlist_list_all', 'files_allowlist_add.exe', 'files_allowlist_add\n'):
            with self.subTest(name=name):
                with self.assertRaises(AuthorizationError):
                    scope_for_files_tool(name)

    def test_schema_rejects_extra_fields_and_malformed_revision(self):
        from jsonschema import Draft202012Validator
        for tool, props, required in [
            ('files_allowlist_list', {'profile_id': {'type': 'string'}}, ['profile_id']),
            ('files_allowlist_add', {'profile_id': {'type': 'string'}, 'executable': {'type': 'string'},
                'expected_revision': {'type': 'string'}}, ['profile_id', 'executable', 'expected_revision']),
            ('files_allowlist_replace', {'profile_id': {'type': 'string'}, 'executable': {'type': 'string'},
                'expected_revision': {'type': 'string'}, 'replacement_executable': {'type': 'string'}},
                ['profile_id', 'executable', 'expected_revision', 'replacement_executable']),
        ]:
            sample = {'name': tool, 'description': 'd', 'inputSchema': {'type': 'object',
                'properties': props, 'required': list(required), 'additionalProperties': True}}
            schema = files_tool_schema(sample)['inputSchema']
            self.assertFalse(schema['additionalProperties'])
            self.assertEqual(schema['required'], required)
            for bad in ({'profile_id': 'appBridge', 'extra': 'x'}, {'profile_id': 'appBridge', 'executable': 'x',
                'expected_revision': 'nope'}):
                with self.subTest(tool=tool, args=bad):
                    with self.assertRaises(Exception):
                        Draft202012Validator(schema).validate(bad)

    def test_profile_selection_is_trusted_only(self):
        auth = self.auth(frozenset({'files_allowlist_list'}))
        context = new_context(auth, PLACEMENT, 'files:read', 'files_allowlist_list',
            resource_authorizer=self.policy, selected_profile_id='appBridge')
        self.assertEqual(context['effective_resources'][0]['profile_id'], 'appBridge')
        # A caller cannot select a profile outside the authenticated resource scope.
        with self.assertRaises(AuthorizationError):
            new_context(auth, PLACEMENT, 'files:read', 'files_allowlist_list',
                resource_authorizer=self.policy, selected_profile_id='attacker')

    def test_only_four_native_tools_default_when_per_tool_policy_absent(self):
        for config in ({}, {'tool_policy': {}}, {'tool_policy': {'files_read': {
                'scope': 'files:read', 'enabled': False}}}):
            with patch('router.server.load_tunnel_config', return_value=config):
                for tool in ('files_allowlist_list', 'files_allowlist_add',
                             'files_allowlist_remove', 'files_allowlist_replace'):
                    with self.subTest(config=config, tool=tool):
                        self.assertEqual(_policy(tool), {
                            'scope': scope_for_files_tool(tool), 'enabled': True})

    def test_existing_files_disabled_policy_is_preserved(self):
        for tool in ('files_read', 'files_exec_command'):
            entry = {'scope': scope_for_files_tool(tool), 'enabled': False}
            with patch('router.server.load_tunnel_config', return_value={
                    'tool_policy': {tool: entry}}):
                self.assertEqual(_policy(tool), entry)

    def test_every_files_policy_must_match_canonical_scope(self):
        for tool in FILES_TOOL_SCOPES:
            wrong_scope = 'files:write' if scope_for_files_tool(tool) == 'files:read' else 'files:read'
            with self.subTest(tool=tool), patch('router.server.load_tunnel_config',
                    return_value={'tool_policy': {tool: {'scope': wrong_scope}}}):
                with self.assertRaises(AuthorizationError) as caught:
                    _policy(tool)
                self.assertEqual(caught.exception.code, 'FILES_TOOL_SCOPE_MISMATCH')

    def test_absent_existing_and_unknown_tools_fail_closed(self):
        for name in ('files_read', 'files_exec_command', 'does_not_exist',
                     'files_allowlist_get', 'files_allowlist_add.exe'):
            with self.subTest(tool=name), patch('router.server.load_tunnel_config', return_value={}):
                with self.assertRaises(AuthorizationError):
                    _policy(name)
        with patch('router.server.load_tunnel_config', return_value={
                'tool_policy': {'files_unknown': {'scope': 'files:read'}}}):
            with self.assertRaises(AuthorizationError):
                _policy('files_unknown')

    def test_explicit_native_policy_overrides_default_without_repair(self):
        for tool in ('files_allowlist_list', 'files_allowlist_add',
                     'files_allowlist_remove', 'files_allowlist_replace'):
            entry = {'scope': scope_for_files_tool(tool), 'enabled': False, 'custom': 'retained'}
            with self.subTest(tool=tool), patch('router.server.load_tunnel_config',
                    return_value={'tool_policy': {tool: entry}}):
                self.assertEqual(_policy(tool), entry)
            for malformed in (None, False, '', [], {}, {'enabled': False}, {'scope': ''}):
                with self.subTest(tool=tool, malformed=malformed), patch(
                        'router.server.load_tunnel_config',
                        return_value={'tool_policy': {tool: malformed}}):
                    with self.assertRaises(AuthorizationError):
                        _policy(tool)

    def test_malformed_policy_map_does_not_enable_native_defaults(self):
        for malformed in ('bad', ['files_allowlist_add'], True, False, 0, '', []):
            with self.subTest(config=malformed), patch('router.server.load_tunnel_config',
                    return_value={'tool_policy': malformed}):
                with self.assertRaises(AuthorizationError):
                    _policy('files_allowlist_add')

    def test_existing_non_files_policy_remains_authoritative(self):
        entry = {'scope': 'arcmap:read', 'enabled': False}
        with patch('router.server.load_tunnel_config', return_value={
                'tool_policy': {'arcmap_ping': entry},
                'allowlist_tool_policy': {'arcmap_ping': {'scope': 'arcmap:write'}}}):
            self.assertEqual(_policy('arcmap_ping'), entry)

    def test_management_only_names_not_exposed_as_allowlist(self):
        self.assertNotIn('files_allowlist_add', MANAGEMENT_ONLY_TOOLS)
        self.assertIn('files_allowlist_add', FILES_TOOL_SCOPES)


if __name__ == '__main__':
    unittest.main()

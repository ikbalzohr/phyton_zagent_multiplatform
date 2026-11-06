import unittest
from router.profile_admin import tool_schema


class ExecutionAccessSchemaTests(unittest.TestCase):
    def test_create_and_update_are_owner_scoped_explicit_enums(self):
        for action in ('create','update'):
            schema=tool_schema('files_profile_admin_'+action)
            props=(schema['properties']['changes']['properties']
                   if action=='update' else schema['properties'])
            self.assertEqual(props['execution_access']['enum'],
                             ['disabled','developer','full'])
            self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('execution_access',tool_schema('files_profile_admin_list')['properties'])

    def test_read_only_file_tools_do_not_get_execution_scopes(self):
        from router.files_policy import FILES_TOOL_SCOPES
        self.assertEqual(FILES_TOOL_SCOPES['files_read'],'files:read')
        self.assertEqual(FILES_TOOL_SCOPES['files_git'],'files:execute')
        self.assertEqual(FILES_TOOL_SCOPES['files_powershell_run'],'files:execute')

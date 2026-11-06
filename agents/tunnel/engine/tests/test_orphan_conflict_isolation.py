"""Regression: a stale ArcMap ping must not quarantine Files development.

All rows and execution contexts are synthetic. No live journal is touched.
"""
import json
import unittest

from router.orphan_conflicts import blocks_service, nonblocking_probe


def orphan(service, tool, *, canonical=False):
    context = {
        'context_version': 1, 'public_tool': tool,
        'required_scope': 'arcmap:inspect', 'installation_id': 'install',
        'device_id': 'device',
        'effective_resources': [{'kind': 'arcmap', 'resource_id': 'installation:install'}],
    } if canonical else {}
    return {
        'service_id': service, 'tool_name': tool,
        'resource_key': 'installation:install',
        'arguments_json': '{}',
        'execution_context_json': json.dumps(context),
        'target_device_id': 'device', 'executed_on': 'device',
    }


class OrphanConflictsTests(unittest.TestCase):
    def test_canonical_arcmap_ping_does_not_block_any_service(self):
        row = orphan('zagent_arcmap', 'arcmap_ping', canonical=True)
        self.assertTrue(nonblocking_probe(row))
        for target in ('zagent_files', 'zagent_files_v3', 'zagent_arcmap',
                       'zagent_web', 'zagent_qgis', '__workflow__'):
            with self.subTest(target=target):
                self.assertFalse(blocks_service(row, target))

    def test_live_legacy_ping_uses_execute_scope_but_is_still_no_effect(self):
        # Actual 2026-11-06 orphaned arcmap_ping used arcmap:execute.
        # The operation itself, not the coarse OAuth scope, is read-only.
        row = orphan('zagent_arcmap', 'arcmap_ping', canonical=True)
        context = json.loads(row['execution_context_json'])
        context['required_scope'] = 'arcmap:execute'
        row['execution_context_json'] = json.dumps(context)
        self.assertTrue(nonblocking_probe(row))
        for target in ('zagent_files', 'zagent_arcmap', 'zagent_web'):
            self.assertFalse(blocks_service(row, target))

    def test_uncertain_arcmap_writer_quarantines_only_arcmap_family(self):
        row = orphan('zagent_arcmap', 'arcmap_set_title')
        self.assertFalse(nonblocking_probe(row))
        self.assertTrue(blocks_service(row, 'zagent_arcmap'))
        for target in ('zagent_files', 'zagent_files_v3', 'zagent_web', 'zagent_qgis'):
            with self.subTest(target=target):
                self.assertFalse(blocks_service(row, target))

    def test_files_command_orphan_blocks_files_and_qgis_not_arcmap_or_browser(self):
        row = orphan('zagent_files', 'files_exec_command')
        for target in ('zagent_files', 'zagent_files_v3', 'zagent_qgis'):
            self.assertTrue(blocks_service(row, target))
        for target in ('zagent_arcmap', 'zagent_web'):
            self.assertFalse(blocks_service(row, target))

    def test_mutating_browser_orphan_is_scoped_to_browser(self):
        row = orphan('zagent_web', 'web_click')
        self.assertTrue(blocks_service(row, 'zagent_web'))
        self.assertFalse(blocks_service(row, 'zagent_files'))
        self.assertFalse(blocks_service(row, 'zagent_arcmap'))

    def test_workflow_and_unknown_services_fail_closed(self):
        for source in ('__workflow__', 'unknown_service'):
            row = orphan(source, 'arcmap_goal_execute')
            for target in ('zagent_files', 'zagent_arcmap', 'zagent_web'):
                self.assertTrue(blocks_service(row, target))
        row = orphan('zagent_arcmap', 'arcmap_set_title')
        for target in ('__workflow__', 'unknown_service'):
            self.assertTrue(blocks_service(row, target))

    def test_spoofed_or_corrupt_ping_context_does_not_bypass_quarantine(self):
        base = orphan('zagent_arcmap', 'arcmap_ping', canonical=True)
        mutations = [
            {'execution_context_json': '{}'},
            {'arguments_json': '{"unexpected":true}'},
            {'execution_context_json': 'not-json'},
            {'target_device_id': 'different'},
            {'service_id': 'zagent_files'},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                row = dict(base, **mutation)
                self.assertFalse(nonblocking_probe(row))
                self.assertTrue(blocks_service(row, 'zagent_arcmap'))

    def test_explicit_inspection_not_blanket_whitelist(self):
        row = orphan('zagent_arcmap', 'arcmap_get_status', canonical=True)
        self.assertFalse(nonblocking_probe(row))
        self.assertTrue(blocks_service(row, 'zagent_arcmap'))


if __name__ == '__main__':
    unittest.main()

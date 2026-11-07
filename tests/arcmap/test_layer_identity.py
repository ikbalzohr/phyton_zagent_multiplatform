"""Actual bridge source, isolated configuration, fake unavailable ArcPy only."""
import importlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / 'agents/arcmap/engine/arcmap_bridge'


class Layer:
    def __init__(self, name, supported=True, failure=None):
        self.name = name
        self.supported = supported
        self.failure = failure
        self.writes = []
        self._visible = True
        self._query = ''

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, value):
        self.writes.append(('visible', value))
        self._visible = value

    def supports(self, capability):
        if self.failure == 'supports':
            raise RuntimeError('capability failed')
        return self.supported

    @property
    def definitionQuery(self):
        return self._query

    @definitionQuery.setter
    def definitionQuery(self, value):
        if self.failure == 'query':
            raise RuntimeError('query failed')
        self.writes.append(('definition_query', value))
        self._query = value


class Frame:
    def __init__(self, name, *layers):
        self.name = name
        self.layers = list(layers)


class LayerIdentityTests(unittest.TestCase):
    def setUp(self):
        prefixes = ('core', 'features', 'arcpy')
        self.saved_modules = {k: v for k, v in sys.modules.items()
                              if any(k == p or k.startswith(p + '.') for p in prefixes)}
        for k in self.saved_modules:
            del sys.modules[k]
        self.addCleanup(self.restore_modules)
        self.saved_env = os.environ.copy()
        self.addCleanup(self.restore_environment)
        self.old_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        self.addCleanup(setattr, sys, 'dont_write_bytecode', self.old_bytecode)
        validation = ROOT / '_validation'
        validation.mkdir(exist_ok=True)
        self.fixture = Path(tempfile.mkdtemp(prefix='layer_identity_', dir=str(validation)))
        self.addCleanup(shutil.rmtree, str(self.fixture))
        for key in ('ENGINE_ROOT', 'DATA_ROOT', 'CONFIG_DIR', 'IPC_ROOT'):
            os.environ['ZAGENT_ARCMAP_' + key] = str(self.fixture / key)
        self.frames = []
        self.refreshes = []
        self.mxd = types.SimpleNamespace()
        arcpy = types.ModuleType('arcpy')
        arcpy.mapping = types.SimpleNamespace(
            MapDocument=lambda target: self.mxd,
            ListDataFrames=lambda mxd: self.frames,
            ListLayers=lambda mxd, wildcard, df: df.layers)
        arcpy.RefreshActiveView = lambda: self.refreshes.append('view')
        arcpy.RefreshTOC = lambda: self.refreshes.append('toc')
        sys.modules['arcpy'] = arcpy
        for name in ('core', 'features'):
            module = types.ModuleType(name)
            module.__path__ = [str(BRIDGE / name)]
            sys.modules[name] = module
        # Execute real configuration code with an isolated locator path; no installed config is read.
        config = types.ModuleType('core.config')
        config.__file__ = str(self.fixture / 'bridge/core/config.py')
        config.__package__ = 'core'
        sys.modules['core.config'] = config
        source = BRIDGE / 'core/config.py'
        exec(compile(source.read_bytes(), str(source), 'exec'), config.__dict__)
        config.AGENT['allow_live_write'] = True
        self.config = config
        self.current_map = importlib.import_module('core.current_map')
        self.layers = importlib.import_module('features.layers')

    def restore_modules(self):
        for key in list(sys.modules):
            if any(key == p or key.startswith(p + '.') for p in ('core', 'features', 'arcpy')):
                del sys.modules[key]
        sys.modules.update(self.saved_modules)

    def restore_environment(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def test_visibility_rejects_duplicate_names_before_mutation(self):
        first, second = Layer('roads'), Layer('roads')
        self.frames = [Frame('Map', first, second)]
        result = self.layers.set_layer_visibility({'layer_name': 'roads', 'visible': False})
        self.assertFalse(result['ok'])
        self.assertIn('LAYER_AMBIGUOUS', result['error'])
        self.assertEqual([], first.writes + second.writes)
        self.assertEqual([], self.refreshes)


    def test_duplicate_named_frames_are_ambiguous_even_with_one_layer_match(self):
        first = Layer('roads')
        self.frames = [Frame('Map', first), Frame('Map', Layer('rivers'))]
        result = self.layers.set_layer_visibility(
            {'layer_name': 'roads', 'data_frame': 'Map', 'visible': False})
        self.assertFalse(result['ok'])
        self.assertIn('DATA_FRAME_AMBIGUOUS', result['error'])
        self.assertEqual([], first.writes)
        self.assertEqual([], self.refreshes)

    def test_unscoped_duplicates_across_frames_are_ambiguous(self):
        first, second = Layer('roads'), Layer('roads')
        self.frames = [Frame('Map', first), Frame('Inset', second)]
        result = self.layers.set_layer_visibility({'layer_name': 'roads', 'visible': False})
        self.assertFalse(result['ok'])
        self.assertIn('LAYER_AMBIGUOUS', result['error'])
        self.assertEqual([], first.writes + second.writes)
        self.assertEqual([], self.refreshes)

    def test_unique_scoped_visibility_preserves_response(self):
        first, second = Layer('roads'), Layer('roads')
        self.frames = [Frame('Map', first), Frame('Inset', second)]
        result = self.layers.set_layer_visibility(
            {'layer_name': 'roads', 'data_frame': 'Inset', 'visible': False})
        self.assertEqual({'ok': True, 'saved': False, 'matches': [
            {'name': 'roads', 'data_frame': 'Inset', 'visible': False}]}, result)
        self.assertEqual([], first.writes)
        self.assertEqual([('visible', False)], second.writes)
        self.assertEqual(['view', 'toc'], self.refreshes)

    def test_find_layer_keeps_all_matches_in_a_list(self):
        first, second = Layer('roads'), Layer('roads')
        frame = Frame('Map', first, second)
        self.frames = [frame]
        self.assertEqual([(frame, first), (frame, second)],
                         self.current_map.find_layer(self.mxd, 'roads'))
        self.assertEqual([], self.current_map.find_layer(self.mxd, 'missing'))

    def test_resolver_not_found_is_deterministic(self):
        self.frames = [Frame('Map', Layer('roads'))]
        with self.assertRaisesRegex(RuntimeError, '^LAYER_NOT_FOUND: missing$'):
            self.current_map.resolve_unique_layer(self.mxd, 'missing')


    def test_definition_query_resolves_before_any_duplicate_mutation(self):
        for layout, scope in (
                ('same_frame', 'Map'), ('different_frames', ''), ('duplicate_frames', 'Map')):
            with self.subTest(layout=layout):
                first, second = Layer('roads'), Layer('roads')
                if layout == 'same_frame':
                    self.frames = [Frame('Map', first, second)]
                else:
                    self.frames = [Frame('Map', first),
                                   Frame('Map' if layout == 'duplicate_frames' else 'Inset', second)]
                result = self.layers.set_definition_query(
                    {'layer_name': 'roads', 'data_frame': scope, 'definition_query': 'id > 1'})
                self.assertFalse(result['ok'])
                self.assertIn('AMBIGUOUS', result['error'])
                self.assertEqual([], first.writes + second.writes)
                self.assertEqual([], self.refreshes)

    def test_unique_scoped_definition_query_preserves_response(self):
        first, second = Layer('roads'), Layer('roads')
        self.frames = [Frame('Map', first), Frame('Inset', second)]
        result = self.layers.set_definition_query(
            {'layer_name': 'roads', 'data_frame': 'Inset', 'definition_query': 'id > 1'})
        self.assertEqual({'ok': True, 'saved': False, 'matches': [
            {'name': 'roads', 'data_frame': 'Inset', 'definition_query': 'id > 1'}]}, result)
        self.assertEqual([], first.writes)
        self.assertEqual([('definition_query', 'id > 1')], second.writes)
        self.assertEqual(['view', 'toc'], self.refreshes)


    def test_unsupported_definition_query_returns_explicit_error_without_refresh(self):
        target = Layer('roads', supported=False)
        self.frames = [Frame('Map', target)]
        result = self.layers.set_definition_query({'layer_name': 'roads', 'definition_query': 'id > 1'})
        self.assertFalse(result['ok'])
        self.assertIn('DEFINITION_QUERY_UNSUPPORTED', result.get('error', ''))
        self.assertEqual([], target.writes)
        self.assertEqual([], self.refreshes)


    def test_definition_query_arcpy_errors_are_explicit_failed_results(self):
        for stage in ('supports', 'query'):
            with self.subTest(stage=stage):
                target = Layer('roads', failure=stage)
                self.frames = [Frame('Map', target)]
                try:
                    result = self.layers.set_definition_query(
                        {'layer_name': 'roads', 'definition_query': 'id > 1'})
                except Exception as exc:
                    self.fail('Expected failed result, not escaped ArcPy error: ' + str(exc))
                self.assertFalse(result['ok'])
                self.assertIn('DEFINITION_QUERY_FAILED', result.get('error', ''))
                self.assertEqual([], self.refreshes)


    def test_empty_definition_query_target_never_selects_unnamed_layer(self):
        target = Layer('')
        self.frames = [Frame('Map', target)]
        result = self.layers.set_definition_query({'definition_query': 'id > 1'})
        self.assertFalse(result['ok'])
        self.assertIn('LAYER_NAME_REQUIRED', result.get('error', ''))
        self.assertEqual([], target.writes)
        self.assertEqual([], self.refreshes)
        with self.assertRaisesRegex(RuntimeError, '^LAYER_NAME_REQUIRED:'):
            self.current_map.resolve_unique_layer(self.mxd, '')

    def test_write_safety_gate_remains_before_map_access(self):
        self.config.AGENT['allow_live_write'] = False
        def forbidden_map_access(target):
            self.fail('Disabled live writes must not access CURRENT')
        sys.modules['arcpy'].mapping.MapDocument = forbidden_map_access
        for handler in (self.layers.set_layer_visibility, self.layers.set_definition_query):
            result = handler({'layer_name': 'roads'})
            self.assertFalse(result['ok'])
            self.assertTrue(result['blocked'])
        self.assertEqual([], self.refreshes)

    def test_not_found_targets_never_fall_back_to_other_frames(self):
        target = Layer('roads')
        self.frames = [Frame('Map', target)]
        for handler in (self.layers.set_layer_visibility, self.layers.set_definition_query):
            for command in ({'layer_name': 'missing'},
                            {'layer_name': 'roads', 'data_frame': 'Missing'}):
                with self.subTest(handler=handler.__name__, command=command):
                    result = handler(command)
                    self.assertFalse(result['ok'])
                    self.assertIn('LAYER_NOT_FOUND', result['error'])
                    self.assertEqual([], target.writes)
                    self.assertEqual([], self.refreshes)

    def test_definition_query_can_be_cleared_on_unique_target(self):
        target = Layer('roads')
        target._query = 'id > 1'
        self.frames = [Frame('Map', target)]
        result = self.layers.set_definition_query({'layer_name': 'roads', 'definition_query': ''})
        self.assertTrue(result['ok'])
        self.assertEqual('', target.definitionQuery)
        self.assertFalse(result['saved'])

    def test_resolver_returns_actual_pair_without_case_folding(self):
        target = Layer('Roads')
        frame = Frame('Map', target)
        self.frames = [frame]
        self.assertEqual((frame, target), self.current_map.resolve_unique_layer(self.mxd, 'Roads', 'Map'))
        with self.assertRaisesRegex(RuntimeError, '^LAYER_NOT_FOUND:'):
            self.current_map.resolve_unique_layer(self.mxd, 'roads', 'Map')

    def test_group_path_does_not_disambiguate_duplicate_display_names(self):
        first, second = Layer('roads'), Layer('roads')
        first.longName, second.longName = 'GroupA\\roads', 'GroupB\\roads'
        self.frames = [Frame('Map', first, second)]
        with self.assertRaisesRegex(RuntimeError, '^LAYER_AMBIGUOUS: roads \\(2 matches\\)$'):
            self.current_map.resolve_unique_layer(self.mxd, 'roads', 'Map')
        self.assertEqual([], first.writes + second.writes)

    def test_unicode_target_names_are_preserved(self):
        target = Layer('jalan_\\u00e9')
        self.frames = [Frame('Peta_\\u00e9', target)]
        result = self.layers.set_layer_visibility({'layer_name': target.name, 'visible': False})
        self.assertTrue(result['ok'])
        self.assertEqual(target.name, result['matches'][0]['name'])
        missing = self.layers.set_definition_query({'layer_name': 'hilang_\\u00e9'})
        self.assertIn('hilang_\\u00e9', missing['error'])

    def test_actual_registry_uses_changed_handlers(self):
        registry = importlib.import_module('core.registry')
        self.assertIs(self.layers.set_layer_visibility, registry.get('set_layer_visibility'))
        self.assertIs(self.layers.set_definition_query, registry.get('set_definition_query'))


if __name__ == '__main__':
    unittest.main()

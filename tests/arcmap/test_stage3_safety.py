"""Stage3 service-boundary fixtures: no ArcPy or live IPC is invoked."""
import os
import sys
import time
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'agents' / 'arcmap' / 'engine'
def setUpModule():
    global TEMP, services, request_context, tools
    from contextlib import ExitStack
    stack = ExitStack()
    unittest.addModuleCleanup(stack.close)
    prefixes = ('mcp_server', 'stage3')
    def owned(name):
        return any(name == p or name.startswith(p + '.') for p in prefixes)
    saved = {k: v for k, v in sys.modules.items() if owned(k)}
    def restore_modules():
        for key in list(sys.modules):
            if owned(key):
                del sys.modules[key]
        sys.modules.update(saved)
    stack.callback(restore_modules)
    for key in saved:
        del sys.modules[key]
    old_bytecode = sys.dont_write_bytecode
    stack.callback(setattr, sys, 'dont_write_bytecode', old_bytecode)
    sys.dont_write_bytecode = True
    old_path = sys.path[:]
    stack.callback(setattr, sys, 'path', old_path)
    (ROOT / '_validation').mkdir(parents=True, exist_ok=True)
    TEMP = tempfile.TemporaryDirectory(prefix='stage3-safety-', dir=ROOT / '_validation')
    stack.enter_context(TEMP)
    # Import against disposable roots, never installed identity/configuration.
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('ZAGENT_', 'ARCMAP_'))}
    environment.update({
        'ZAGENT_ARCMAP_ENGINE_ROOT': str(ENGINE),
        'ZAGENT_ARCMAP_DATA_ROOT': TEMP.name,
        'ZAGENT_ARCMAP_CONFIG_DIR': str(Path(TEMP.name) / 'config'),
        'ZAGENT_ARCMAP_IPC_ROOT': str(Path(TEMP.name) / 'ipc'),
    })
    stack.enter_context(patch.dict(os.environ, environment, clear=True))
    sys.path.insert(0, str(ENGINE))
    from mcp_server import services, request_context, execution_context
    # Restore both ContextVars even if a later import/setup step fails.
    stack.callback(request_context.correlation.reset, request_context.correlation.set({}))
    stack.callback(execution_context.CURRENT.reset, execution_context.CURRENT.set(None))
    from stage3 import mcp_tools as tools


class Stage3Safety(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.context = {'document_id': 'fixture-document', 'bridge_instance_id': 'fixture-bridge'}
        self.svc = services.AgentServices()
        self.old_namespace = tools._RUNTIME_NAMESPACE
        tools._RUNTIME_NAMESPACE = {'services': self.svc}
        self.addCleanup(setattr, tools, '_RUNTIME_NAMESPACE', self.old_namespace)
        self.config = patch.dict(services.AGENT, {
            'allow_live_write': True, 'allow_save': True,
            'allow_destructive_operations': True, 'allow_geoprocessing': True,
            'allow_export': True,
        })
        self.config.start()
        self.addCleanup(self.config.stop)
        self.transport = patch.object(services, 'send_command', self.boundary)
        self.transport.start()
        self.addCleanup(self.transport.stop)
        raw_transport = patch.object(sys.modules['mcp_server.ipc_client'], 'send_command', self.boundary)
        raw_transport.start()
        self.addCleanup(raw_transport.stop)
        self.upstream = patch.object(services, '_UPSTREAM_READ_ONLY', False)
        self.upstream.start()
        self.addCleanup(self.upstream.stop)
        self.bind()

    def bind(self, **changes):
        ctx = {'principal_id': 'fixture-principal', 'workspace_id': 'fixture-workspace',
               'resource_id': 'fixture-arcmap', 'effective_access': 'read',
               'expires_at': time.time() + 60}
        ctx.update(changes)
        token = request_context.correlation.set(ctx)
        self.addCleanup(request_context.correlation.reset, token)

    def boundary(self, action, **payload):
        self.calls.append((action, payload))
        return {'ok': True, 'context': dict(self.context)}

    def test_read_context_cannot_create_text(self):
        with self.assertRaisesRegex(PermissionError, 'WRITE_SCOPE_REQUIRED'):
            tools.arcmap_stage3_create_text('fixture')
        self.assertEqual([], self.calls)


    def test_every_known_action_requires_authenticated_service_context(self):
        import inspect
        self.bind(principal_id='')
        self.assertEqual(20, len(tools.STAGE3_TOOL_NAMES))
        for name in tools.STAGE3_TOOL_NAMES:
            fn = getattr(tools, name)
            kwargs = {p.name: 'fixture' for p in inspect.signature(fn).parameters.values()
                      if p.default is inspect.Parameter.empty}
            with self.subTest(action=name):
                self.calls.clear()
                with self.assertRaisesRegex(PermissionError, 'AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED'):
                    fn(**kwargs)
                self.assertEqual([], self.calls)


    def test_dispatch_fails_closed_without_raw_transport_fallback(self):
        from types import SimpleNamespace
        for namespace, action in (({}, 'stage3_health'),
                                  ({'services': SimpleNamespace(send_command=self.boundary)}, 'stage3_health'),
                                  ({'services': self.svc}, 'stage3_unknown')):
            with self.subTest(action=action, service=bool(namespace)):
                tools._RUNTIME_NAMESPACE = namespace
                with self.assertRaisesRegex(RuntimeError, 'STAGE3_(SERVICE_REQUIRED|UNKNOWN_ACTION)'):
                    tools._send(action)
                self.assertEqual([], self.calls)


    def invoke(self, name, **overrides):
        import inspect
        fn = getattr(tools, name)
        kwargs = {p.name: 'fixture' for p in inspect.signature(fn).parameters.values()
                  if p.default is inspect.Parameter.empty}
        kwargs.update(overrides)
        return fn(**kwargs)

    def test_health_accepts_read_context_once(self):
        self.assertTrue(tools.arcmap_stage3_health()['ok'])
        self.assertEqual(['stage3_health'], [a for a, p in self.calls])

    def test_expired_context_rejects_every_action(self):
        self.bind(effective_access='write', expires_at=time.time() - 1)
        for name in tools.STAGE3_TOOL_NAMES:
            with self.subTest(action=name):
                with self.assertRaisesRegex(PermissionError, 'CONTEXT_EXPIRED_WHILE_QUEUED'):
                    self.invoke(name)
        self.assertEqual([], self.calls)

    def test_missing_context_fields_reject_before_transport(self):
        for key in ('principal_id', 'workspace_id', 'resource_id'):
            with self.subTest(field=key):
                self.bind(**{key: ''})
                with self.assertRaisesRegex(PermissionError, 'AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED'):
                    tools.arcmap_stage3_health()
        self.assertEqual([], self.calls)

    def test_successful_actions_dispatch_exactly_once(self):
        self.bind(effective_access='write')
        for name in tools.STAGE3_TOOL_NAMES:
            with self.subTest(action=name):
                self.calls.clear()
                self.assertTrue(self.invoke(name)['ok'])
                action = name[len('arcmap_'):]
                self.assertEqual(1, sum(a == action for a, p in self.calls))
                for a, payload in self.calls:
                    if a == action and action != 'stage3_health':
                        self.assertEqual(self.context, payload['_expected_context'])

    def test_operational_typeerror_after_effect_is_not_replayed(self):
        self.bind(effective_access='write')
        def effect_then_error(action, **payload):
            result = self.boundary(action, **payload)
            if action == 'stage3_create_text':
                raise TypeError('fixture operational error after effect')
            return result
        with patch.object(services, 'send_command', effect_then_error):
            with self.assertRaisesRegex(TypeError, 'operational error after effect'):
                tools.arcmap_stage3_create_text('fixture')
        self.assertEqual(['ping', 'stage3_create_text'], [a for a, p in self.calls])

    def test_upstream_read_only_blocks_mutation_before_transport(self):
        self.bind(effective_access='write')
        with patch.object(services, '_UPSTREAM_READ_ONLY', True):
            result = tools.arcmap_stage3_create_text('fixture')
        self.assertEqual('DEV_UPSTREAM_READ_ONLY', result['code'])
        self.assertEqual([], self.calls)

    def test_changed_document_prevents_action(self):
        self.bind(effective_access='write')
        result = tools._send('stage3_create_text', {'text': 'fixture', '_expected_context': {'document_id': 'old'}})
        self.assertEqual('CURRENT_MXD_CHANGED', result['code'])
        self.assertEqual(['ping'], [a for a, p in self.calls])

    def test_failed_readback_marks_possible_completed_action(self):
        self.bind(effective_access='write')
        def failed_readback(action, **payload):
            result = self.boundary(action, **payload)
            return {'ok': False, 'error': 'fixture observation failed'} if action == 'inspect_current_map' else result
        with patch.object(services, 'send_command', failed_readback):
            result = tools.arcmap_stage3_create_text('fixture')
        self.assertFalse(result['ok'])
        self.assertEqual('POST_ACTION_VERIFICATION_FAILED', result['code'])
        self.assertTrue(result['action_may_have_completed'])
        self.assertEqual('FAILED', result['verification']['status'])
        self.assertFalse(result['verification']['saved'])
        self.assertEqual(['ping', 'stage3_create_text', 'inspect_current_map'], [a for a, p in self.calls])

    def test_composite_build_requires_save_permission_before_any_transport(self):
        self.bind(effective_access='write')
        with patch.dict(services.AGENT, {'allow_save': False}):
            result = tools.arcmap_stage3_build_no_data_a4('fixture')
        self.assertFalse(result['ok'])
        self.assertTrue(result['blocked'])
        self.assertIn('save', result['error'])
        self.assertEqual([], self.calls)


    def test_each_composite_effect_honors_its_safety_gate(self):
        self.bind(effective_access='write')
        cases = [
            ('arcmap_stage3_blank_init', 'allow_destructive_operations', 'destructive'),
            ('arcmap_stage3_build_blank_a4', 'allow_destructive_operations', 'destructive'),
            ('arcmap_stage3_build_no_data_a4', 'allow_destructive_operations', 'destructive'),
            ('arcmap_stage3_build_blank_a4', 'allow_export', 'export'),
            ('arcmap_stage3_build_no_data_a4', 'allow_export', 'export'),
            ('arcmap_stage3_restore_checkpoint', 'allow_save', 'save'),
        ]
        for name, flag, kind in cases:
            with self.subTest(action=name, gate=flag):
                self.calls.clear()
                with patch.dict(services.AGENT, {flag: False}):
                    result = self.invoke(name)
                self.assertFalse(result['ok'])
                self.assertTrue(result['blocked'])
                self.assertIn(kind, result['error'])
                self.assertEqual([], self.calls)


    def test_every_mutating_action_requires_write_context(self):
        for name in tools.STAGE3_TOOL_NAMES:
            if name == 'arcmap_stage3_health':
                continue
            with self.subTest(action=name):
                with self.assertRaisesRegex(PermissionError, 'WRITE_SCOPE_REQUIRED'):
                    self.invoke(name)
        self.assertEqual([], self.calls)

    def test_all_primary_operation_kinds_use_real_safety_policy(self):
        self.bind(effective_access='write')
        special = {
            'arcmap_stage3_create_featureclass': ('allow_geoprocessing', 'geoprocessing'),
            'arcmap_stage3_create_xy_featureclass': ('allow_geoprocessing', 'geoprocessing'),
            'arcmap_stage3_create_geometry_features': ('allow_geoprocessing', 'geoprocessing'),
            'arcmap_stage3_save_checkpoint': ('allow_save', 'save'),
            'arcmap_stage3_restore_checkpoint': ('allow_destructive_operations', 'destructive'),
            'arcmap_stage3_export_current': ('allow_export', 'export'),
        }
        for name in tools.STAGE3_TOOL_NAMES:
            if name == 'arcmap_stage3_health':
                continue
            flag, kind = special.get(name, ('allow_live_write', 'live_write'))
            with self.subTest(action=name, kind=kind):
                with patch.dict(services.AGENT, {flag: False}):
                    result = self.invoke(name)
                self.assertTrue(result['blocked'])
                self.assertIn(kind, result['error'])
                self.assertEqual([], self.calls)

    def test_unused_composite_effects_do_not_require_permission(self):
        self.bind(effective_access='write')
        with patch.dict(services.AGENT, {'allow_destructive_operations': False}):
            self.assertTrue(tools.arcmap_stage3_blank_init(clear_layers=False)['ok'])
        with patch.dict(services.AGENT, {'allow_save': False, 'allow_export': False}):
            self.assertTrue(tools.arcmap_stage3_build_no_data_a4(
                'fixture', save_mxd=False, export_pdf=False, export_png=False)['ok'])

    def test_real_service_lock_serializes_stage3_calls(self):
        import threading
        self.bind(effective_access='write')
        ctx = request_context.current()
        active = [0, 0]
        gate = threading.Lock()
        failures = []
        def slow_boundary(action, **payload):
            with gate:
                active[0] += 1
                active[1] = max(active)
            try:
                time.sleep(.01)
                return self.boundary(action, **payload)
            finally:
                with gate:
                    active[0] -= 1
        def worker():
            token = request_context.correlation.set(dict(ctx))
            try:
                self.assertTrue(tools.arcmap_stage3_create_text('fixture')['ok'])
            except Exception as exc:
                failures.append(repr(exc))
            finally:
                request_context.correlation.reset(token)
        with patch.object(services, 'send_command', slow_boundary):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual([], failures)
        self.assertEqual(1, active[1])
        self.assertEqual(2, sum(a == 'stage3_create_text' for a, p in self.calls))

    def test_readback_transport_failure_keeps_completed_action_warning(self):
        self.bind(effective_access='write')
        def readback_error(action, **payload):
            result = self.boundary(action, **payload)
            if action == 'inspect_current_map':
                raise services.ArcMapBridgeError('fixture readback unavailable')
            return result
        with patch.object(services, 'send_command', readback_error):
            result = tools.arcmap_stage3_create_text('fixture')
        self.assertFalse(result['ok'])
        self.assertEqual('POST_ACTION_VERIFICATION_FAILED', result.get('code'))
        self.assertTrue(result.get('action_may_have_completed'))
        self.assertEqual('FAILED', result['verification']['status'])
        self.assertEqual(['ping', 'stage3_create_text', 'inspect_current_map'], [a for a, p in self.calls])


if __name__ == '__main__':
    unittest.main()

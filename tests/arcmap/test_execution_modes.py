"""Source/SDK routing fixtures; no ArcPy, live bridge, or private config."""
import asyncio
from contextlib import ExitStack
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / 'agents/arcmap/engine'
PREFIXES = ('mcp_server', 'stage3', 'orchestrator')


def owned(name):
    return any(name == p or name.startswith(p + '.') for p in PREFIXES)


def setUpModule():
    global TEMP, server, services, request_context, execution_context
    stack = ExitStack()
    unittest.addModuleCleanup(stack.close)
    saved = {k: v for k, v in sys.modules.items() if owned(k)}
    def restore():
        for key in list(sys.modules):
            if owned(key):
                del sys.modules[key]
        sys.modules.update(saved)
    stack.callback(restore)
    for key in saved:
        del sys.modules[key]
    old_path = sys.path[:]
    stack.callback(setattr, sys, 'path', old_path)
    old_bytecode = sys.dont_write_bytecode
    stack.callback(setattr, sys, 'dont_write_bytecode', old_bytecode)
    sys.dont_write_bytecode = True
    (ROOT / '_validation').mkdir(exist_ok=True)
    TEMP = tempfile.TemporaryDirectory(prefix='mode-routing-', dir=ROOT / '_validation')
    stack.enter_context(TEMP)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith(('ZAGENT_', 'ARCMAP_'))}
    environment.update({
        'ZAGENT_ARCMAP_ENGINE_ROOT': str(Path(TEMP.name) / 'engine'),
        'ZAGENT_ARCMAP_DATA_ROOT': str(Path(TEMP.name) / 'data'),
        'ZAGENT_ARCMAP_CONFIG_DIR': str(Path(TEMP.name) / 'config'),
        'ZAGENT_ARCMAP_IPC_ROOT': str(Path(TEMP.name) / 'ipc'),
        'ZAGENT_VISUAL_ROOT': str(Path(TEMP.name) / 'visual'),
        'ZAGENT_DEVICE_ID': 'fixture-device',
        'ZAGENT_INTERNAL_TOKEN': 'fixture-internal-token-not-a-secret-123456',
        'ZAGENT_WORKFLOW_RUNTIME_URL': 'http://127.0.0.1:1',
    })
    stack.enter_context(patch.dict(os.environ, environment, clear=True))
    sys.path.insert(0, str(ENGINE))
    services = importlib.import_module('mcp_server.services')
    request_context = importlib.import_module('mcp_server.request_context')
    execution_context = importlib.import_module('mcp_server.execution_context')
    stack.callback(request_context.correlation.reset, request_context.correlation.set({}))
    stack.callback(execution_context.CURRENT.reset, execution_context.CURRENT.set(None))
    def forbidden(*args, **kwargs):
        raise AssertionError('LIVE_TRANSPORT_FORBIDDEN')
    stack.enter_context(patch.object(services, 'send_command', forbidden))
    stack.enter_context(patch.object(sys.modules['mcp_server.ipc_client'], 'send_command', forbidden))
    stack.enter_context(patch.object(services, 'send_command_via', forbidden))
    server = importlib.import_module('mcp_server.server')


def raw_context(**changes):
    raw = {'context_version': 1, 'principal_id': 'fixture-principal',
           'workspace_id': 'fixture-workspace', 'device_id': 'fixture-device',
           'operation_id': 'fixture-operation', 'request_id': 'fixture-request',
           'trace_id': 'fixture-trace', 'deadline': time.time() + 60,
           'effective_access': 'read',
           'effective_resources': [{'kind': 'arcmap', 'resource_id': 'fixture-arcmap'}]}
    raw.update(changes)
    return raw


def decoded(result):
    if hasattr(result, 'content'):
        result = result.content
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        return json.loads(result[0].text)
    return result


class Routing(unittest.TestCase):
    def test_unknown_action_arguments_are_rejected_by_actual_sdk_before_dispatch(self):
        for name, args in (('arcmap_inspect_map', {'mode': 'attached', 'action': 'export'}),
                           ('arcmap_execution_capabilities', {'action': 'mutate'})):
            with self.subTest(name=name):
                with self.assertRaises(Exception):
                    self.invoke(name, args)
        self.assertEqual([], self.calls)

    def test_both_modes_and_capabilities_reject_invalid_sdk_authority_before_effects(self):
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        bad = ({'principal_id': ''}, {'workspace_id': ''}, {'device_id': 'other'},
               {'deadline': time.time() - 1}, {'effective_access': 'none'},
               {'effective_resources': []},
               {'effective_resources': [{'kind': 'files', 'resource_id': 'fixture-files'}]},
               {'effective_resources': [{'kind': 'arcmap', 'resource_id': 'one'},
                                        {'kind': 'arcmap', 'resource_id': 'two'}]})
        with patch.object(worker_module, 'ArcGISProcessFileWorker') as factory:
            for name, args in (('arcmap_inspect_map', {'mode': 'headless', 'mxd_path': 'CURRENT'}),
                               ('arcmap_inspect_map', {'mode': 'attached'}),
                               ('arcmap_execution_capabilities', {})):
                for changes in bad:
                    with self.subTest(name=name, args=args, changes=changes):
                        with self.assertRaises(PermissionError):
                            self.invoke(name, args, raw_context(**changes))
                with self.assertRaises(PermissionError):
                    asyncio.run(server.mcp.call_tool(name, args, None))
            factory.assert_not_called()
        self.assertEqual([], self.calls)

    def test_raw_backend_failures_remain_failures_without_cross_lane_fallback(self):
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        path = Path(TEMP.name) / 'failure.mxd'
        path.write_bytes(b'fixture')
        raw = {'ok': False, 'code': 'REAL_BACKEND_FAILURE', 'error': 'fixture-detail', 'partial': True}
        from types import SimpleNamespace
        calls = []
        def inspect_mxd(*, mxd_path):
            calls.append(mxd_path)
            return raw
        with patch.object(worker_module, 'ArcGISProcessFileWorker', return_value=SimpleNamespace(inspect_mxd=inspect_mxd)):
            disk = self.invoke(arguments={'mode': 'headless', 'mxd_path': str(path)})
            self.assertFalse(disk['ok'])
            self.assertEqual(raw, disk['data'])
            self.assertEqual([str(path)], calls)
            self.assertEqual([], self.calls)
            self.reply = raw
            live = self.invoke(arguments={'mode': 'attached'})
            self.assertFalse(live['ok'])
            self.assertEqual('REAL_BACKEND_FAILURE', live['data']['code'])
            self.assertEqual('fixture-detail', live['data']['error'])
            self.assertEqual([('inspect_current_map', {})], self.calls)
            self.assertEqual([str(path)], calls)
            self.assertIsNone(live['target']['context'])

    def test_operational_typeerror_is_not_retried_or_rerouted(self):
        from mcp_server.execution_modes import inspect_map
        from types import SimpleNamespace
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        path = Path(TEMP.name) / 'exception.mxd'
        path.write_bytes(b'fixture')
        self.addCleanup(request_context.correlation.reset, request_context.correlation.set(self.verified()))
        disk_calls = []
        def fail_disk(*, mxd_path):
            disk_calls.append(mxd_path)
            raise TypeError('disk operational error')
        def fail_live(action, **payload):
            self.calls.append((action, payload))
            raise TypeError('live operational error')
        with patch.object(worker_module, 'ArcGISProcessFileWorker', return_value=SimpleNamespace(inspect_mxd=fail_disk)):
            with self.assertRaisesRegex(TypeError, 'disk operational error'):
                inspect_map(server.services, 'headless', str(path))
            self.assertEqual([str(path)], disk_calls)
            self.assertEqual([], self.calls)
            with patch.object(services, 'send_command', fail_live):
                with self.assertRaisesRegex(TypeError, 'live operational error'):
                    inspect_map(server.services, 'attached')
            self.assertEqual([('inspect_current_map', {})], self.calls)
            self.assertEqual([str(path)], disk_calls)

    def test_expiry_is_checked_after_acquiring_shared_lock(self):
        from contextlib import contextmanager
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        ctx = self.verified()
        self.addCleanup(request_context.correlation.reset, request_context.correlation.set(ctx))
        actual_lock = services._HEADLESS_LOCK
        @contextmanager
        def queued_lock():
            with actual_lock:
                ctx['expires_at'] = 0
                yield
        with patch.object(services, '_HEADLESS_LOCK', queued_lock()), patch.object(worker_module, 'ArcGISProcessFileWorker') as factory:
            with self.assertRaisesRegex(PermissionError, 'CONTEXT_EXPIRED_WHILE_QUEUED'):
                server.services.inspect_mxd(mxd_path='CURRENT')
            factory.assert_not_called()
        self.assertEqual([], self.calls)

    def test_unknown_public_action_cannot_dispatch(self):
        from mcp.server import MCPServer
        with self.assertRaises(Exception):
            self.invoke('arcmap_export_map', {'mode': 'headless'}, raw_context(effective_access='write'))
        self.assertEqual([], self.calls)

    def test_fixture_discovery_and_setup_cleanup_restore_owned_state(self):
        import importlib.util
        def state():
            return (dict(os.environ), sys.path[:], sys.dont_write_bytecode,
                    {k: v for k, v in sys.modules.items() if owned(k)},
                    set((ROOT / '_validation').glob('mode-routing-*')),
                    request_context.correlation.get(), execution_context.CURRENT.get())
        for failure in (False, True):
            before = state()
            spec = importlib.util.spec_from_file_location('mode_fixture_cleanup_probe', __file__)
            clone = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(clone)
            self.assertEqual(before, state())
            cleanups = []
            original_import = importlib.import_module
            def imported(name, *args, **kwargs):
                if failure and name == 'mcp_server.server':
                    raise RuntimeError('INJECTED_LATE_FIXTURE_FAILURE')
                return original_import(name, *args, **kwargs)
            try:
                with patch.object(unittest, 'addModuleCleanup', lambda fn: cleanups.append(fn)), patch.object(importlib, 'import_module', imported):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError, 'INJECTED_LATE_FIXTURE_FAILURE'):
                            clone.setUpModule()
                    else:
                        clone.setUpModule()
            finally:
                for cleanup in reversed(cleanups):
                    cleanup()
            self.assertEqual(before, state())

    def test_sdk_lists_both_new_tools_as_read_only_and_nondestructive(self):
        listing = asyncio.run(server.mcp.list_tools())
        if hasattr(listing, 'tools'):
            listing = listing.tools
        tools = {t.name: t for t in listing}
        for name in ('arcmap_execution_capabilities', 'arcmap_inspect_map'):
            self.assertIsNotNone(tools[name].annotations)
            self.assertIs(True, tools[name].annotations.read_only_hint)
            self.assertIs(False, tools[name].annotations.destructive_hint)

    def test_capabilities_is_registered_read_only_and_truthful_about_mvp(self):
        self.assertIn('arcmap_execution_capabilities', server._registered_tool_names(server.mcp))
        result = self.invoke('arcmap_execution_capabilities')
        self.assertTrue(result['ok'], result)
        self.assertEqual('source_only', result['status'])
        self.assertFalse(result['deployment_verified'])
        self.assertEqual(['headless', 'attached'], result['operations']['inspect_map']['modes'])
        for action in ('mutation', 'ui_control'):
            self.assertFalse(result['operations'][action]['supported'])
        export = result['operations']['export']
        self.assertTrue(export['supported'])
        self.assertEqual(['headless'], export['modes'])
        self.assertFalse(export['attached_supported'])
        self.assertFalse(export['print_ready_accepted_by_export'])
        self.assertEqual(['print_ready_template'], export['operations'])
        self.assertFalse(result['filesystem_sandbox'])
        self.assertEqual([], self.calls)

    def test_public_capabilities_and_headless_progress_while_desktop_ping_is_blocked(self):
        """Real SDK ingress must not queue disk inspection behind an offline UI ping."""
        import threading
        from types import SimpleNamespace
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        path = Path(TEMP.name) / 'desktop-offline.mxd'
        path.write_bytes(b'synthetic-disk-mxd')
        entered, release = threading.Event(), threading.Event()
        cap_done, disk_done = threading.Event(), threading.Event()
        results, worker_calls, threads = {}, [], []

        def stuck_bridge(action, **kwargs):
            if action != 'ping':
                raise AssertionError('UNEXPECTED_DESKTOP_BRIDGE_CALL')
            entered.set()
            if not release.wait(8):
                raise AssertionError('FIXTURE_PING_RELEASE_TIMEOUT')
            return {'ok': False, 'code': 'DESKTOP_OFFLINE'}

        def inspect_disk(*, mxd_path):
            worker_calls.append(mxd_path)
            return {'ok': True, 'document_path': mxd_path, 'frames': []}

        def invoke(label, name, arguments, done):
            try:
                results[label] = self.invoke(name, arguments)
            except BaseException as exc:
                results[label] = exc
            finally:
                done.set()

        with patch.object(services, 'send_command', stuck_bridge), patch.object(
                worker_module, 'ArcGISProcessFileWorker',
                return_value=SimpleNamespace(inspect_mxd=inspect_disk)):
            try:
                ping = threading.Thread(
                    target=invoke, args=('ping', 'arcmap_ping', {}, threading.Event()),
                    daemon=True)
                threads.append(ping)
                ping.start()
                self.assertTrue(entered.wait(3), 'Desktop ping did not enter bridge IPC')
                for label, tool, arguments, done in (
                    ('capabilities', 'arcmap_execution_capabilities', {}, cap_done),
                    ('headless', 'arcmap_inspect_map',
                     {'mode': 'headless', 'mxd_path': str(path)}, disk_done)):
                    thread = threading.Thread(
                        target=invoke, args=(label, tool, arguments, done),
                        daemon=True)
                    threads.append(thread)
                    thread.start()
                self.assertTrue(cap_done.wait(2), 'Capabilities blocked on Desktop IPC lock')
                self.assertTrue(disk_done.wait(2), 'Headless blocked on Desktop IPC lock')
                self.assertIsInstance(results['capabilities'], dict, results['capabilities'])
                self.assertTrue(results['capabilities']['ok'])
                self.assertIsInstance(results['headless'], dict, results['headless'])
                self.assertTrue(results['headless']['ok'])
                self.assertEqual([str(path)], worker_calls)
                self.assertEqual(b'synthetic-disk-mxd', path.read_bytes())
                self.assertEqual([], self.calls)
            finally:
                release.set()
                for thread in threads:
                    thread.join(timeout=3)
                    self.assertFalse(thread.is_alive(), 'Fixture thread did not exit')

    def test_headless_timeout_metadata_does_not_expand_attached_timeout(self):
        """Metadata names only Headless; public tool input stays mode-only."""
        listing = asyncio.run(server.mcp.list_tools())
        if hasattr(listing, 'tools'):
            listing = listing.tools
        tool = {item.name: item for item in listing}['arcmap_inspect_map']
        schema = tool.model_dump(by_alias=True)
        self.assertNotIn('timeout_seconds', schema['inputSchema']['properties'])
        self.assertEqual(
            {'headless': 60},
            schema['_meta']['zagent.mode_worker_timeout_seconds'])
        with self.assertRaises(Exception):
            self.invoke('arcmap_inspect_map', {
                'mode': 'headless', 'mxd_path': 'CURRENT', 'timeout_seconds': 120})
        self.assertEqual([], self.calls)

    def test_router_applies_mode_timeout_only_to_headless(self):
        """Exercise the real Router timeout helper without importing its HTTP stack."""
        import ast
        from types import SimpleNamespace
        from typing import Any
        router_path = ROOT / 'agents/tunnel/engine/router/registry.py'
        tree = ast.parse(router_path.read_text(encoding='utf-8'))
        helper = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name == '_tool_call_timeout_seconds')
        globals_for_helper = {
            'Any': Any,
            '_LONG_CALL_TIMEOUT_MARGIN_SECONDS': 15.0,
            '_MAX_LONG_CALL_TIMEOUT_SECONDS': 1830.0,
        }
        exec(compile(ast.Module(body=[helper], type_ignores=[]),
                     str(router_path), 'exec'), globals_for_helper)
        calculate = globals_for_helper['_tool_call_timeout_seconds']
        state = SimpleNamespace(service={'timeout_seconds': 25})
        tool = {'name': 'arcmap_inspect_map',
                '_meta': {'zagent.mode_worker_timeout_seconds': {'headless': 60}},
                'inputSchema': {'properties': {}}}
        self.assertEqual(75, calculate(state, tool, {'mode': 'headless'}))
        self.assertIsNone(calculate(state, tool, {'mode': 'attached'}))
        self.assertIsNone(calculate(state, tool, {'mode': 'unknown'}))
        self.assertIsNone(calculate(state, tool, {}))

    def test_concurrent_headless_requests_still_serialize_arcgis_worker(self):
        """Separate Desktop lock must not allow overlapping ArcPy file workers."""
        import threading
        from types import SimpleNamespace
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        first = Path(TEMP.name) / 'serialize-first.mxd'
        second = Path(TEMP.name) / 'serialize-second.mxd'
        first.write_bytes(b'first-fixture')
        second.write_bytes(b'second-fixture')
        entered, release, first_done, second_done = (
            threading.Event(), threading.Event(), threading.Event(), threading.Event())
        calls, outcomes, threads = [], {}, []

        def inspect_disk(*, mxd_path):
            calls.append(mxd_path)
            if mxd_path == str(first):
                entered.set()
                if not release.wait(8):
                    raise AssertionError('FIXTURE_RELEASE_TIMEOUT')
            return {'ok': True, 'document_path': mxd_path, 'frames': []}

        def invoke(label, path, done):
            try:
                outcomes[label] = self.invoke(
                    'arcmap_inspect_map', {'mode': 'headless', 'mxd_path': str(path)})
            except BaseException as exc:
                outcomes[label] = exc
            finally:
                done.set()

        with patch.object(worker_module, 'ArcGISProcessFileWorker',
                          return_value=SimpleNamespace(inspect_mxd=inspect_disk)):
            try:
                for label, path, done in (('first', first, first_done),
                                          ('second', second, second_done)):
                    if label == 'second':
                        self.assertTrue(entered.wait(3), 'First Headless worker did not start')
                    thread = threading.Thread(target=invoke, args=(label, path, done), daemon=True)
                    threads.append(thread)
                    thread.start()
                self.assertFalse(second_done.wait(0.3), 'ArcPy workers overlapped')
                self.assertEqual([str(first)], calls)
            finally:
                release.set()
                for thread in threads:
                    thread.join(timeout=3)
                    self.assertFalse(thread.is_alive(), 'Fixture thread did not exit')
        self.assertTrue(first_done.is_set())
        self.assertTrue(second_done.is_set())
        self.assertEqual([str(first), str(second)], calls)
        self.assertTrue(outcomes['first']['ok'], outcomes['first'])
        self.assertTrue(outcomes['second']['ok'], outcomes['second'])
        self.assertEqual([], self.calls)

    def verified(self):
        ctx = execution_context.verify(execution_context.TrustedMetadata(
            {'zagent.execution_context': raw_context()}), 'arcmap_inspect_map', {})
        ctx['resource_id'] = 'fixture-arcmap'
        return ctx

    def test_headless_service_rejects_unverified_wrong_resource_device_owner_or_expiry(self):
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        path = Path(TEMP.name) / 'authority.mxd'
        path.write_bytes(b'fixture')
        valid = self.verified()
        cases = [{}, dict(valid)]
        for changes in ({'effective_resources': [{'kind': 'files', 'resource_id': 'fixture-arcmap'}]},
                        {'resource_id': 'different'}, {'device_id': 'wrong-device'},
                        {'session_id': 'wrong-owner'}, {'expires_at': time.time() - 1},
                        {'effective_access': 'none'}):
            ctx = execution_context.VerifiedContext(valid)
            ctx.update(changes)
            cases.append(ctx)
        with patch.object(worker_module, 'ArcGISProcessFileWorker') as factory:
            for ctx in cases:
                with self.subTest(context=ctx):
                    token = request_context.correlation.set(ctx)
                    try:
                        with self.assertRaises(PermissionError):
                            server.services.inspect_mxd(mxd_path=str(path))
                    finally:
                        request_context.correlation.reset(token)
            factory.assert_not_called()
        self.assertEqual([], self.calls)

    def test_headless_read_routes_to_one_real_worker_boundary_without_ui(self):
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        path = Path(TEMP.name) / 'explicit.mxd'
        path.write_bytes(b'fixture-only-boundary')
        reply = {'ok': True, 'document_path': str(path), 'document': {'path': str(path), 'title': 'Disk'},
                 'frames': [], 'partial': False, 'warnings': []}
        from types import SimpleNamespace
        worker_calls = []
        def inspect_mxd(*, mxd_path):
            worker_calls.append(mxd_path)
            return reply
        with patch.object(worker_module, 'ArcGISProcessFileWorker', return_value=SimpleNamespace(inspect_mxd=inspect_mxd)) as factory:
            result = self.invoke(arguments={'mode': 'headless', 'mxd_path': str(path)})
        self.assertTrue(result['ok'], result)
        self.assertEqual([], self.calls)
        self.assertEqual([str(path)], worker_calls)
        factory.assert_called_once_with(ENGINE, timeout_seconds=300)
        self.assertEqual('headless', result['requested_mode'])
        self.assertEqual('headless', result['execution_lane'])
        self.assertEqual({'kind': 'disk_mxd', 'path': str(path)}, result['target'])
        self.assertEqual(reply, result['data'])
        self.assertEqual(b'fixture-only-boundary', path.read_bytes())

    def test_invalid_mode_and_target_mixes_never_reach_either_backend(self):
        from mcp_server.execution_modes import inspect_map
        ctx = execution_context.verify(execution_context.TrustedMetadata(
            {'zagent.execution_context': raw_context()}), 'arcmap_inspect_map', {})
        ctx['resource_id'] = 'fixture-arcmap'
        self.addCleanup(request_context.correlation.reset, request_context.correlation.set(ctx))
        cases = [({'mode': value}, 'INVALID_EXECUTION_MODE')
                 for value in ('', 'HEADLESS', 'Attached', 'auto', None, 1)]
        cases += [({'mode': 'attached', 'mxd_path': 'other.mxd'}, 'ATTACHED_DISK_TARGET_FORBIDDEN'),
                  ({'mode': 'headless', 'mxd_path': 'CURRENT'}, 'EXPLICIT_MXD_PATH_REQUIRED'),
                  ({'mode': 'headless', 'mxd_path': ''}, 'EXPLICIT_MXD_PATH_REQUIRED'),
                  ({'mode': 'headless', 'mxd_path': 'relative.mxd'}, 'ABSOLUTE_MXD_PATH_REQUIRED'),
                  ({'mode': 'headless', 'mxd_path': str(Path(TEMP.name) / 'bad.txt')}, 'MXD_SUFFIX_REQUIRED'),
                  ({'mode': 'headless', 'mxd_path': str(Path(TEMP.name) / 'missing.mxd')}, 'MXD_NOT_FOUND'),
                  ({'mode': 'headless', 'expected_context': {}}, 'HEADLESS_ATTACHED_CONTEXT_FORBIDDEN')]
        for args, code in cases:
            with self.subTest(args=args):
                result = inspect_map(server.services, **args)
                self.assertFalse(result['ok'], result)
                self.assertEqual(code, result['code'])
                self.assertIsNone(result['execution_lane'])
                self.assertEqual([], self.calls)

    def test_print_ready_contract_rejects_attached_and_read_only(self):
        listing = asyncio.run(server.mcp.list_tools())
        if hasattr(listing, 'tools'):
            listing = listing.tools
        tool = {item.name: item for item in listing}['arcmap_print_ready_template']
        self.assertIs(False, tool.annotations.read_only_hint)
        self.assertIs(False, tool.annotations.destructive_hint)
        self.assertEqual({'headless': 300},
                         tool.model_dump(by_alias=True)['_meta']['zagent.mode_worker_timeout_seconds'])
        args = {'mode': 'headless', 'template_mxd': 'C:/template.mxd',
                'data_root': 'C:/input', 'output_root': 'C:/output'}
        with self.assertRaises(PermissionError):
            self.invoke('arcmap_print_ready_template', args)
        with self.assertRaises(Exception):
            self.invoke('arcmap_print_ready_template',
                        dict(args, unexpected='forbidden'),
                        raw_context(effective_access='write'))
        result = self.invoke('arcmap_print_ready_template', dict(args, mode='attached'),
                             raw_context(effective_access='write'))
        self.assertFalse(result['ok'])
        self.assertEqual('HEADLESS_MODE_REQUIRED', result['code'])
        self.assertEqual([], self.calls)

    def test_print_ready_headless_dispatch_isolated_from_desktop(self):
        from types import SimpleNamespace
        worker_module = importlib.import_module('orchestrator.adapters.file_worker.arcgis_process')
        args = {'mode': 'headless', 'template_mxd': 'C:/template.mxd',
                'data_root': 'C:/input', 'output_root': 'C:/output'}
        records = []
        def print_disk(**kwargs):
            records.append(kwargs)
            return {'ok': True, 'execution_mode': 'headless',
                    'print_ready_accepted': False}
        with patch.object(worker_module, 'ArcGISProcessFileWorker',
                          return_value=SimpleNamespace(print_ready_template=print_disk)) as factory:
            with patch.object(server.services.safety, 'guard', return_value=None) as guard:
                result = self.invoke('arcmap_print_ready_template', args,
                                     raw_context(effective_access='write'))
            self.assertTrue(result['ok'], result)
            self.assertFalse(result['print_ready_accepted'])
            self.assertEqual(['headless_print_ready','export'],[x.args[0] for x in guard.call_args_list])
            factory.assert_called_once_with(ENGINE, timeout_seconds=300)
        self.assertEqual('C:/template.mxd', records[0]['template_mxd'])
        self.assertEqual(1,len(records))
        self.assertEqual([], self.calls)

    def setUp(self):
        self.calls = []
        self.observed = {'document_id': 'observed-document', 'bridge_instance_id': 'observed-bridge'}
        self.reply = {'ok': True, 'document': {'path': 'observed.mxd'}, 'context': self.observed}
        self.enterContext(patch.object(services, 'send_command', self.boundary))

    def boundary(self, action, **payload):
        self.calls.append((action, payload))
        return dict(self.reply)

    def invoke(self, name='arcmap_inspect_map', arguments=None, raw=None):
        from types import SimpleNamespace
        meta = execution_context.TrustedMetadata({'zagent.execution_context': raw or raw_context()})
        context = SimpleNamespace(request_context=SimpleNamespace(
            request=SimpleNamespace(headers={'x-zagent-internal-token': os.environ['ZAGENT_INTERNAL_TOKEN']}),
            meta=meta))
        return decoded(asyncio.run(server.mcp.call_tool(name, arguments or {}, context)))

    def test_attached_read_is_registered_and_dispatches_once_with_observed_target(self):
        self.assertIn('arcmap_inspect_map', server._registered_tool_names(server.mcp))
        result = self.invoke(arguments={'mode': 'attached', 'expected_context': self.observed})
        self.assertTrue(result['ok'], result)
        self.assertEqual([('inspect_current_map', {'_expected_context': self.observed})], self.calls)
        self.assertEqual('attached', result['requested_mode'])
        self.assertEqual('attached', result['execution_lane'])
        self.assertEqual(self.observed, result['target']['context'])
        self.assertEqual('CURRENT', result['target']['kind'])
        self.assertEqual('observed.mxd', result['data']['document']['path'])

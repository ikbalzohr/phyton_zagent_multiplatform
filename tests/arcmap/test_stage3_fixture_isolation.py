"""Process-isolation regression tests for the real Stage3 safety fixture."""
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / 'tests/arcmap/test_stage3_safety.py'
PREFIXES = ('mcp_server', 'stage3')


def owned(name):
    return any(name == p or name.startswith(p + '.') for p in PREFIXES)


@contextmanager
def probe_module():
    """Keep a failing regression probe from leaking into its own runner."""
    environment, path = dict(os.environ), sys.path[:]
    bytecode = sys.dont_write_bytecode
    saved = {k: v for k, v in sys.modules.items() if owned(k)}
    name = '_stage3_fixture_isolation_probe'
    spec = importlib.util.spec_from_file_location(name, TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        yield module, spec
    finally:
        if hasattr(module, 'TEMP'):
            module.TEMP.cleanup()
        os.environ.clear()
        os.environ.update(environment)
        sys.path[:] = path
        sys.dont_write_bytecode = bytecode
        for key in list(sys.modules):
            if owned(key):
                del sys.modules[key]
        sys.modules.update(saved)
        sys.modules.pop(name, None)


class Stage3FixtureIsolation(unittest.TestCase):
    def test_complete_run_repeats_with_sentinel_process_state(self):
        import tempfile
        import types
        from contextvars import ContextVar
        with probe_module() as (module, spec):
            spec.loader.exec_module(module)
            for key in list(sys.modules):
                if owned(key):
                    del sys.modules[key]
            for name in ('mcp_server', 'mcp_server.request_context',
                         'mcp_server.execution_context', 'mcp_server.sentinel',
                         'stage3', 'stage3.sentinel'):
                sys.modules[name] = types.ModuleType(name)
            correlation = ContextVar('isolation-correlation')
            authority = ContextVar('isolation-authority')
            first, second = {'sentinel': 'correlation'}, {'sentinel': 'authority'}
            self.addCleanup(correlation.reset, correlation.set(first))
            self.addCleanup(authority.reset, authority.set(second))
            sys.modules['mcp_server.request_context'].correlation = correlation
            sys.modules['mcp_server.execution_context'].CURRENT = authority
            os.environ['ZAGENT_ISOLATION_SENTINEL'] = 'keep-zagent'
            os.environ['ARCMAP_ISOLATION_SENTINEL'] = 'keep-arcmap'
            environment, path = dict(os.environ), sys.path[:]
            bytecode = sys.dont_write_bytecode
            modules = {k: v for k, v in sys.modules.items() if owned(k)}
            (ROOT / '_validation').mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='stage3-isolation-', dir=ROOT / '_validation') as root:
                module.ROOT = Path(root) / 'fresh-root'
                self.assertFalse((module.ROOT / '_validation').exists())
                for iteration in range(2):
                    with self.subTest(iteration=iteration):
                        result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(
                            unittest.defaultTestLoader.loadTestsFromModule(module))
                        self.assertTrue(result.wasSuccessful(), 'nested Stage3 run failed')
                        self.assertEqual(18, result.testsRun)
                        self.assertEqual(environment, dict(os.environ))
                        self.assertEqual(path, sys.path)
                        self.assertEqual(bytecode, sys.dont_write_bytecode)
                        self.assertEqual(modules, {k: v for k, v in sys.modules.items() if owned(k)})
                        self.assertIs(first, correlation.get())
                        self.assertIs(second, authority.get())
                        self.assertFalse(Path(module.TEMP.name).exists())
                        self.assertEqual([], list((module.ROOT / '_validation').iterdir()))

    def test_setup_failure_restores_contexts_and_process_state(self):
        import builtins
        from unittest.mock import patch
        with probe_module() as (module, spec):
            spec.loader.exec_module(module)
            os.environ['ZAGENT_ISOLATION_SENTINEL'] = 'keep-after-failure'
            environment, path = dict(os.environ), sys.path[:]
            bytecode = sys.dont_write_bytecode
            modules = {k: v for k, v in sys.modules.items() if owned(k)}
            contexts = []
            original_import = builtins.__import__
            def fail_final_import(name, *args, **kwargs):
                result = original_import(name, *args, **kwargs)
                if name == 'stage3':
                    correlation = sys.modules['mcp_server.request_context'].correlation
                    authority = sys.modules['mcp_server.execution_context'].CURRENT
                    contexts.extend((correlation, authority))
                    correlation.set({'fixture-failure': 'correlation'})
                    authority.set({'fixture-failure': 'authority'})
                    raise RuntimeError('injected fixture setup failure')
                return result
            with patch.object(builtins, '__import__', fail_final_import):
                result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(
                    unittest.defaultTestLoader.loadTestsFromModule(module))
            self.assertEqual(0, result.testsRun)
            self.assertEqual(1, len(result.errors))
            self.assertIn('injected fixture setup failure', result.errors[0][1])
            self.assertEqual(environment, dict(os.environ))
            self.assertEqual(path, sys.path)
            self.assertEqual(bytecode, sys.dont_write_bytecode)
            self.assertEqual(modules, {k: v for k, v in sys.modules.items() if owned(k)})
            self.assertFalse(Path(module.TEMP.name).exists())
            self.assertEqual(2, len(contexts))
            self.assertEqual({}, contexts[0].get(), 'correlation leaked after setup failure')
            self.assertIsNone(contexts[1].get(), 'authority leaked after setup failure')

    def test_discovery_preserves_environment_and_path(self):
        with probe_module() as (module, spec):
            os.environ['ZAGENT_ISOLATION_SENTINEL'] = 'keep-zagent'
            os.environ['ARCMAP_ISOLATION_SENTINEL'] = 'keep-arcmap'
            environment, path = dict(os.environ), sys.path[:]
            bytecode = sys.dont_write_bytecode
            modules = {k: v for k, v in sys.modules.items() if owned(k)}
            validation = ROOT / '_validation'
            directories = set(validation.glob('stage3-safety-*'))
            spec.loader.exec_module(module)
            suite = unittest.defaultTestLoader.loadTestsFromModule(module)
            self.assertEqual(18, suite.countTestCases())
            self.assertEqual(environment, dict(os.environ), 'discovery changed environment')
            self.assertEqual(path, sys.path, 'discovery changed sys.path')
            self.assertEqual(bytecode, sys.dont_write_bytecode)
            self.assertEqual(modules, {k: v for k, v in sys.modules.items() if owned(k)})
            self.assertEqual(directories, set(validation.glob('stage3-safety-*')))
            self.assertFalse(hasattr(module, 'TEMP'), 'discovery created a fixture')


if __name__ == '__main__':
    unittest.main()

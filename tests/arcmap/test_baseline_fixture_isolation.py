"""Regression for source-cache ownership of the baseline's real SDK imports."""
import importlib
import io
import sys
import unittest


def owned(name):
    return name == 'orchestrator' or name.startswith('orchestrator.')


class BaselineFixtureIsolation(unittest.TestCase):
    def test_baseline_restores_orchestrator_modules_after_real_suite(self):
        baseline = importlib.import_module('test_bridge_regression')
        saved = {key: value for key, value in sys.modules.items() if owned(key)}
        for key in saved:
            del sys.modules[key]
        stream = io.StringIO()
        try:
            suite = unittest.defaultTestLoader.loadTestsFromModule(baseline)
            result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
            self.assertEqual(26, result.testsRun, stream.getvalue())
            self.assertEqual([], result.failures, stream.getvalue())
            self.assertEqual([], result.errors, stream.getvalue())
            self.assertEqual([], result.skipped, stream.getvalue())
            self.assertEqual([], sorted(key for key in sys.modules if owned(key)))
        finally:
            for key in list(sys.modules):
                if owned(key):
                    del sys.modules[key]
            sys.modules.update(saved)

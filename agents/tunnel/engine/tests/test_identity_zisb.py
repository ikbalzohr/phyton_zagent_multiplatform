"""Authenticated internal channel replaces chat binding. NOT_RUN."""
import os
import unittest
from unittest.mock import patch
from router.identity import verify_internal_token, internal_token
from router.access import AuthorizationError

class InternalChannelTests(unittest.TestCase):
    def test_missing_or_weak_internal_secret_fail_closed(self):
        for value in ("", "short"):
            with patch.dict(os.environ, {"ZAGENT_INTERNAL_TOKEN":value}), self.assertRaises(AuthorizationError):
                internal_token()

    def test_constant_time_token_boundary(self):
        with patch.dict(os.environ, {"ZAGENT_INTERNAL_TOKEN":"synthetic-internal-token-0123456789"}):
            verify_internal_token("synthetic-internal-token-0123456789")
            with self.assertRaises(AuthorizationError):
                verify_internal_token("forged")

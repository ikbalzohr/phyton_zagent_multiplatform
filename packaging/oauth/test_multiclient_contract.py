"""Offline MCP authorization metadata and CIMD policy intent checks."""
import importlib.util
from pathlib import Path
import unittest

from client_policy_review import build_review


def load_readiness():
    path = Path(__file__).with_name("check_mcp_readiness.py")
    spec = importlib.util.spec_from_file_location("zmp_check_mcp_readiness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MultiClientContractTests(unittest.TestCase):
    def setUp(self):
        self.resource = "https://mcp-fixture.example/mcp"
        self.issuer = "https://auth-fixture.example/realms/zagent"
        self.metadata = {"resource": self.resource,
                         "authorization_servers": [self.issuer]}
        self.identity = {
            "issuer": self.issuer,
            "authorization_endpoint": self.issuer + "/protocol/openid-connect/auth",
            "token_endpoint": self.issuer + "/protocol/openid-connect/token",
            "code_challenge_methods_supported": ["S256"],
            "authorization_response_iss_parameter_supported": True,
            "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"]
        }

    def test_valid_discovery_contract(self):
        load_readiness().validate_discovery(
            self.resource, self.issuer, self.metadata, self.identity)

    def test_deny_wrong_resource_issuer_pkce_and_token_method(self):
        checker = load_readiness()
        for mutated in (
            (self.resource.replace("/mcp", "/tools"), self.issuer,
             self.metadata, self.identity),
            (self.resource, self.issuer + "/other", self.metadata, self.identity),
            (self.resource, self.issuer,
             dict(self.metadata, resource="https://other.example/mcp"), self.identity),
            (self.resource, self.issuer,
             dict(self.metadata, authorization_servers=["https://other.example"]),
             self.identity),
            (self.resource, self.issuer, self.metadata,
             dict(self.identity, issuer="https://other.example")),
            (self.resource, self.issuer, self.metadata,
             dict(self.identity, code_challenge_methods_supported=["plain"])),
            (self.resource, self.issuer, self.metadata,
             dict(self.identity, authorization_response_iss_parameter_supported=False)),
            (self.resource, self.issuer, self.metadata,
             dict(self.identity, token_endpoint_auth_methods_supported=["client_secret_post"])),
        ):
            with self.subTest(case=mutated[:2]), self.assertRaises(ValueError):
                checker.validate_discovery(*mutated)

    def test_cimd_policies_are_review_only_and_exact_resource(self):
        plan = build_review(self.resource)
        self.assertEqual(plan["status"], "OWNER_REVIEW_REQUIRED_NOT_APPLIED")
        self.assertEqual(plan["feature_flags"], ["cimd", "resource-indicators"])
        self.assertEqual(plan["resource_indicator_allow_list"], [self.resource])
        self.assertEqual([p["client_id_trusted_domains"] for p in plan["client_policies"]],
                         [["claude.ai"], ["nousresearch.github.io"]])
        self.assertFalse(plan["registration_endpoint"]["public"])
        for policy in plan["client_policies"]:
            self.assertEqual(policy["resource_indicator_allow_list"], [self.resource])
            self.assertEqual(policy["uri_scheme"], ["https"])
            self.assertFalse(policy["allow_http_scheme"])
            self.assertNotIn("*", ",".join(policy["metadata_trusted_domains"]))
        self.assertTrue(plan["client_policies"][0][
            "accept_public_client_with_confidential_only_grant_types"])
        self.assertEqual(plan["chatgpt"]["mode"], "pre_registered_public_pkce")

    def test_reject_unsafe_cimd_resource(self):
        for resource in ("http://example.com/mcp", "https://example.com/tools",
                         "https://example.com/mcp?x=1", "https://user:pass@example.com/mcp",
                         "https://example.com/mcp#fragment", None):
            with self.subTest(resource=resource), self.assertRaises(ValueError):
                build_review(resource)


if __name__ == "__main__":
    unittest.main()

"""Offline contract test SOURCE; run on owner Windows, not executed on VPS."""
import copy
import unittest

from router.access import principal_id
from router.oauth_provisioning import build_readonly_plan


class OAuthProvisioningTests(unittest.TestCase):
    def spec(self):
        return dict(issuer="https://as.example/realms/zagent",
                    resource_uri="https://resource.example/mcp", subject="user-uuid",
                    workspace_id="ws", policy_revision="2", profile_id="approved-repo",
                    device_id="device", installation_id="install", grant_expires_at=2000000000,
                    hermes_client_id="hermes-zagent", introspection_client_id="zagent-rs",
                    redirect_port=8765)

    def test_exact_audience_issuer_and_principal(self):
        plan = build_readonly_plan(self.spec())
        resource = plan["resource_server"]
        self.assertEqual(resource["introspection_endpoint"],
                         self.spec()["issuer"] + "/protocol/openid-connect/token/introspect")
        self.assertEqual(resource["authorization_servers"], [self.spec()["issuer"]])
        self.assertEqual(list(resource["grants"]),
                         [principal_id(self.spec()["issuer"], "user-uuid")])
        mapper = plan["keycloak"]["audience_mapper"]
        self.assertEqual(mapper["config"]["included.custom.audience"], self.spec()["resource_uri"])
        self.assertEqual(mapper["config"]["introspection.token.claim"], "true")

    def test_output_disabled_revoked_and_profile_scoped(self):
        plan = build_readonly_plan(self.spec())
        grant = next(iter(plan["resource_server"]["grants"].values()))
        self.assertIs(grant["revoked"], True)
        self.assertIs(grant["files_resource"]["revoked"], True)
        self.assertEqual(grant["scopes"], ["files:read"])
        self.assertEqual(grant["tools"], ["files_stat", "files_read"])
        self.assertEqual(grant["files_resource"]["profile_id"], "approved-repo")
        hermes = plan["hermes_mcp_entry"]
        self.assertIs(hermes["enabled"], False)
        self.assertEqual(hermes["auth"], "oauth")
        self.assertEqual(hermes["oauth"]["token_endpoint_auth_method"], "none")
        self.assertEqual(hermes["oauth"]["scope"], "files:read")
        self.assertNotIn("headers", hermes)
        self.assertNotIn("client_secret", hermes["oauth"])

    def test_rejects_nonexact_urls_and_unapproved_scope_inputs(self):
        for field, value in [("issuer", "http://as.example/realms/zagent"),
                             ("issuer", "https://as.example/realms/zagent/"),
                             ("resource_uri", "https://resource.example/mcp/"),
                             ("resource_uri", "https://resource.example/mcp?key=x"),
                             ("issuer", "https://u:p@as.example/realms/zagent"),
                             ("subject", " user-uuid"), ("redirect_port", True),
                             ("grant_expires_at", float("inf"))]:
            spec = self.spec(); spec[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                build_readonly_plan(spec)
        for field in ("client_secret", "access_token", "scopes", "tools"):
            spec = self.spec(); spec[field] = "not-allowed"
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_readonly_plan(spec)

    def test_input_not_mutated_and_clients_separated(self):
        spec = self.spec(); before = copy.deepcopy(spec)
        build_readonly_plan(spec)
        self.assertEqual(spec, before)
        spec["introspection_client_id"] = spec["hermes_client_id"]
        with self.assertRaises(ValueError):
            build_readonly_plan(spec)

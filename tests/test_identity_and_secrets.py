from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest

from reportflow_app.core import ProjectStore, ReportFlowError
from reportflow_app.enterprise import ConnectorProfile, require_secret, validate_read_only_query, validate_rest_endpoint
from reportflow_app.identity import (
    IdentityStore,
    NativeOIDCClient,
    OIDCProviderConfig,
    SCIMProvisioningService,
)
from reportflow_app.secrets import SecretResolver


class FakeSecretProvider:
    def __init__(self, value: str = "central-secret") -> None:
        self.value = value
        self.references: list[str] = []

    def resolve(self, reference: str) -> str:
        self.references.append(reference)
        return self.value


def test_native_oidc_uses_browser_safe_pkce_s256() -> None:
    client = NativeOIDCClient(OIDCProviderConfig(
        issuer="https://id.example.test", client_id="reportflow-desktop",
        redirect_uri="http://127.0.0.1:49152/oauth/callback",
        authorization_endpoint="https://id.example.test/authorize",
        token_endpoint="https://id.example.test/token", jwks_uri="https://id.example.test/jwks",
    ))
    login = client.start_login()
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(login.authorization_url).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [login.state]
    assert "nonce" in query and "code_challenge" in query
    assert "client_secret" not in query


def test_oidc_rejects_insecure_non_loopback_redirect() -> None:
    with pytest.raises(ReportFlowError):
        OIDCProviderConfig(
            issuer="https://id.example.test", client_id="desktop", redirect_uri="http://app.example.test/callback"
        ).validate()


def test_scim_provisioning_is_allowlisted_and_audited(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "reportflow.db")
    service = SCIMProvisioningService(IdentityStore(store), {"Finance Analysts": "report_author"})
    user = service.upsert_user_resource({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "externalId": "entra:alice",
        "userName": "alice@example.test", "displayName": "Alice", "active": True,
        "emails": [{"value": "alice@example.test", "primary": True}],
        "groups": [{"display": "Finance Analysts"}],
    })
    assert user["active"] is True
    assert service.identity_store.get_user_by_external_id("entra:alice").roles == ["report_author"]
    patched = service.patch_user_resource(user["id"], {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "active", "value": False}],
    })
    assert patched["active"] is False
    with pytest.raises(ReportFlowError):
        service.patch_user_resource(user["id"], {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "roles", "value": ["tenant_admin"]}],
        })
    assert any(event["action"] == "identity.user.upserted" for event in store.list_audit_events())


def test_central_secret_reference_routes_only_to_approved_provider() -> None:
    provider = FakeSecretProvider()
    resolver = SecretResolver({"vault": provider})
    assert resolver.resolve("vault:///reportflow/prod/connectors/sales#password") == "central-secret"
    assert provider.references == ["vault:///reportflow/prod/connectors/sales#password"]
    with pytest.raises(ReportFlowError):
        resolver.resolve("https://unapproved.example.test/secret")


def test_connector_secret_uses_provider_and_not_connector_settings() -> None:
    provider = FakeSecretProvider("db-secret")
    profile = ConnectorProfile(
        id="sales", name="Sales", kind="postgresql", settings={"host": "db.example.test"},
        credential_reference="vault:///reportflow/prod/connectors/sales#password",
    )
    assert require_secret(profile, provider) == "db-secret"
    assert provider.references == [profile.credential_reference]


def test_read_only_query_rejects_comments_and_sql_mutations() -> None:
    with pytest.raises(ReportFlowError):
        validate_read_only_query("SELECT * FROM sales -- hidden write")
    with pytest.raises(ReportFlowError):
        validate_read_only_query("SELECT * INTO archive FROM sales")


def test_rest_private_address_requires_explicit_cidr_allowlist() -> None:
    endpoint = urllib.parse.urlsplit("https://127.0.0.1/api")
    with pytest.raises(ReportFlowError, match="private"):
        validate_rest_endpoint(endpoint, {"127.0.0.1"}, [])
    validate_rest_endpoint(endpoint, {"127.0.0.1"}, ["127.0.0.0/8"])

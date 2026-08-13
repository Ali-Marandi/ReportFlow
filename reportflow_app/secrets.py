"""Central secret manager adapters for ReportFlow Enterprise.

All adapters are read-only. Connector profiles contain only a credential reference;
secret material is never persisted in the ReportFlow catalog or written to logs.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from reportflow_app.core import CredentialVault, ReportFlowError

_REFERENCE = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s?#]+(?:/[^\s?#]+)*(?:#[A-Za-z0-9_.-]+)?$")


class SecretProvider(Protocol):
    def resolve(self, reference: str) -> str: ...


@dataclass(slots=True)
class LocalVaultProvider:
    """Development-only provider backed by the operating-system credential vault."""

    prefix: str = "local://"

    def resolve(self, reference: str) -> str:
        if not reference.startswith(self.prefix):
            raise ReportFlowError("The local secret provider accepts only local:// references.")
        key = reference.removeprefix(self.prefix)
        if not key or "/" not in key:
            raise ReportFlowError("Local secret references must include a namespace and name.")
        value = CredentialVault.get_secret(key)
        if not value:
            raise ReportFlowError("The local credential reference cannot be resolved by the OS vault.")
        return value


@dataclass(slots=True)
class VaultAppRoleProvider:
    """HashiCorp Vault KV v2 provider using a short-lived AppRole login.

    The caller supplies a `role_id` and a `secret_id_loader`; the latter should
    read a response-wrapped, short-lived bootstrap value from MDM/agent storage,
    never a hard-coded secret or connector configuration.
    """

    vault_url: str
    mount: str
    allowed_path_prefix: str
    role_id: str
    secret_id_loader: callable
    auth_mount: str = "approle"
    timeout_seconds: int = 10

    def __post_init__(self) -> None:
        _validate_https(self.vault_url, "Vault URL")
        if not self.mount.strip() or not self.allowed_path_prefix.strip() or not self.role_id.strip():
            raise ReportFlowError("Vault provider requires mount, allowed path prefix, and role ID.")

    def resolve(self, reference: str) -> str:
        parsed = urllib.parse.urlsplit(reference)
        if parsed.scheme != "vault" or parsed.netloc or not parsed.path or not parsed.fragment:
            raise ReportFlowError("Vault references use vault:///path/to/secret#field.")
        path = parsed.path.lstrip("/")
        if not path or any(segment in {"", ".", ".."} for segment in path.split("/")):
            raise ReportFlowError("Vault reference contains an invalid secret path.")
        if not path.startswith(self.allowed_path_prefix.rstrip("/") + "/"):
            raise ReportFlowError("Vault reference is outside the approved tenant secret prefix.")
        secret_id = self.secret_id_loader()
        if not isinstance(secret_id, str) or not secret_id:
            raise ReportFlowError("A short-lived Vault bootstrap secret could not be obtained.")
        token_response = _post_json(self.vault_url.rstrip("/") + f"/v1/auth/{urllib.parse.quote(self.auth_mount, safe='')}/login",
                                    {"role_id": self.role_id, "secret_id": secret_id}, self.timeout_seconds)
        token = token_response.get("auth", {}).get("client_token")
        if not isinstance(token, str) or not token:
            raise ReportFlowError("Vault did not issue a usable workload token.")
        path_url = urllib.parse.quote(path, safe="/")
        request = urllib.request.Request(self.vault_url.rstrip("/") + f"/v1/{urllib.parse.quote(self.mount, safe='')}/data/{path_url}",
                                         headers={"X-Vault-Token": token, "Accept": "application/json"}, method="GET")
        try:
            opener = urllib.request.build_opener(_NoRedirectHandler())
            # Vault URL and tenant path are validated; redirects are rejected.
            with opener.open(request, timeout=self.timeout_seconds) as response:  # nosec B310
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        except Exception as error:
            raise ReportFlowError("Central Vault secret retrieval failed.") from error
        value = payload.get("data", {}).get("data", {}).get(parsed.fragment)
        if not isinstance(value, str) or not value:
            raise ReportFlowError("Vault secret field is missing or is not a nonempty string.")
        return value


@dataclass(slots=True)
class AzureKeyVaultProvider:
    """Azure Key Vault provider using DefaultAzureCredential (managed identity in production)."""

    vault_url: str
    allowed_name_prefix: str

    def __post_init__(self) -> None:
        _validate_https(self.vault_url, "Azure Key Vault URL")

    def resolve(self, reference: str) -> str:
        parsed = urllib.parse.urlsplit(reference)
        if parsed.scheme != "azurekv" or parsed.netloc or not parsed.path or parsed.fragment:
            raise ReportFlowError("Azure Key Vault references use azurekv:///secret-name.")
        name = parsed.path.lstrip("/")
        if not name.startswith(self.allowed_name_prefix) or not re.fullmatch(r"[A-Za-z0-9-]{1,127}", name):
            raise ReportFlowError("Azure Key Vault secret name is outside the approved tenant prefix.")
        try:
            from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
            from azure.keyvault.secrets import SecretClient  # type: ignore[import-not-found]
            value = SecretClient(vault_url=self.vault_url, credential=DefaultAzureCredential()).get_secret(name).value
        except ImportError as error:
            raise ReportFlowError("Azure Key Vault requires azure-identity and azure-keyvault-secrets enterprise dependencies.") from error
        except Exception as error:
            raise ReportFlowError("Azure Key Vault secret retrieval failed.") from error
        if not value:
            raise ReportFlowError("Azure Key Vault returned an empty secret.")
        return str(value)


@dataclass(slots=True)
class AWSSecretsManagerProvider:
    """AWS Secrets Manager provider using the default IAM credential chain."""

    region_name: str
    allowed_arn_prefix: str

    def resolve(self, reference: str) -> str:
        parsed = urllib.parse.urlsplit(reference)
        if parsed.scheme != "awssecrets" or parsed.netloc or not parsed.path or not parsed.fragment:
            raise ReportFlowError("AWS references use awssecrets:///secret-arn#json-field.")
        secret_id = urllib.parse.unquote(parsed.path.lstrip("/"))
        if not secret_id.startswith(self.allowed_arn_prefix):
            raise ReportFlowError("AWS secret reference is outside the approved tenant ARN prefix.")
        try:
            import boto3  # type: ignore[import-not-found]
            response = boto3.client("secretsmanager", region_name=self.region_name).get_secret_value(SecretId=secret_id)
        except ImportError as error:
            raise ReportFlowError("AWS Secrets Manager requires the optional boto3 enterprise dependency.") from error
        except Exception as error:
            raise ReportFlowError("AWS Secrets Manager secret retrieval failed.") from error
        raw = response.get("SecretString")
        if not isinstance(raw, str):
            raise ReportFlowError("AWS Secrets Manager response does not contain a text secret.")
        try:
            value = json.loads(raw)[parsed.fragment]
        except Exception as error:
            raise ReportFlowError("AWS secret must be JSON and contain the requested field.") from error
        if not isinstance(value, str) or not value:
            raise ReportFlowError("AWS secret field is missing or is not text.")
        return value


class SecretResolver:
    """Routes immutable URI references to an explicitly approved provider."""

    def __init__(self, providers: dict[str, SecretProvider]) -> None:
        if not providers:
            raise ReportFlowError("At least one secret provider must be configured.")
        self.providers = dict(providers)

    def resolve(self, reference: str) -> str:
        if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
            raise ReportFlowError("Credential reference has an invalid format.")
        scheme = urllib.parse.urlsplit(reference).scheme
        provider = self.providers.get(scheme)
        if provider is None:
            raise ReportFlowError("The selected credential provider is not approved for this deployment.")
        return provider.resolve(reference)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: object, fp: object, code: int, message: str, headers: object, newurl: str) -> None:
        raise ReportFlowError("Secret manager endpoint redirects are not permitted by policy.")


def _validate_https(value: str, label: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ReportFlowError(f"{label} must be a clean HTTPS URL.")


def _post_json(url: str, body: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        # URL is derived from validated Vault base URL; redirects are rejected.
        with opener.open(request, timeout=timeout_seconds) as response:  # nosec B310
            return dict(json.loads(response.read(1024 * 1024).decode("utf-8")))
    except Exception as error:
        raise ReportFlowError("Central Vault authentication failed.") from error

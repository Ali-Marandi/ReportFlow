"""Enterprise identity foundations for ReportFlow v2.0.

Desktop authentication follows OIDC Authorization Code + PKCE.  SCIM behavior is
kept in a control-plane service adapter; the desktop executable never exposes a
public provisioning endpoint.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from reportflow_app.core import CredentialVault, ProjectStore, ReportFlowError, utc_now

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SAFE_OIDC_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "report_viewer": frozenset({"report.read", "run.read"}),
    "report_author": frozenset({"report.read", "report.write", "run.read", "run.execute"}),
    "burst_operator": frozenset({"burst.read", "burst.write", "burst.execute"}),
    "connector_admin": frozenset({"connector.read", "connector.write", "connector.test"}),
    "semantic_steward": frozenset({"semantic.read", "semantic.write", "copilot.execute"}),
    "tenant_admin": frozenset({"identity.read", "identity.write", "role.assign", "audit.read"}),
}


@dataclass(slots=True)
class OIDCProviderConfig:
    issuer: str
    client_id: str
    redirect_uri: str
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    jwks_uri: str = ""
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    group_claim: str = "groups"
    allowed_algorithms: tuple[str, ...] = SAFE_OIDC_ALGORITHMS

    def validate(self) -> None:
        _require_https_url(self.issuer, "OIDC issuer")
        _require_https_url(self.authorization_endpoint, "OIDC authorization endpoint", optional=True)
        _require_https_url(self.token_endpoint, "OIDC token endpoint", optional=True)
        _require_https_url(self.jwks_uri, "OIDC JWKS endpoint", optional=True)
        redirect = urllib.parse.urlsplit(self.redirect_uri)
        is_loopback = redirect.scheme == "http" and redirect.hostname in {"127.0.0.1", "::1"}
        if not is_loopback and (redirect.scheme != "https" or not redirect.hostname):
            raise ReportFlowError("OIDC redirect URI must be HTTPS or a local loopback URI.")
        if not self.client_id.strip() or "openid" not in self.scopes:
            raise ReportFlowError("OIDC configuration requires a client ID and the openid scope.")
        if not set(self.allowed_algorithms).issubset(SAFE_OIDC_ALGORITHMS):
            raise ReportFlowError("OIDC configuration contains an unsupported ID-token algorithm.")


@dataclass(slots=True)
class LoginTransaction:
    state: str
    nonce: str
    code_verifier: str
    created_at: float


@dataclass(slots=True)
class LoginStart:
    authorization_url: str
    state: str


@dataclass(slots=True)
class OIDCSession:
    subject: str
    issuer: str
    email: str | None
    display_name: str | None
    groups: list[str]
    roles: list[str]
    expires_at: int
    access_token: str
    refresh_token: str | None = None


class NativeOIDCClient:
    """Strict OIDC public-client flow for a native Windows application.

    Transactions are in memory and single-use. The caller opens ``authorization_url``
    with the operating-system browser then gives the callback URL to ``complete``.
    """

    def __init__(self, config: OIDCProviderConfig, timeout_seconds: int = 15) -> None:
        config.validate()
        self.config = config
        self.timeout_seconds = timeout_seconds
        self._transactions: dict[str, LoginTransaction] = {}

    def discover(self) -> OIDCProviderConfig:
        discovery_url = self.config.issuer.rstrip("/") + "/.well-known/openid-configuration"
        payload = _read_json(discovery_url, self.timeout_seconds)
        issuer = str(payload.get("issuer", "")).rstrip("/")
        if issuer != self.config.issuer.rstrip("/"):
            raise ReportFlowError("OIDC discovery issuer does not match the configured issuer.")
        discovered = OIDCProviderConfig(
            issuer=issuer,
            client_id=self.config.client_id,
            redirect_uri=self.config.redirect_uri,
            authorization_endpoint=str(payload.get("authorization_endpoint", "")),
            token_endpoint=str(payload.get("token_endpoint", "")),
            jwks_uri=str(payload.get("jwks_uri", "")),
            scopes=self.config.scopes,
            group_claim=self.config.group_claim,
            allowed_algorithms=self.config.allowed_algorithms,
        )
        discovered.validate()
        self.config = discovered
        return discovered

    def start_login(self) -> LoginStart:
        if not self.config.authorization_endpoint:
            self.discover()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
        self._transactions[state] = LoginTransaction(state, nonce, verifier, time.monotonic())
        self._drop_expired_transactions()
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return LoginStart(self.config.authorization_endpoint + "?" + urllib.parse.urlencode(params), state)

    def complete(self, callback_url: str, group_role_mapping: dict[str, str] | None = None) -> OIDCSession:
        callback = urllib.parse.urlsplit(callback_url)
        expected = urllib.parse.urlsplit(self.config.redirect_uri)
        if (callback.scheme, callback.hostname, callback.path) != (expected.scheme, expected.hostname, expected.path):
            raise ReportFlowError("OIDC callback does not match the configured redirect URI.")
        params = urllib.parse.parse_qs(callback.query, strict_parsing=True)
        if "error" in params:
            raise ReportFlowError("The identity provider denied the sign-in request.")
        code, state = _single(params, "code"), _single(params, "state")
        transaction = self._transactions.pop(state, None)
        if transaction is None or time.monotonic() - transaction.created_at > 600:
            raise ReportFlowError("OIDC state is invalid or has expired. Start sign-in again.")
        if not self.config.token_endpoint or not self.config.jwks_uri:
            self.discover()
        token_response = _post_form(self.config.token_endpoint, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id, "code_verifier": transaction.code_verifier,
        }, self.timeout_seconds)
        id_token = str(token_response.get("id_token", ""))
        access_token = str(token_response.get("access_token", ""))
        if not id_token or not access_token:
            raise ReportFlowError("OIDC token response is missing a required token.")
        claims = self._validate_id_token(id_token, transaction.nonce)
        raw_groups = claims.get(self.config.group_claim, [])
        groups = [str(value) for value in raw_groups] if isinstance(raw_groups, list) else []
        mapping = group_role_mapping or {}
        roles = sorted({mapping[group] for group in groups if group in mapping and mapping[group] in ROLE_PERMISSIONS})
        expires_at = int(claims["exp"])
        return OIDCSession(
            subject=str(claims["sub"]), issuer=str(claims["iss"]), email=_optional_str(claims.get("email")),
            display_name=_optional_str(claims.get("name")), groups=groups, roles=roles, expires_at=expires_at,
            access_token=access_token, refresh_token=_optional_str(token_response.get("refresh_token")),
        )

    def save_session(self, session: OIDCSession, reference: str = "identity/current-session") -> None:
        CredentialVault.set_secret(reference, json.dumps(asdict(session), ensure_ascii=False))

    def clear_session(self, reference: str = "identity/current-session") -> None:
        CredentialVault.delete_secret(reference)

    def _validate_id_token(self, token: str, expected_nonce: str) -> dict[str, Any]:
        try:
            import jwt  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("OIDC requires the optional PyJWT[crypto] enterprise dependency.") from error
        try:
            signing_key = jwt.PyJWKClient(self.config.jwks_uri, timeout=self.timeout_seconds).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, signing_key.key, algorithms=list(self.config.allowed_algorithms), audience=self.config.client_id,
                issuer=self.config.issuer.rstrip("/"), options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
            )
        except Exception as error:
            raise ReportFlowError("OIDC ID token validation failed.") from error
        if not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
            raise ReportFlowError("OIDC nonce validation failed.")
        return dict(claims)

    def _drop_expired_transactions(self) -> None:
        cutoff = time.monotonic() - 600
        for state in [key for key, value in self._transactions.items() if value.created_at < cutoff]:
            self._transactions.pop(state, None)


@dataclass(slots=True)
class IdentityUser:
    scim_id: str
    external_id: str
    user_name: str
    display_name: str
    email: str | None
    active: bool
    roles: list[str] = field(default_factory=list)
    version: int = 1
    updated_at: str = ""


@dataclass(slots=True)
class IdentityGroup:
    scim_id: str
    external_id: str
    display_name: str
    member_scim_ids: list[str] = field(default_factory=list)
    version: int = 1
    updated_at: str = ""


class IdentityStore:
    """Tenant-local SCIM persistence with explicit role mapping and audit events."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.database_path = Path(store.database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS identity_users (
                    scim_id TEXT PRIMARY KEY, external_id TEXT NOT NULL UNIQUE, user_name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL, email TEXT, active INTEGER NOT NULL, roles TEXT NOT NULL,
                    version INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identity_groups (
                    scim_id TEXT PRIMARY KEY, external_id TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL UNIQUE,
                    members TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
            """)

    def upsert_user(self, user: IdentityUser, actor: str = "scim-provisioner") -> IdentityUser:
        _validate_identity_user(user)
        previous = self.get_user_by_external_id(user.external_id, required=False)
        version = (previous.version + 1) if previous else 1
        now = utc_now()
        saved = IdentityUser(user.scim_id or _stable_scim_id(user.external_id), user.external_id, user.user_name, user.display_name,
                             user.email, user.active, sorted(set(user.roles)), version, now)
        with self._connect() as connection:
            connection.execute("""INSERT INTO identity_users(scim_id, external_id, user_name, display_name, email, active, roles, version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_id) DO UPDATE SET user_name=excluded.user_name, display_name=excluded.display_name,
                email=excluded.email, active=excluded.active, roles=excluded.roles, version=excluded.version, updated_at=excluded.updated_at""",
                (saved.scim_id, saved.external_id, saved.user_name, saved.display_name, saved.email, int(saved.active),
                 json.dumps(saved.roles), saved.version, saved.updated_at))
        self.store.audit("identity.user.upserted", "identity_user", saved.scim_id, {"active": saved.active, "roles": saved.roles}, actor)
        return saved

    def get_user(self, scim_id: str) -> IdentityUser:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM identity_users WHERE scim_id=?", (scim_id,)).fetchone()
        if row is None:
            raise ReportFlowError("The SCIM user does not exist.")
        return _user_from_row(row)

    def get_user_by_external_id(self, external_id: str, required: bool = True) -> IdentityUser | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM identity_users WHERE external_id=?", (external_id,)).fetchone()
        if row is None and required:
            raise ReportFlowError("The SCIM user does not exist.")
        return _user_from_row(row) if row else None

    def list_users(self, start_index: int = 1, count: int = 100) -> tuple[list[IdentityUser], int]:
        if start_index < 1 or not 1 <= count <= 100:
            raise ReportFlowError("SCIM pagination must use startIndex >= 1 and count between 1 and 100.")
        with self._connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM identity_users").fetchone()[0])
            rows = connection.execute("SELECT * FROM identity_users ORDER BY user_name LIMIT ? OFFSET ?", (count, start_index - 1)).fetchall()
        return [_user_from_row(row) for row in rows], total

    def upsert_group(self, group: IdentityGroup, actor: str = "scim-provisioner") -> IdentityGroup:
        if not group.external_id.strip() or not group.display_name.strip():
            raise ReportFlowError("SCIM groups require externalId and displayName.")
        members = sorted(set(group.member_scim_ids))
        for member in members:
            self.get_user(member)
        old = self.get_group_by_external_id(group.external_id, required=False)
        now = utc_now()
        saved = IdentityGroup(group.scim_id or _stable_scim_id(group.external_id), group.external_id, group.display_name, members,
                              (old.version + 1) if old else 1, now)
        with self._connect() as connection:
            connection.execute("""INSERT INTO identity_groups(scim_id, external_id, display_name, members, version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_id) DO UPDATE SET display_name=excluded.display_name, members=excluded.members,
                version=excluded.version, updated_at=excluded.updated_at""",
                (saved.scim_id, saved.external_id, saved.display_name, json.dumps(saved.member_scim_ids), saved.version, saved.updated_at))
        self.store.audit("identity.group.upserted", "identity_group", saved.scim_id, {"members": len(members)}, actor)
        return saved

    def get_group_by_external_id(self, external_id: str, required: bool = True) -> IdentityGroup | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM identity_groups WHERE external_id=?", (external_id,)).fetchone()
        if row is None and required:
            raise ReportFlowError("The SCIM group does not exist.")
        return _group_from_row(row) if row else None


class SCIMProvisioningService:
    """Schema-restricted SCIM user/group operations for a server-side control plane."""

    def __init__(self, identity_store: IdentityStore, group_role_mapping: dict[str, str]) -> None:
        invalid = set(group_role_mapping.values()).difference(ROLE_PERMISSIONS)
        if invalid:
            raise ReportFlowError("SCIM group mapping references an undefined ReportFlow role.")
        self.identity_store = identity_store
        self.group_role_mapping = dict(group_role_mapping)

    def service_provider_config(self) -> dict[str, Any]:
        return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
                "patch": {"supported": True}, "bulk": {"supported": False}, "filter": {"supported": False},
                "changePassword": {"supported": False}, "sort": {"supported": False}, "etag": {"supported": True},
                "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token", "primary": True}]}

    def upsert_user_resource(self, payload: dict[str, Any], actor: str = "scim-provisioner") -> dict[str, Any]:
        user = self._user_from_resource(payload)
        saved = self.identity_store.upsert_user(user, actor)
        return self.to_scim_user(saved)

    def patch_user_resource(self, scim_id: str, payload: dict[str, Any], actor: str = "scim-provisioner") -> dict[str, Any]:
        if SCIM_PATCH_SCHEMA not in payload.get("schemas", []):
            raise ReportFlowError("SCIM PATCH payload is missing the PatchOp schema.")
        user = self.identity_store.get_user(scim_id)
        updates: dict[str, Any] = {}
        for operation in payload.get("Operations", []):
            if str(operation.get("op", "")).lower() not in {"replace", "add"}:
                raise ReportFlowError("SCIM supports only replace/add for allowlisted User fields.")
            path = str(operation.get("path", "")).lower()
            if path not in {"active", "displayname", "emails"}:
                raise ReportFlowError("SCIM PATCH attempted to update a protected field.")
            updates[path] = operation.get("value")
        if "active" in updates:
            if not isinstance(updates["active"], bool):
                raise ReportFlowError("SCIM active must be a boolean.")
            user.active = updates["active"]
        if "displayname" in updates:
            user.display_name = _short_text(updates["displayname"], "displayName")
        if "emails" in updates:
            user.email = _primary_email(updates["emails"])
        return self.to_scim_user(self.identity_store.upsert_user(user, actor))

    def upsert_group_resource(self, payload: dict[str, Any], actor: str = "scim-provisioner") -> dict[str, Any]:
        external_id = _short_text(payload.get("externalId") or payload.get("id"), "externalId")
        display_name = _short_text(payload.get("displayName"), "displayName")
        members: list[str] = []
        for member in payload.get("members", []):
            value = _short_text(member.get("value"), "group member value")
            members.append(self.identity_store.get_user_by_external_id(value).scim_id)
        saved = self.identity_store.upsert_group(IdentityGroup("", external_id, display_name, members), actor)
        return self.to_scim_group(saved)

    def to_scim_user(self, user: IdentityUser) -> dict[str, Any]:
        resource: dict[str, Any] = {"schemas": [SCIM_USER_SCHEMA], "id": user.scim_id, "externalId": user.external_id,
            "userName": user.user_name, "displayName": user.display_name, "active": user.active,
            "meta": {"resourceType": "User", "version": f'W/"{user.version}"', "lastModified": user.updated_at}}
        if user.email:
            resource["emails"] = [{"value": user.email, "primary": True}]
        return resource

    def to_scim_group(self, group: IdentityGroup) -> dict[str, Any]:
        return {"schemas": [SCIM_GROUP_SCHEMA], "id": group.scim_id, "externalId": group.external_id, "displayName": group.display_name,
                "members": [{"value": member} for member in group.member_scim_ids],
                "meta": {"resourceType": "Group", "version": f'W/"{group.version}"', "lastModified": group.updated_at}}

    def to_list_response(self, users: list[IdentityUser], total: int, start_index: int) -> dict[str, Any]:
        return {"schemas": [SCIM_LIST_SCHEMA], "totalResults": total, "startIndex": start_index,
                "itemsPerPage": len(users), "Resources": [self.to_scim_user(user) for user in users]}

    def _user_from_resource(self, payload: dict[str, Any]) -> IdentityUser:
        schemas = payload.get("schemas", [])
        if schemas and SCIM_USER_SCHEMA not in schemas:
            raise ReportFlowError("SCIM User payload uses an unsupported schema.")
        external_id = _short_text(payload.get("externalId") or payload.get("id"), "externalId")
        groups = payload.get("groups", [])
        group_names = [str(item.get("display") or item.get("value")) for item in groups if isinstance(item, dict)]
        roles = sorted({self.group_role_mapping[name] for name in group_names if name in self.group_role_mapping})
        return IdentityUser("", external_id, _short_text(payload.get("userName"), "userName"),
                            _short_text(payload.get("displayName") or payload.get("userName"), "displayName"),
                            _primary_email(payload.get("emails", [])), bool(payload.get("active", True)), roles)


def has_permission(roles: list[str], permission: str) -> bool:
    return any(permission in ROLE_PERMISSIONS.get(role, frozenset()) for role in roles)


def _require_https_url(value: str, label: str, optional: bool = False) -> None:
    if optional and not value:
        return
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ReportFlowError(f"{label} must be a clean HTTPS URL.")


def _read_json(url: str, timeout_seconds: int) -> dict[str, Any]:
    _require_https_url(url, "Identity endpoint")
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.headers.get_content_type() != "application/json":
                raise ReportFlowError("Identity endpoint did not return JSON.")
            return dict(json.loads(response.read(1024 * 1024).decode("utf-8")))
    except ReportFlowError:
        raise
    except Exception as error:
        raise ReportFlowError("Unable to query the identity provider discovery endpoint.") from error


def _post_form(url: str, fields: dict[str, str], timeout_seconds: int) -> dict[str, Any]:
    _require_https_url(url, "OIDC token endpoint")
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return dict(json.loads(response.read(1024 * 1024).decode("utf-8")))
    except Exception as error:
        raise ReportFlowError("OIDC code exchange failed.") from error


def _single(values: dict[str, list[str]], name: str) -> str:
    items = values.get(name, [])
    if len(items) != 1 or not items[0]:
        raise ReportFlowError(f"OIDC callback is missing a valid {name} value.")
    return items[0]


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _optional_str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _stable_scim_id(external_id: str) -> str:
    return hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:32]


def _short_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
        raise ReportFlowError(f"SCIM {label} must be a nonempty string no longer than 256 characters.")
    return value.strip()


def _primary_email(value: Any) -> str | None:
    if not value:
        return None
    if not isinstance(value, list):
        raise ReportFlowError("SCIM emails must be a list.")
    candidates = [item for item in value if isinstance(item, dict) and isinstance(item.get("value"), str)]
    if not candidates:
        return None
    chosen = next((item for item in candidates if item.get("primary") is True), candidates[0])
    email = chosen["value"].strip()
    if not email or "@" not in email or len(email) > 254:
        raise ReportFlowError("SCIM email is invalid.")
    return email


def _validate_identity_user(user: IdentityUser) -> None:
    for label, value in (("externalId", user.external_id), ("userName", user.user_name), ("displayName", user.display_name)):
        _short_text(value, label)
    if user.email:
        _primary_email([{"value": user.email}])
    if not set(user.roles).issubset(ROLE_PERMISSIONS):
        raise ReportFlowError("Identity user has an undefined role.")


def _user_from_row(row: sqlite3.Row) -> IdentityUser:
    return IdentityUser(row["scim_id"], row["external_id"], row["user_name"], row["display_name"], row["email"],
                        bool(row["active"]), list(json.loads(row["roles"])), int(row["version"]), row["updated_at"])


def _group_from_row(row: sqlite3.Row) -> IdentityGroup:
    return IdentityGroup(row["scim_id"], row["external_id"], row["display_name"], list(json.loads(row["members"])),
                         int(row["version"]), row["updated_at"])

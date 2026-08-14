"""Embedded white-label portal foundation for ReportFlow v2.2.

The portal never trusts a tenant identifier sent by a browser. A short-lived,
signed server-side session is issued only after the enterprise identity layer
has authenticated a principal and proven its tenant membership.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlparse

from reportflow_app.core import ProjectStore, ReportFlowError, utc_now


_TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


@dataclass(frozen=True, slots=True)
class PortalBrand:
    display_name: str
    primary_color: str
    logo_url: str | None = None
    support_url: str | None = None
    custom_domain: str | None = None

    def validate(self) -> None:
        if not self.display_name.strip() or len(self.display_name) > 80:
            raise ReportFlowError("Portal brand display name is required and limited to 80 characters.")
        if not _HEX_COLOR.fullmatch(self.primary_color):
            raise ReportFlowError("Portal primary color must be a six-digit hex color.")
        for field_name, value in (("logo", self.logo_url), ("support", self.support_url)):
            if value is None:
                continue
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or len(value) > 500:
                raise ReportFlowError(f"Portal {field_name} URL must be an HTTPS URL without embedded credentials.")
        if self.custom_domain and not _DOMAIN.fullmatch(self.custom_domain.lower()):
            raise ReportFlowError("Portal custom domain is invalid.")


@dataclass(frozen=True, slots=True)
class PortalTenant:
    id: str
    brand: PortalBrand
    status: str = "active"

    def validate(self) -> None:
        if not _TENANT_ID.fullmatch(self.id) or self.status not in {"active", "suspended"}:
            raise ReportFlowError("Portal tenant ID or status is invalid.")
        self.brand.validate()


@dataclass(frozen=True, slots=True)
class PortalReportGrant:
    tenant_id: str
    report_id: int
    classification: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class PortalSession:
    tenant_id: str
    subject: str
    report_ids: tuple[int, ...]
    issued_at: str
    expires_at: str
    nonce: str


class PortalRegistry:
    """Stores tenant branding and per-tenant report grants, separate from report content."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        with self.store._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS portal_tenants (
                    id TEXT PRIMARY KEY,
                    brand_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','suspended')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_report_grants (
                    tenant_id TEXT NOT NULL,
                    report_id INTEGER NOT NULL,
                    classification TEXT NOT NULL CHECK(classification IN ('public','internal','confidential','restricted')),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, report_id),
                    FOREIGN KEY(tenant_id) REFERENCES portal_tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
                );
                """
            )

    def save_tenant(self, tenant: PortalTenant, actor: str = "local-user") -> PortalTenant:
        tenant.validate()
        now = utc_now()
        with self.store._connect() as connection:
            connection.execute(
                """INSERT INTO portal_tenants(id,brand_json,status,created_at,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET brand_json=excluded.brand_json,status=excluded.status,updated_at=excluded.updated_at""",
                (tenant.id, json.dumps(asdict(tenant.brand), ensure_ascii=False), tenant.status, now, now),
            )
        self.store.audit("portal.tenant.saved", "portal_tenant", tenant.id, {"status": tenant.status}, actor)
        return tenant

    def get_tenant(self, tenant_id: str) -> PortalTenant:
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM portal_tenants WHERE id=?", (tenant_id,)).fetchone()
        if row is None:
            raise ReportFlowError("Portal tenant was not found.")
        return PortalTenant(row["id"], PortalBrand(**json.loads(row["brand_json"])), row["status"])

    def grant_report(self, grant: PortalReportGrant, actor: str = "local-user") -> PortalReportGrant:
        if grant.classification not in {"public", "internal", "confidential", "restricted"}:
            raise ReportFlowError("Portal grant classification is invalid.")
        self.get_tenant(grant.tenant_id)
        self.store.get_report(grant.report_id)
        with self.store._connect() as connection:
            connection.execute(
                """INSERT INTO portal_report_grants(tenant_id,report_id,classification,enabled,created_at) VALUES(?,?,?,?,?)
                ON CONFLICT(tenant_id,report_id) DO UPDATE SET classification=excluded.classification,enabled=excluded.enabled""",
                (grant.tenant_id, grant.report_id, grant.classification, int(grant.enabled), utc_now()),
            )
        self.store.audit("portal.grant.saved", "portal_report_grant", f"{grant.tenant_id}:{grant.report_id}", {"classification": grant.classification, "enabled": grant.enabled}, actor)
        return grant

    def list_granted_reports(self, tenant_id: str) -> list[PortalReportGrant]:
        with self.store._connect() as connection:
            rows = connection.execute("SELECT * FROM portal_report_grants WHERE tenant_id=? AND enabled=1 ORDER BY report_id", (tenant_id,)).fetchall()
        return [PortalReportGrant(row["tenant_id"], row["report_id"], row["classification"], bool(row["enabled"])) for row in rows]


class PortalSessionService:
    """Signs short-lived portal sessions; signing material is loaded from a central secret at call time."""

    def __init__(self, registry: PortalRegistry, signing_secret_loader: Callable[[], str]) -> None:
        self.registry, self.signing_secret_loader = registry, signing_secret_loader

    def issue(self, tenant_id: str, subject: str, authenticated_tenants: set[str], *, ttl_minutes: int = 10) -> str:
        if tenant_id not in authenticated_tenants:
            raise ReportFlowError("Authenticated principal is not a member of the requested portal tenant.")
        tenant = self.registry.get_tenant(tenant_id)
        if tenant.status != "active":
            raise ReportFlowError("Portal tenant is suspended.")
        if not subject.strip() or len(subject) > 256 or not 1 <= ttl_minutes <= 15:
            raise ReportFlowError("Portal subject or session TTL is invalid.")
        grants = self.registry.list_granted_reports(tenant_id)
        now = datetime.now(UTC)
        session = PortalSession(tenant_id, subject.strip(), tuple(item.report_id for item in grants), now.isoformat(), (now + timedelta(minutes=ttl_minutes)).isoformat(), secrets.token_urlsafe(18))
        token = _sign_payload(asdict(session), self._secret())
        self.registry.store.audit("portal.session.issued", "portal_tenant", tenant_id, {"subject_hash": _short_hash(subject), "grant_count": len(grants), "ttl_minutes": ttl_minutes})
        return token

    def verify(self, token: str) -> PortalSession:
        payload = _verify_payload(token, self._secret())
        try:
            session = PortalSession(
                tenant_id=str(payload["tenant_id"]), subject=str(payload["subject"]), report_ids=tuple(int(value) for value in payload["report_ids"]),
                issued_at=str(payload["issued_at"]), expires_at=str(payload["expires_at"]), nonce=str(payload["nonce"]),
            )
            if datetime.fromisoformat(session.expires_at) <= datetime.now(UTC):
                raise ReportFlowError("Portal session has expired.")
        except (KeyError, TypeError, ValueError) as error:
            raise ReportFlowError("Portal session token is malformed.") from error
        tenant = self.registry.get_tenant(session.tenant_id)
        if tenant.status != "active":
            raise ReportFlowError("Portal tenant is suspended.")
        current_grants = {item.report_id for item in self.registry.list_granted_reports(session.tenant_id)}
        if not set(session.report_ids).issubset(current_grants):
            raise ReportFlowError("Portal session grants are no longer valid.")
        return session

    def assert_report_access(self, token: str, tenant_id: str, report_id: int) -> PortalSession:
        session = self.verify(token)
        if not secrets.compare_digest(session.tenant_id, tenant_id) or report_id not in session.report_ids:
            raise ReportFlowError("Portal report access is not authorized for this tenant session.")
        return session

    def render_shell(self, token: str) -> str:
        session = self.verify(token)
        tenant = self.registry.get_tenant(session.tenant_id)
        reports = [self.registry.store.get_report(report_id) for report_id in session.report_ids]
        logo = f'<img src="{html.escape(tenant.brand.logo_url, quote=True)}" alt="" class="logo">' if tenant.brand.logo_url else ""
        report_items = "".join(f'<li data-report-id="{report.id}">{html.escape(report.title)}</li>' for report in reports)
        support = f'<a rel="noopener noreferrer" target="_blank" href="{html.escape(tenant.brand.support_url, quote=True)}">Support</a>' if tenant.brand.support_url else ""
        return (
            "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(tenant.brand.display_name)} Reports</title><style>:root{{--brand:{tenant.brand.primary_color};}}body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f8fafc;color:#14213d}}header{{background:var(--brand);color:#fff;padding:28px}}main{{padding:28px;max-width:960px;margin:auto}}.logo{{height:38px;vertical-align:middle;margin-right:12px}}li{{padding:12px;border-bottom:1px solid #e5e7eb}}</style></head>"
            f"<body><header>{logo}<strong>{html.escape(tenant.brand.display_name)}</strong></header><main><h1>Reports</h1><ul>{report_items}</ul>{support}</main></body></html>"
        )

    def _secret(self) -> bytes:
        secret = self.signing_secret_loader()
        if not secret or len(secret) < 32:
            raise ReportFlowError("Portal signing secret must be centrally managed and at least 32 characters.")
        return secret.encode("utf-8")


def _sign_payload(payload: dict[str, Any], secret: bytes) -> str:
    encoded = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    return f"p1.{encoded}.{_b64(signature)}"


def _verify_payload(token: str, secret: bytes) -> dict[str, Any]:
    try:
        version, encoded, supplied = token.split(".", 2)
        expected = _b64(hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest())
        if version != "p1" or not secrets.compare_digest(supplied, expected):
            raise ReportFlowError("Portal session signature is invalid.")
        return dict(json.loads(_unb64(encoded)))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReportFlowError("Portal session token is malformed.") from error


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

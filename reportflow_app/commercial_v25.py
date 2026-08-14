"""Commercial entitlements and usage metering for ReportFlow v2.5.

This module enforces product packaging without handling payment cards, invoices or
raw customer data. It creates auditable plan snapshots, tenant-scoped feature
gates and idempotent usage events that can later feed a billing provider.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, Mapping, TYPE_CHECKING
from uuid import uuid4

from reportflow_app.core import ProjectStore, ReportFlowError, utc_now

if TYPE_CHECKING:
    from reportflow_app.distribution_v22 import DistributionJob, DistributionQueue, RetryPolicy


OverageBehavior = Literal["deny", "allow"]
SubscriptionStatus = Literal["active", "suspended", "cancelled"]
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$")
_SAFE_FEATURE = re.compile(r"^[a-z][a-z0-9_:-]{2,63}$")
_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_ALLOWED_STATUS = {"active", "suspended", "cancelled"}
_ALLOWED_OVERAGE = {"deny", "allow"}


@dataclass(frozen=True, slots=True)
class CommercialPlan:
    id: str
    version: int
    display_name: str
    feature_flags: tuple[str, ...]
    meter_limits: dict[str, int]
    overage_behavior: OverageBehavior
    commercial_sku: str
    created_at: str

    def validate(self) -> None:
        _validate_id(self.id, "Plan ID")
        if not 1 <= self.version <= 10_000:
            raise ReportFlowError("Plan version must be between 1 and 10000.")
        if not self.display_name.strip() or len(self.display_name.strip()) > 120:
            raise ReportFlowError("Plan display name is required and must be at most 120 characters.")
        if not self.feature_flags or len(set(self.feature_flags)) != len(self.feature_flags):
            raise ReportFlowError("Plan feature flags must be non-empty and unique.")
        if any(not _SAFE_FEATURE.fullmatch(item) for item in self.feature_flags):
            raise ReportFlowError("Plan contains an invalid feature flag.")
        if not self.meter_limits or any(not _SAFE_FEATURE.fullmatch(meter) or not isinstance(limit, int) or not 1 <= limit <= 100_000_000 for meter, limit in self.meter_limits.items()):
            raise ReportFlowError("Plan meter limits must use valid names and positive integer limits.")
        if self.overage_behavior not in _ALLOWED_OVERAGE:
            raise ReportFlowError("Plan overage behavior is invalid.")
        _validate_id(self.commercial_sku, "Commercial SKU")


@dataclass(frozen=True, slots=True)
class TenantEntitlement:
    tenant_id: str
    plan_id: str
    plan_version: int
    status: SubscriptionStatus
    feature_overrides: tuple[str, ...]
    limit_overrides: dict[str, int]
    effective_from: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class EntitlementDecision:
    allowed: bool
    tenant_id: str
    feature: str
    reason: str
    plan_id: str | None = None
    plan_version: int | None = None


@dataclass(frozen=True, slots=True)
class UsageEvent:
    id: str
    tenant_id: str
    meter: str
    quantity: int
    idempotency_key: str
    billing_period: str
    overage_units: int
    metadata: dict[str, Any]
    occurred_at: str


@dataclass(frozen=True, slots=True)
class UsageSummary:
    tenant_id: str
    meter: str
    billing_period: str
    used: int
    included: int
    remaining: int
    overage: int
    overage_behavior: OverageBehavior


class CommercialCatalog:
    """Persist plans, tenant plan assignments and billing-provider-neutral usage."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self._initialize()

    def _initialize(self) -> None:
        with self.store._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS commercial_plans (
                    id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    feature_flags TEXT NOT NULL,
                    meter_limits TEXT NOT NULL,
                    overage_behavior TEXT NOT NULL CHECK(overage_behavior IN ('deny','allow')),
                    commercial_sku TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(id, version)
                );
                CREATE TABLE IF NOT EXISTS commercial_tenant_entitlements (
                    tenant_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','suspended','cancelled')),
                    feature_overrides TEXT NOT NULL,
                    limit_overrides TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id, plan_version) REFERENCES commercial_plans(id, version)
                );
                CREATE TABLE IF NOT EXISTS commercial_usage_events (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    meter TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    billing_period TEXT NOT NULL,
                    overage_units INTEGER NOT NULL CHECK(overage_units >= 0),
                    metadata TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_commercial_usage_period
                    ON commercial_usage_events(tenant_id, meter, billing_period);
                """
            )

    def save_plan(self, plan: CommercialPlan, *, actor: str = "commercial-admin") -> CommercialPlan:
        plan.validate()
        _validate_id(actor, "Commercial actor")
        if plan.created_at:
            created_at = plan.created_at
        else:
            created_at = utc_now()
        frozen = CommercialPlan(plan.id, plan.version, plan.display_name.strip(), tuple(sorted(plan.feature_flags)),
                                dict(sorted(plan.meter_limits.items())), plan.overage_behavior, plan.commercial_sku, created_at)
        with self.store._connect() as connection:
            existing = connection.execute("SELECT * FROM commercial_plans WHERE id=? AND version=?", (frozen.id, frozen.version)).fetchone()
            if existing is not None:
                loaded = self._row_to_plan(existing)
                if loaded != frozen:
                    raise ReportFlowError("Commercial plans are immutable; create a new version instead.")
                return loaded
            connection.execute(
                """INSERT INTO commercial_plans(id,version,display_name,feature_flags,meter_limits,overage_behavior,commercial_sku,created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (frozen.id, frozen.version, frozen.display_name, _canonical_json(list(frozen.feature_flags)),
                 _canonical_json(frozen.meter_limits), frozen.overage_behavior, frozen.commercial_sku, frozen.created_at),
            )
        self.store.audit("commercial.plan_created", "commercial_plan", f"{frozen.id}:{frozen.version}", {
            "sku": frozen.commercial_sku, "feature_count": len(frozen.feature_flags), "meter_count": len(frozen.meter_limits),
        }, actor=actor)
        return frozen

    def get_plan(self, plan_id: str, version: int) -> CommercialPlan:
        _validate_id(plan_id, "Plan ID")
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM commercial_plans WHERE id=? AND version=?", (plan_id, version)).fetchone()
        if row is None:
            raise ReportFlowError("Commercial plan version was not found.")
        return self._row_to_plan(row)

    def assign_tenant(self, tenant_id: str, plan_id: str, plan_version: int, *, status: SubscriptionStatus = "active",
                      feature_overrides: tuple[str, ...] = (), limit_overrides: Mapping[str, int] | None = None,
                      effective_from: str = "", actor: str = "commercial-admin") -> TenantEntitlement:
        _validate_id(tenant_id, "Tenant ID")
        _validate_id(actor, "Commercial actor")
        plan = self.get_plan(plan_id, plan_version)
        if status not in _ALLOWED_STATUS:
            raise ReportFlowError("Tenant entitlement status is invalid.")
        normalized_features = tuple(sorted(set(feature_overrides)))
        if any(not _SAFE_FEATURE.fullmatch(item) for item in normalized_features):
            raise ReportFlowError("Tenant feature overrides are invalid.")
        normalized_limits = dict(sorted((limit_overrides or {}).items()))
        if any(not _SAFE_FEATURE.fullmatch(meter) or not isinstance(limit, int) or not 1 <= limit <= 100_000_000 for meter, limit in normalized_limits.items()):
            raise ReportFlowError("Tenant limit overrides are invalid.")
        if any(meter not in plan.meter_limits for meter in normalized_limits):
            raise ReportFlowError("Tenant limit override references a meter absent from the plan.")
        now = utc_now()
        entitlement = TenantEntitlement(tenant_id, plan.id, plan.version, status, normalized_features, normalized_limits, effective_from or now, now)
        with self.store._connect() as connection:
            connection.execute(
                """INSERT INTO commercial_tenant_entitlements(tenant_id,plan_id,plan_version,status,feature_overrides,limit_overrides,effective_from,updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET plan_id=excluded.plan_id,plan_version=excluded.plan_version,status=excluded.status,
                    feature_overrides=excluded.feature_overrides,limit_overrides=excluded.limit_overrides,effective_from=excluded.effective_from,updated_at=excluded.updated_at""",
                (entitlement.tenant_id, entitlement.plan_id, entitlement.plan_version, entitlement.status,
                 _canonical_json(list(entitlement.feature_overrides)), _canonical_json(entitlement.limit_overrides),
                 entitlement.effective_from, entitlement.updated_at),
            )
        self.store.audit("commercial.tenant_assigned", "tenant_entitlement", tenant_id, {
            "plan_id": plan.id, "plan_version": plan.version, "status": status,
        }, actor=actor)
        return entitlement

    def get_entitlement(self, tenant_id: str) -> TenantEntitlement:
        _validate_id(tenant_id, "Tenant ID")
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM commercial_tenant_entitlements WHERE tenant_id=?", (tenant_id,)).fetchone()
        if row is None:
            raise ReportFlowError("Tenant does not have a commercial entitlement.")
        return self._row_to_entitlement(row)

    def check_feature(self, tenant_id: str, feature: str) -> EntitlementDecision:
        _validate_id(tenant_id, "Tenant ID")
        if not _SAFE_FEATURE.fullmatch(feature):
            raise ReportFlowError("Commercial feature is invalid.")
        try:
            entitlement = self.get_entitlement(tenant_id)
        except ReportFlowError:
            return EntitlementDecision(False, tenant_id, feature, "tenant_has_no_plan")
        if entitlement.status != "active":
            return EntitlementDecision(False, tenant_id, feature, f"subscription_{entitlement.status}", entitlement.plan_id, entitlement.plan_version)
        plan = self.get_plan(entitlement.plan_id, entitlement.plan_version)
        allowed = feature in set(plan.feature_flags) | set(entitlement.feature_overrides)
        return EntitlementDecision(allowed, tenant_id, feature, "feature_enabled" if allowed else "feature_not_in_plan", plan.id, plan.version)

    def usage_summary(self, tenant_id: str, meter: str, billing_period: str) -> UsageSummary:
        _validate_id(tenant_id, "Tenant ID")
        _validate_meter(meter)
        _validate_period(billing_period)
        entitlement = self.get_entitlement(tenant_id)
        plan = self.get_plan(entitlement.plan_id, entitlement.plan_version)
        if meter not in plan.meter_limits:
            raise ReportFlowError("Meter is not included in the tenant plan.")
        limit = entitlement.limit_overrides.get(meter, plan.meter_limits[meter])
        with self.store._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS used FROM commercial_usage_events WHERE tenant_id=? AND meter=? AND billing_period=?",
                (tenant_id, meter, billing_period),
            ).fetchone()
        used = int(row["used"])
        return UsageSummary(tenant_id, meter, billing_period, used, limit, max(0, limit - used), max(0, used - limit), plan.overage_behavior)

    def record_usage(self, tenant_id: str, meter: str, quantity: int, idempotency_key: str, billing_period: str, *,
                     metadata: Mapping[str, Any] | None = None, actor: str = "usage-worker") -> UsageEvent:
        _validate_id(tenant_id, "Tenant ID")
        _validate_meter(meter)
        _validate_id(idempotency_key, "Usage idempotency key")
        _validate_id(actor, "Usage actor")
        _validate_period(billing_period)
        if not isinstance(quantity, int) or not 1 <= quantity <= 1_000_000:
            raise ReportFlowError("Usage quantity must be an integer between 1 and 1000000.")
        safe_metadata = _safe_metadata(metadata or {})
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT * FROM commercial_usage_events WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing is not None:
                event = self._row_to_event(existing)
                if event.tenant_id != tenant_id or event.meter != meter or event.quantity != quantity or event.billing_period != billing_period:
                    raise ReportFlowError("Usage idempotency key was already used with different event data.")
                connection.commit()
                return event
            entitlement = self._get_entitlement_in_connection(connection, tenant_id)
            if entitlement.status != "active":
                raise ReportFlowError("Usage cannot be recorded for an inactive tenant subscription.")
            plan = self._get_plan_in_connection(connection, entitlement.plan_id, entitlement.plan_version)
            if meter not in plan.meter_limits:
                raise ReportFlowError("Meter is not included in the tenant plan.")
            limit = entitlement.limit_overrides.get(meter, plan.meter_limits[meter])
            used_row = connection.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS used FROM commercial_usage_events WHERE tenant_id=? AND meter=? AND billing_period=?",
                (tenant_id, meter, billing_period),
            ).fetchone()
            used = int(used_row["used"])
            projected = used + quantity
            if projected > limit and plan.overage_behavior == "deny":
                connection.rollback()
                self.store.audit("commercial.usage_denied", "tenant_entitlement", tenant_id, {
                    "meter": meter, "billing_period": billing_period, "limit": limit, "used": used, "requested": quantity,
                }, actor=actor)
                raise ReportFlowError("Usage would exceed the tenant plan limit.")
            event_id, now = str(uuid4()), utc_now()
            event = UsageEvent(event_id, tenant_id, meter, quantity, idempotency_key, billing_period,
                               max(0, projected - limit) - max(0, used - limit), safe_metadata, now)
            connection.execute(
                """INSERT INTO commercial_usage_events(id,tenant_id,meter,quantity,idempotency_key,billing_period,overage_units,metadata,occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event.id, event.tenant_id, event.meter, event.quantity, event.idempotency_key, event.billing_period,
                 event.overage_units, _canonical_json(event.metadata), event.occurred_at),
            )
            connection.commit()
        self.store.audit("commercial.usage_recorded", "usage_event", event.id, {
            "tenant_id": tenant_id, "meter": meter, "quantity": quantity, "billing_period": billing_period,
            "overage_units": event.overage_units,
        }, actor=actor)
        return event

    def preflight_usage(self, tenant_id: str, meter: str, quantity: int, billing_period: str) -> UsageSummary:
        """Validate a prospective usage event without creating billable usage."""
        summary = self.usage_summary(tenant_id, meter, billing_period)
        if self.get_entitlement(tenant_id).status != "active":
            raise ReportFlowError("Tenant subscription is inactive.")
        if not isinstance(quantity, int) or quantity < 1:
            raise ReportFlowError("Prospective usage quantity must be positive.")
        if summary.used + quantity > summary.included and summary.overage_behavior == "deny":
            raise ReportFlowError("Prospective usage would exceed the tenant plan limit.")
        return summary

    def _get_entitlement_in_connection(self, connection: sqlite3.Connection, tenant_id: str) -> TenantEntitlement:
        row = connection.execute("SELECT * FROM commercial_tenant_entitlements WHERE tenant_id=?", (tenant_id,)).fetchone()
        if row is None:
            raise ReportFlowError("Tenant does not have a commercial entitlement.")
        return self._row_to_entitlement(row)

    def _get_plan_in_connection(self, connection: sqlite3.Connection, plan_id: str, version: int) -> CommercialPlan:
        row = connection.execute("SELECT * FROM commercial_plans WHERE id=? AND version=?", (plan_id, version)).fetchone()
        if row is None:
            raise ReportFlowError("Commercial plan version was not found.")
        return self._row_to_plan(row)

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> CommercialPlan:
        return CommercialPlan(str(row["id"]), int(row["version"]), str(row["display_name"]), tuple(json.loads(row["feature_flags"])),
                              {str(key): int(value) for key, value in json.loads(row["meter_limits"]).items()}, str(row["overage_behavior"]),
                              str(row["commercial_sku"]), str(row["created_at"]))

    @staticmethod
    def _row_to_entitlement(row: sqlite3.Row) -> TenantEntitlement:
        return TenantEntitlement(str(row["tenant_id"]), str(row["plan_id"]), int(row["plan_version"]), str(row["status"]),
                                 tuple(json.loads(row["feature_overrides"])), {str(key): int(value) for key, value in json.loads(row["limit_overrides"]).items()},
                                 str(row["effective_from"]), str(row["updated_at"]))

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> UsageEvent:
        return UsageEvent(str(row["id"]), str(row["tenant_id"]), str(row["meter"]), int(row["quantity"]),
                          str(row["idempotency_key"]), str(row["billing_period"]), int(row["overage_units"]),
                          json.loads(row["metadata"]), str(row["occurred_at"]))


class CommercialDistributionGate:
    """Checks packaging before queue enrollment; usage is recorded on successful delivery."""

    def __init__(self, commercial: CommercialCatalog) -> None:
        self.commercial = commercial

    def enqueue_entitled(self, queue: "DistributionQueue", tenant_id: str, *, kind: str, payload: Mapping[str, Any],
                         idempotency_key: str, retry_policy: "RetryPolicy", billing_period: str, priority: int = 0,
                         actor: str = "distribution-worker") -> tuple["DistributionJob", bool]:
        decision = self.commercial.check_feature(tenant_id, "distribution_queue")
        if not decision.allowed:
            raise ReportFlowError(f"Distribution queue is not entitled: {decision.reason}.")
        self.commercial.preflight_usage(tenant_id, "successful_delivery", 1, billing_period)
        return queue.enqueue(kind, dict(payload), idempotency_key, retry_policy=retry_policy, priority=priority, actor=actor)

    def record_success(self, tenant_id: str, job_id: str, billing_period: str, *, actor: str = "distribution-worker") -> UsageEvent:
        _validate_id(job_id, "Distribution job ID")
        return self.commercial.record_usage(tenant_id, "successful_delivery", 1, f"delivery-success:{job_id}", billing_period,
                                            metadata={"distribution_job_id": job_id}, actor=actor)


def _validate_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ReportFlowError(f"{label} is invalid.")


def _validate_meter(value: str) -> None:
    if not isinstance(value, str) or not _SAFE_FEATURE.fullmatch(value):
        raise ReportFlowError("Usage meter is invalid.")


def _validate_period(value: str) -> None:
    if not isinstance(value, str) or not _PERIOD.fullmatch(value):
        raise ReportFlowError("Billing period must use YYYY-MM format.")


def _safe_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReportFlowError("Usage metadata must be a JSON object.")
    try:
        copied = json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError) as error:
        raise ReportFlowError("Usage metadata must be JSON-serializable without non-finite values.") from error
    if len(_canonical_json(copied).encode("utf-8")) > 16_000:
        raise ReportFlowError("Usage metadata exceeds the 16 KiB limit.")
    blocked = {"password", "secret", "token", "access_key", "private_key", "email"}
    if any(str(key).lower() in blocked for key in _walk_keys(copied)):
        raise ReportFlowError("Usage metadata cannot contain credentials or recipient identity.")
    return copied


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

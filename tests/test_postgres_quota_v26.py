from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from reportflow_app.core import ReportFlowError
from reportflow_app.postgres_quota_v26 import AdmissionRequest, PostgresQuotaReservationService, QuotaGrant


def _request(**overrides):
    grant = QuotaGrant(
        tenant_id="tenant-alpha",
        meter="successful_delivery",
        billing_period=date(2026, 8, 1),
        quota_scope_id="growth-v2-2026-08",
        plan_id="growth-v2",
        plan_version=2,
        entitlement_effective_from=datetime(2026, 8, 1, tzinfo=UTC),
        overage_behavior="deny",
        included_units=10,
    )
    values = {
        "grant": grant,
        "idempotency_key": "admission-tenant-alpha-0001",
        "kind": "report-delivery",
        "payload": {"report_id": "monthly-summary"},
        "quantity": 1,
        "reservation_ttl_seconds": 300,
        "actor_subject": "workload-distributor",
        "priority": 0,
    }
    values.update(overrides)
    return AdmissionRequest(**values)


def test_admission_validation_accepts_server_issued_month_scope():
    PostgresQuotaReservationService._validate_admission(_request())


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("quantity", 0, "Reservation quantity"),
        ("reservation_ttl_seconds", 10, "Reservation quantity"),
        ("priority", 101, "Distribution priority"),
        ("payload", {"not_json": {1, 2}}, "JSON serializable"),
    ],
)
def test_admission_validation_rejects_unsafe_requests(field, value, error):
    with pytest.raises(ReportFlowError, match=error):
        PostgresQuotaReservationService._validate_admission(_request(**{field: value}))


def test_admission_validation_requires_month_start_and_timezone_aware_snapshot():
    invalid_period = _request(grant=QuotaGrant(
        tenant_id="tenant-alpha", meter="successful_delivery", billing_period=date(2026, 8, 2),
        quota_scope_id="growth-v2-2026-08", plan_id="growth-v2", plan_version=2,
        entitlement_effective_from=datetime(2026, 8, 1, tzinfo=UTC), overage_behavior="deny", included_units=10,
    ))
    with pytest.raises(ReportFlowError, match="Billing period"):
        PostgresQuotaReservationService._validate_admission(invalid_period)

    naive_snapshot = _request(grant=QuotaGrant(
        tenant_id="tenant-alpha", meter="successful_delivery", billing_period=date(2026, 8, 1),
        quota_scope_id="growth-v2-2026-08", plan_id="growth-v2", plan_version=2,
        entitlement_effective_from=datetime(2026, 8, 1), overage_behavior="deny", included_units=10,
    ))
    with pytest.raises(ReportFlowError, match="snapshot"):
        PostgresQuotaReservationService._validate_admission(naive_snapshot)


def test_idempotency_reuse_rejects_different_commercial_scope_or_quantity():
    existing = {
        "tenant_id": "tenant-alpha", "meter": "successful_delivery", "billing_period": date(2026, 8, 1),
        "quota_scope_id": "growth-v2-2026-08", "quantity": 1,
    }
    PostgresQuotaReservationService._assert_same_request(existing, _request())
    with pytest.raises(ReportFlowError, match="idempotency"):
        PostgresQuotaReservationService._assert_same_request(existing, _request(quantity=2))


def test_schema_and_service_include_required_postgresql_atomicity_primitives():
    root = Path(__file__).parents[1]
    schema = (root / "migrations/postgres/001_v26_atomic_quota_reservation.sql").read_text(encoding="utf-8")
    service = (root / "reportflow_app/postgres_quota_v26.py").read_text(encoding="utf-8")
    assert "PRIMARY KEY (tenant_id, meter, billing_period, quota_scope_id)" in schema
    assert "idempotency_key TEXT NOT NULL UNIQUE" in schema
    assert "FOR UPDATE" in service
    assert "FOR UPDATE SKIP LOCKED" in service
    assert "rf_outbox_events" in service

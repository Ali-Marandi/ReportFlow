"""Real PostgreSQL concurrency tests for the v2.6.1 control-plane reference.

Run only with an isolated disposable database:
    REPORTFLOW_TEST_POSTGRES_DSN=postgresql://... pytest -q -m postgres_integration

The test database is truncated before each test. Never point this DSN at production,
staging shared with other services, or a database containing customer data.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier

import pytest
from psycopg import connect
from psycopg.rows import dict_row

from reportflow_app.postgres_quota_v26 import AdmissionRequest, PostgresQuotaReservationService, QuotaExceeded, QuotaGrant

pytestmark = pytest.mark.postgres_integration


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.environ.get("REPORTFLOW_TEST_POSTGRES_DSN", "")
    if not dsn:
        pytest.skip("REPORTFLOW_TEST_POSTGRES_DSN is required for real PostgreSQL concurrency tests.")
    return dsn


@pytest.fixture(autouse=True)
def clean_schema(postgres_dsn: str):
    root = Path(__file__).parents[2]
    migrations = [
        root / "migrations/postgres/001_v26_atomic_quota_reservation.sql",
        root / "migrations/postgres/002_v261_outbox_worker_leases.sql",
    ]
    with connect(postgres_dsn, autocommit=True) as connection:
        for migration in migrations:
            connection.execute(migration.read_text(encoding="utf-8"))
        connection.execute(
            "TRUNCATE rf_usage_events,rf_quota_reservations,rf_distribution_jobs,rf_quota_buckets,rf_outbox_events RESTART IDENTITY CASCADE"
        )
    yield


def _request(key: str, *, included_units: int = 5, quantity: int = 1) -> AdmissionRequest:
    grant = QuotaGrant(
        tenant_id="tenant-concurrency",
        meter="successful_delivery",
        billing_period=date(2026, 8, 1),
        quota_scope_id="growth-v2-2026-08",
        plan_id="growth-v2",
        plan_version=2,
        entitlement_effective_from=datetime(2026, 8, 1, tzinfo=UTC),
        overage_behavior="deny",
        included_units=included_units,
    )
    return AdmissionRequest(
        grant=grant,
        idempotency_key=key,
        kind="report-delivery",
        payload={"report_id": "concurrency-demo"},
        quantity=quantity,
        reservation_ttl_seconds=300,
        actor_subject="workload-concurrency-test",
    )


def test_parallel_admissions_never_oversubscribe_a_deny_quota(postgres_dsn: str):
    """Twenty concurrent requests compete for five units; exactly five may hold quota."""
    barrier = Barrier(20)

    def attempt(index: int):
        barrier.wait()
        try:
            return PostgresQuotaReservationService(postgres_dsn).admit(
                _request(f"parallel-admission-{index:03d}", included_units=5)
            )
        except QuotaExceeded:
            return None

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(attempt, range(20)))

    successes = [result for result in results if result is not None]
    assert len(successes) == 5
    assert len({result.job_id for result in successes}) == 5
    assert len({result.reservation_id for result in successes}) == 5
    with connect(postgres_dsn, row_factory=dict_row) as connection:
        bucket = connection.execute(
            "SELECT included_units,consumed_units,held_units FROM rf_quota_buckets WHERE tenant_id=%s",
            ("tenant-concurrency",),
        ).fetchone()
        held = connection.execute("SELECT count(*) AS count FROM rf_quota_reservations WHERE state='held'").fetchone()
    assert dict(bucket) == {"included_units": 5, "consumed_units": 0, "held_units": 5}
    assert int(held["count"]) == 5


def test_parallel_same_idempotency_key_returns_one_job_and_reservation(postgres_dsn: str):
    """A retry storm for one client request creates no duplicate billable hold or job."""
    barrier = Barrier(12)

    def attempt(_: int):
        barrier.wait()
        return PostgresQuotaReservationService(postgres_dsn).admit(
            _request("same-request-idempotency-001", included_units=10)
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(attempt, range(12)))

    assert sum(result.created for result in results) == 1
    assert len({result.job_id for result in results}) == 1
    assert len({result.reservation_id for result in results}) == 1
    with connect(postgres_dsn, row_factory=dict_row) as connection:
        rows = connection.execute("SELECT count(*) AS count FROM rf_quota_reservations").fetchone()
        bucket = connection.execute("SELECT held_units FROM rf_quota_buckets WHERE tenant_id=%s", ("tenant-concurrency",)).fetchone()
    assert int(rows["count"]) == 1
    assert int(bucket["held_units"]) == 1


def test_parallel_outbox_claims_are_disjoint_and_cover_every_ready_event(postgres_dsn: str):
    """Two publishers use SKIP LOCKED to lease disjoint events without head-of-line blocking."""
    service = PostgresQuotaReservationService(postgres_dsn)
    for index in range(12):
        service.admit(_request(f"outbox-seed-{index:03d}", included_units=20))

    barrier = Barrier(2)

    def claim(publisher: str):
        barrier.wait()
        return PostgresQuotaReservationService(postgres_dsn).claim_outbox(publisher, batch_size=6, lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(claim, ("outbox-publisher-a", "outbox-publisher-b")))

    first_ids = {lease.event_id for lease in first}
    second_ids = {lease.event_id for lease in second}
    assert len(first_ids) == len(second_ids) == 6
    assert first_ids.isdisjoint(second_ids)
    assert {lease.lease_owner for lease in first} == {"outbox-publisher-a"}
    assert {lease.lease_owner for lease in second} == {"outbox-publisher-b"}
    with connect(postgres_dsn, row_factory=dict_row) as connection:
        leased = connection.execute(
            "SELECT count(*) AS count FROM rf_outbox_events WHERE published_at IS NULL AND lease_owner IS NOT NULL"
        ).fetchone()
    assert int(leased["count"]) == 12

"""PostgreSQL control-plane sample for atomic quota reservations and transactional outbox.

This module is deliberately server-side only. A desktop client must call an authenticated
control-plane API; it must never receive PostgreSQL credentials or direct write privileges.

Schema: migrations/postgres/001_v26_atomic_quota_reservation.sql
Dependency: psycopg[binary]>=3.1 from requirements-enterprise.txt
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Literal, Mapping, Protocol
from uuid import UUID

from psycopg import Connection, connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from reportflow_app.core import ReportFlowError

OverageBehavior = Literal["deny", "allow"]
TerminalReason = Literal["cancelled", "dead_letter"]
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$")
_SAFE_METER = re.compile(r"^[a-z][a-z0-9_:-]{2,63}$")


@dataclass(frozen=True, slots=True)
class QuotaGrant:
    """Immutable commercial snapshot supplied only by the entitlement service."""

    tenant_id: str
    meter: str
    billing_period: date
    quota_scope_id: str
    plan_id: str
    plan_version: int
    entitlement_effective_from: datetime
    overage_behavior: OverageBehavior
    included_units: int


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    grant: QuotaGrant
    idempotency_key: str
    kind: str
    payload: Mapping[str, Any]
    quantity: int
    reservation_ttl_seconds: int
    actor_subject: str
    priority: int = 0


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    job_id: UUID
    reservation_id: UUID
    created: bool
    expires_at: datetime
    held_units: int
    available_units: int
    overage_units: int
    plan_id: str
    plan_version: int


@dataclass(frozen=True, slots=True)
class UsageConsumption:
    reservation_id: UUID
    usage_event_id: UUID
    consumed_units: int
    overage_units: int


@dataclass(frozen=True, slots=True)
class OutboxLease:
    event_id: UUID
    event_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    lease_token: UUID
    lease_owner: str
    publish_attempts: int = 1


@dataclass(frozen=True, slots=True)
class ExponentialBackoffPolicy:
    """Full-jitter retry policy; delay is uniform in [0, capped exponential delay]."""

    max_attempts: int = 5
    base_delay_seconds: int = 2
    max_delay_seconds: int = 300

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 100:
            raise ReportFlowError("Outbox max attempts is invalid.")
        if not 1 <= self.base_delay_seconds <= self.max_delay_seconds <= 86_400:
            raise ReportFlowError("Outbox retry delay policy is invalid.")

    def retry_delay_seconds(self, publish_attempts: int, *, random_value: float) -> int:
        if not 1 <= publish_attempts < self.max_attempts:
            raise ReportFlowError("Outbox retry is not permitted after the maximum attempt.")
        if not 0.0 <= random_value < 1.0:
            raise ReportFlowError("Outbox jitter value is invalid.")
        cap = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (publish_attempts - 1)))
        return max(1, int(random_value * cap) + 1)


@dataclass(frozen=True, slots=True)
class OutboxRunResult:
    claimed: int
    published: int
    deferred: int
    dead_lettered: int


class OutboxSink(Protocol):
    """Broker adapter. Consumers must deduplicate by the supplied idempotency key."""

    def publish(self, event_type: str, payload: Mapping[str, Any], *, idempotency_key: str) -> None:
        """Publish a durable event or raise a recoverable exception."""


class QuotaExceeded(ReportFlowError):
    """Raised when a deny-overage commercial policy has no remaining quota."""


class PostgresQuotaReservationService:
    """Coordinates quota admission, queue enrollment, usage and outbox publication.

    Every public state-changing method owns one short PostgreSQL transaction. The caller
    obtains tenant identity and commercial grant from an authenticated server-side layer.
    The module trusts neither a desktop tenant ID nor an arbitrary billing-period string.
    """

    def __init__(self, conninfo: str) -> None:
        if not conninfo or len(conninfo) > 4_096:
            raise ReportFlowError("PostgreSQL connection configuration is invalid.")
        self.conninfo = conninfo

    def admit(self, request: AdmissionRequest) -> AdmissionResult:
        """Atomically reserve quota, create one job, and append one outbox event.

        Retrying the same idempotency key returns the original reservation/job. A caller
        cannot use the same key with a different tenant, meter, billing scope or quantity.
        """
        self._validate_admission(request)
        with self._connection() as connection, connection.transaction():
            existing = self._existing_admission(connection, request.idempotency_key)
            if existing is not None:
                self._assert_same_request(existing, request)
                return self._admission_from_row(existing, created=False)

            bucket = self._lock_or_create_bucket(connection, request.grant)
            consumed, held = int(bucket["consumed_units"]), int(bucket["held_units"])
            effective_before = consumed + held
            available = max(0, int(bucket["included_units"]) - effective_before)
            projected = effective_before + request.quantity
            overage_before = max(0, effective_before - int(bucket["included_units"]))
            overage_after = max(0, projected - int(bucket["included_units"]))
            overage_delta = overage_after - overage_before
            if request.grant.overage_behavior == "deny" and request.quantity > available:
                raise QuotaExceeded(
                    f"Quota exhausted for meter '{request.grant.meter}': "
                    f"available={available}, requested={request.quantity}."
                )

            now = datetime.now(UTC)
            expires_at = now + timedelta(seconds=request.reservation_ttl_seconds)
            job_row = connection.execute(
                """
                INSERT INTO rf_distribution_jobs (tenant_id,idempotency_key,kind,payload,priority)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """,
                (request.grant.tenant_id, request.idempotency_key, request.kind, Jsonb(dict(request.payload)), request.priority),
            ).fetchone()
            if job_row is None:
                # Another transaction committed the same idempotency key while this one waited on the bucket.
                existing = self._existing_admission(connection, request.idempotency_key)
                if existing is None:
                    raise ReportFlowError("Admission idempotency conflict could not be resolved.")
                self._assert_same_request(existing, request)
                return self._admission_from_row(existing, created=False)
            job_id = UUID(str(job_row["id"]))

            reservation_row = connection.execute(
                """
                INSERT INTO rf_quota_reservations (
                    tenant_id,meter,billing_period,quota_scope_id,distribution_job_id,idempotency_key,
                    quantity,overage_units,state,reason,plan_id,plan_version,entitlement_effective_from,
                    expires_at,actor_subject
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'held','enqueue',%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    request.grant.tenant_id, request.grant.meter, request.grant.billing_period,
                    request.grant.quota_scope_id, job_id, request.idempotency_key, request.quantity,
                    overage_delta, request.grant.plan_id, request.grant.plan_version,
                    request.grant.entitlement_effective_from, expires_at, request.actor_subject,
                ),
            ).fetchone()
            reservation_id = UUID(str(reservation_row["id"]))
            connection.execute(
                """
                UPDATE rf_quota_buckets
                SET held_units=held_units+%s,
                    overage_held_units=overage_held_units+%s,
                    row_version=row_version+1,
                    updated_at=now()
                WHERE tenant_id=%s AND meter=%s AND billing_period=%s AND quota_scope_id=%s
                """,
                (
                    request.quantity, overage_delta, request.grant.tenant_id, request.grant.meter,
                    request.grant.billing_period, request.grant.quota_scope_id,
                ),
            )
            self._append_outbox(
                connection,
                aggregate_type="distribution_job",
                aggregate_id=job_id,
                event_type="distribution.admitted",
                dedupe_key=f"distribution.admitted:{job_id}",
                payload={
                    "job_id": str(job_id), "reservation_id": str(reservation_id),
                    "tenant_id": request.grant.tenant_id, "meter": request.grant.meter,
                    "billing_period": request.grant.billing_period.isoformat(),
                    "quota_scope_id": request.grant.quota_scope_id,
                },
            )
            return AdmissionResult(
                job_id=job_id,
                reservation_id=reservation_id,
                created=True,
                expires_at=expires_at,
                held_units=held + request.quantity,
                available_units=max(0, available - request.quantity),
                overage_units=overage_delta,
                plan_id=request.grant.plan_id,
                plan_version=request.grant.plan_version,
            )

    def consume_success(self, job_id: UUID, lease_token: UUID, worker_id: str) -> UsageConsumption:
        """Convert exactly one HELD reservation to consumption after a valid worker completion."""
        _validate_id(str(job_id), "Job ID")
        _validate_id(str(lease_token), "Lease token")
        _validate_id(worker_id, "Worker ID")
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT j.id AS job_id,j.status,j.lease_token,
                       r.*,b.included_units,b.consumed_units,b.held_units,b.overage_held_units,b.overage_consumed_units
                FROM rf_distribution_jobs j
                JOIN rf_quota_reservations r ON r.distribution_job_id=j.id
                JOIN rf_quota_buckets b ON (
                    b.tenant_id=r.tenant_id AND b.meter=r.meter AND b.billing_period=r.billing_period
                    AND b.quota_scope_id=r.quota_scope_id
                )
                WHERE j.id=%s
                FOR UPDATE OF j,r,b
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                raise ReportFlowError("Distribution job or quota reservation was not found.")
            if row["state"] == "consumed":
                event = connection.execute(
                    "SELECT id,quantity,overage_units FROM rf_usage_events WHERE reservation_id=%s",
                    (row["id"],),
                ).fetchone()
                if event is None:
                    raise ReportFlowError("Consumed reservation is missing its immutable usage event.")
                return UsageConsumption(UUID(str(row["id"])), UUID(str(event["id"])), int(event["quantity"]), int(event["overage_units"]))
            if row["status"] != "running" or str(row["lease_token"]) != str(lease_token):
                raise ReportFlowError("Worker lease is invalid; usage cannot be consumed.")
            if row["state"] != "held":
                raise ReportFlowError("Only a held reservation may be consumed.")

            connection.execute(
                """
                UPDATE rf_quota_buckets
                SET held_units=held_units-%s,
                    consumed_units=consumed_units+%s,
                    overage_held_units=overage_held_units-%s,
                    overage_consumed_units=overage_consumed_units+%s,
                    row_version=row_version+1,
                    updated_at=now()
                WHERE tenant_id=%s AND meter=%s AND billing_period=%s AND quota_scope_id=%s
                """,
                (
                    row["quantity"], row["quantity"], row["overage_units"], row["overage_units"],
                    row["tenant_id"], row["meter"], row["billing_period"], row["quota_scope_id"],
                ),
            )
            connection.execute(
                """
                UPDATE rf_quota_reservations
                SET state='consumed', reason='success', worker_id=%s, finalized_at=now()
                WHERE id=%s AND state='held'
                """,
                (worker_id, row["id"]),
            )
            connection.execute(
                """
                UPDATE rf_distribution_jobs
                SET status='succeeded', lease_token=NULL, lease_expires_at=NULL, updated_at=now()
                WHERE id=%s AND status='running' AND lease_token=%s
                """,
                (job_id, lease_token),
            )
            usage = connection.execute(
                """
                INSERT INTO rf_usage_events (
                    reservation_id,tenant_id,meter,billing_period,quota_scope_id,quantity,overage_units,
                    plan_id,plan_version,entitlement_effective_from,metadata
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (reservation_id) DO UPDATE SET reservation_id=EXCLUDED.reservation_id
                RETURNING id,quantity,overage_units
                """,
                (
                    row["id"], row["tenant_id"], row["meter"], row["billing_period"], row["quota_scope_id"],
                    row["quantity"], row["overage_units"], row["plan_id"], row["plan_version"],
                    row["entitlement_effective_from"], Jsonb({"distribution_job_id": str(job_id)}),
                ),
            ).fetchone()
            self._append_outbox(
                connection,
                aggregate_type="quota_reservation",
                aggregate_id=UUID(str(row["id"])),
                event_type="quota.consumed",
                dedupe_key=f"quota.consumed:{row['id']}",
                payload={"reservation_id": str(row["id"]), "job_id": str(job_id), "worker_id": worker_id},
            )
            return UsageConsumption(UUID(str(row["id"])), UUID(str(usage["id"])), int(usage["quantity"]), int(usage["overage_units"]))

    def release_terminal(self, job_id: UUID, reason: TerminalReason, actor_subject: str) -> bool:
        """Release one held reservation when a queued/retry job is cancelled or reaches DLQ."""
        _validate_id(str(job_id), "Job ID")
        _validate_id(actor_subject, "Actor subject")
        if reason not in {"cancelled", "dead_letter"}:
            raise ReportFlowError("Reservation release reason is invalid.")
        with self._connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT j.status,r.*,b.held_units,b.overage_held_units
                FROM rf_distribution_jobs j
                JOIN rf_quota_reservations r ON r.distribution_job_id=j.id
                JOIN rf_quota_buckets b ON (
                    b.tenant_id=r.tenant_id AND b.meter=r.meter AND b.billing_period=r.billing_period
                    AND b.quota_scope_id=r.quota_scope_id
                )
                WHERE j.id=%s
                FOR UPDATE OF j,r,b
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                raise ReportFlowError("Distribution job or quota reservation was not found.")
            if row["state"] in {"released", "expired"}:
                return False
            if row["state"] == "consumed":
                raise ReportFlowError("A consumed reservation cannot be released.")
            expected_status = "cancelled" if reason == "cancelled" else "dead_letter"
            connection.execute(
                """
                UPDATE rf_distribution_jobs
                SET status=%s, lease_token=NULL, lease_expires_at=NULL, updated_at=now()
                WHERE id=%s AND status IN ('queued','retry','running')
                """,
                (expected_status, job_id),
            )
            connection.execute(
                """
                UPDATE rf_quota_buckets
                SET held_units=held_units-%s,
                    overage_held_units=overage_held_units-%s,
                    row_version=row_version+1,
                    updated_at=now()
                WHERE tenant_id=%s AND meter=%s AND billing_period=%s AND quota_scope_id=%s
                """,
                (row["quantity"], row["overage_units"], row["tenant_id"], row["meter"], row["billing_period"], row["quota_scope_id"]),
            )
            connection.execute(
                """
                UPDATE rf_quota_reservations
                SET state='released', reason=%s, worker_id=NULL, finalized_at=now()
                WHERE id=%s AND state='held'
                """,
                (reason, row["id"]),
            )
            self._append_outbox(
                connection,
                aggregate_type="quota_reservation",
                aggregate_id=UUID(str(row["id"])),
                event_type="quota.released",
                dedupe_key=f"quota.released:{row['id']}",
                payload={"reservation_id": str(row["id"]), "job_id": str(job_id), "reason": reason, "actor": actor_subject},
            )
            return True

    def claim_outbox(self, publisher_id: str, *, batch_size: int = 25, lease_seconds: int = 60) -> list[OutboxLease]:
        """Lease ready events without blocking competing publishers.

        `FOR UPDATE SKIP LOCKED` means two publisher processes claim disjoint rows instead
        of waiting behind the same oldest event. Leases expire to recover from publisher
        crashes; broker consumers must still deduplicate because publication is at-least-once.
        """
        _validate_id(publisher_id, "Publisher ID")
        if not 1 <= batch_size <= 500 or not 10 <= lease_seconds <= 3_600:
            raise ReportFlowError("Outbox batch or lease setting is invalid.")
        with self._connection() as connection, connection.transaction():
            rows = connection.execute(
                """
                WITH candidates AS (
                    SELECT id FROM rf_outbox_events
                    WHERE published_at IS NULL
                      AND dead_lettered_at IS NULL
                      AND available_at <= now()
                      AND (lease_expires_at IS NULL OR lease_expires_at < now())
                    ORDER BY available_at ASC, occurred_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE rf_outbox_events e
                SET lease_token=gen_random_uuid(),
                    lease_owner=%s,
                    lease_expires_at=now() + (%s * interval '1 second'),
                    publish_attempts=publish_attempts+1
                FROM candidates
                WHERE e.id=candidates.id
                RETURNING e.id,e.event_type,e.aggregate_id,e.payload,e.lease_token,e.lease_owner,e.publish_attempts
                """,
                (batch_size, publisher_id, lease_seconds),
            ).fetchall()
            return [
                OutboxLease(
                    UUID(str(row["id"])), str(row["event_type"]), UUID(str(row["aggregate_id"])),
                    dict(row["payload"]), UUID(str(row["lease_token"])), str(row["lease_owner"]), int(row["publish_attempts"]),
                )
                for row in rows
            ]

    def mark_outbox_published(self, event_id: UUID, lease_token: UUID, publisher_id: str) -> None:
        """Acknowledge publication only if this publisher still owns the active lease."""
        _validate_id(str(event_id), "Outbox event ID")
        _validate_id(str(lease_token), "Outbox lease token")
        _validate_id(publisher_id, "Publisher ID")
        with self._connection() as connection, connection.transaction():
            updated = connection.execute(
                """
                UPDATE rf_outbox_events
                SET published_at=now(), lease_token=NULL, lease_owner=NULL, lease_expires_at=NULL, last_error=''
                WHERE id=%s AND published_at IS NULL AND lease_token=%s AND lease_owner=%s
                  AND lease_expires_at >= now()
                """,
                (event_id, lease_token, publisher_id),
            ).rowcount
            if updated != 1:
                raise ReportFlowError("Outbox acknowledgement was rejected because its lease is invalid.")

    def defer_outbox(self, event_id: UUID, lease_token: UUID, publisher_id: str, error: Exception | str, *, retry_seconds: int) -> None:
        """Release a failed event for a bounded delayed retry without losing its history."""
        _validate_id(str(event_id), "Outbox event ID")
        _validate_id(str(lease_token), "Outbox lease token")
        _validate_id(publisher_id, "Publisher ID")
        if not 1 <= retry_seconds <= 3_600:
            raise ReportFlowError("Outbox retry delay is invalid.")
        safe_error = _safe_outbox_error(error)
        with self._connection() as connection, connection.transaction():
            updated = connection.execute(
                """
                UPDATE rf_outbox_events
                SET available_at=now() + (%s * interval '1 second'),
                    lease_token=NULL,
                    lease_owner=NULL,
                    lease_expires_at=NULL,
                    last_error=%s
                WHERE id=%s AND published_at IS NULL AND lease_token=%s AND lease_owner=%s
                  AND lease_expires_at >= now()
                """,
                (retry_seconds, safe_error, event_id, lease_token, publisher_id),
            ).rowcount
            if updated != 1:
                raise ReportFlowError("Outbox retry update was rejected because its lease is invalid.")

    def dead_letter_outbox(self, event_id: UUID, lease_token: UUID, publisher_id: str, error: Exception | str) -> None:
        """Move an exhausted event to terminal DLQ while preserving its payload and attempt history."""
        _validate_id(str(event_id), "Outbox event ID")
        _validate_id(str(lease_token), "Outbox lease token")
        _validate_id(publisher_id, "Publisher ID")
        safe_error = _safe_outbox_error(error)
        with self._connection() as connection, connection.transaction():
            updated = connection.execute(
                """
                UPDATE rf_outbox_events
                SET dead_lettered_at=now(),
                    dead_letter_reason=%s,
                    dead_lettered_by=%s,
                    lease_token=NULL,
                    lease_owner=NULL,
                    lease_expires_at=NULL,
                    last_error=%s
                WHERE id=%s
                  AND published_at IS NULL
                  AND dead_lettered_at IS NULL
                  AND lease_token=%s
                  AND lease_owner=%s
                  AND lease_expires_at >= now()
                """,
                (safe_error, publisher_id, safe_error, event_id, lease_token, publisher_id),
            ).rowcount
            if updated != 1:
                raise ReportFlowError("Outbox DLQ transition was rejected because its lease is invalid.")


    def _lock_or_create_bucket(self, connection: Connection[Any], grant: QuotaGrant) -> Mapping[str, Any]:
        connection.execute(
            """
            INSERT INTO rf_quota_buckets (
                tenant_id,meter,billing_period,quota_scope_id,plan_id,plan_version,entitlement_effective_from,
                overage_behavior,included_units
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id,meter,billing_period,quota_scope_id) DO NOTHING
            """,
            (
                grant.tenant_id, grant.meter, grant.billing_period, grant.quota_scope_id, grant.plan_id,
                grant.plan_version, grant.entitlement_effective_from, grant.overage_behavior, grant.included_units,
            ),
        )
        row = connection.execute(
            """
            SELECT * FROM rf_quota_buckets
            WHERE tenant_id=%s AND meter=%s AND billing_period=%s AND quota_scope_id=%s
            FOR UPDATE
            """,
            (grant.tenant_id, grant.meter, grant.billing_period, grant.quota_scope_id),
        ).fetchone()
        if row is None:
            raise ReportFlowError("Quota bucket could not be created or locked.")
        # Existing bucket must retain the original commercial snapshot for auditability.
        snapshot = (str(row["plan_id"]), int(row["plan_version"]), row["entitlement_effective_from"], str(row["overage_behavior"]), int(row["included_units"]))
        expected = (grant.plan_id, grant.plan_version, grant.entitlement_effective_from, grant.overage_behavior, grant.included_units)
        if snapshot != expected:
            raise ReportFlowError("Quota scope re-use conflicts with an immutable commercial snapshot.")
        return row

    def _existing_admission(self, connection: Connection[Any], idempotency_key: str) -> Mapping[str, Any] | None:
        return connection.execute(
            """
            SELECT r.id AS reservation_id,r.tenant_id,r.meter,r.billing_period,r.quota_scope_id,r.quantity,
                   r.overage_units,r.expires_at,r.plan_id,r.plan_version,j.id AS job_id
            FROM rf_quota_reservations r
            JOIN rf_distribution_jobs j ON j.id=r.distribution_job_id
            WHERE r.idempotency_key=%s
            """,
            (idempotency_key,),
        ).fetchone()

    @staticmethod
    def _admission_from_row(row: Mapping[str, Any], *, created: bool) -> AdmissionResult:
        return AdmissionResult(
            job_id=UUID(str(row["job_id"])), reservation_id=UUID(str(row["reservation_id"])), created=created,
            expires_at=row["expires_at"], held_units=-1, available_units=-1, overage_units=int(row["overage_units"]),
            plan_id=str(row["plan_id"]), plan_version=int(row["plan_version"]),
        )

    @staticmethod
    def _assert_same_request(existing: Mapping[str, Any], request: AdmissionRequest) -> None:
        expected = (request.grant.tenant_id, request.grant.meter, request.grant.billing_period, request.grant.quota_scope_id, request.quantity)
        received = (str(existing["tenant_id"]), str(existing["meter"]), existing["billing_period"], str(existing["quota_scope_id"]), int(existing["quantity"]))
        if expected != received:
            raise ReportFlowError("Admission idempotency key was already used with different commercial data.")

    @staticmethod
    def _append_outbox(
        connection: Connection[Any], *, aggregate_type: str, aggregate_id: UUID, event_type: str, dedupe_key: str, payload: Mapping[str, Any]
    ) -> None:
        connection.execute(
            """
            INSERT INTO rf_outbox_events (aggregate_type,aggregate_id,event_type,payload,dedupe_key)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (dedupe_key) DO NOTHING
            """,
            (aggregate_type, aggregate_id, event_type, Jsonb(dict(payload)), dedupe_key),
        )

    def _connection(self) -> Connection[Any]:
        return connect(self.conninfo, row_factory=dict_row)

    @staticmethod
    def _validate_admission(request: AdmissionRequest) -> None:
        grant = request.grant
        for value, label in ((grant.tenant_id, "Tenant ID"), (grant.quota_scope_id, "Quota scope ID"), (grant.plan_id, "Plan ID"), (request.idempotency_key, "Idempotency key"), (request.actor_subject, "Actor subject")):
            _validate_id(value, label)
        if not _SAFE_METER.fullmatch(grant.meter):
            raise ReportFlowError("Meter is invalid.")
        if not isinstance(grant.billing_period, date) or grant.billing_period.day != 1:
            raise ReportFlowError("Billing period must be the first day of a month.")
        if grant.overage_behavior not in {"deny", "allow"} or not 0 <= grant.included_units <= 100_000_000:
            raise ReportFlowError("Quota grant policy is invalid.")
        if not 1 <= grant.plan_version <= 10_000 or grant.entitlement_effective_from.tzinfo is None:
            raise ReportFlowError("Quota grant snapshot is invalid.")
        if not request.kind or not isinstance(request.payload, Mapping):
            raise ReportFlowError("Distribution request is invalid.")
        if not 1 <= request.quantity <= 1_000_000 or not 30 <= request.reservation_ttl_seconds <= 3_600:
            raise ReportFlowError("Reservation quantity or TTL is invalid.")
        if not -100 <= request.priority <= 100:
            raise ReportFlowError("Distribution priority is invalid.")
        try:
            encoded = json.dumps(dict(request.payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ReportFlowError("Distribution payload must be JSON serializable.") from error
        if len(encoded) > 128_000:
            raise ReportFlowError("Distribution payload exceeds the sample control-plane limit.")



class TransactionalOutboxWorker:
    """A one-pass, deterministic worker suitable for a durable supervisor or scheduled runtime.

    The worker never sleeps, polls, or owns a long-lived database connection. A deployment
    supervisor controls cadence. This keeps work bounded and lets multiple replicas run
    concurrently; PostgreSQL leases and SKIP LOCKED coordinate their claims.
    """

    def __init__(
        self,
        service: PostgresQuotaReservationService,
        sink: OutboxSink,
        *,
        publisher_id: str,
        batch_size: int = 25,
        lease_seconds: int = 60,
        retry_policy: ExponentialBackoffPolicy | None = None,
        retry_seconds: int | None = None,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        _validate_id(publisher_id, "Publisher ID")
        if not 1 <= batch_size <= 500 or not 10 <= lease_seconds <= 3_600:
            raise ReportFlowError("Outbox worker settings are invalid.")
        if retry_policy is not None and retry_seconds is not None:
            raise ReportFlowError("Choose either a retry policy or legacy fixed retry seconds.")
        if retry_seconds is not None and not 1 <= retry_seconds <= 3_600:
            raise ReportFlowError("Outbox legacy retry delay is invalid.")
        self.service = service
        self.sink = sink
        self.publisher_id = publisher_id
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.retry_policy = retry_policy or ExponentialBackoffPolicy()
        self.legacy_retry_seconds = retry_seconds
        self.random_value = random_value

    def run_once(self) -> OutboxRunResult:
        """Publish one lease-safe batch with full-jitter retries and terminal DLQ state."""
        leases = self.service.claim_outbox(
            self.publisher_id, batch_size=self.batch_size, lease_seconds=self.lease_seconds
        )
        published = deferred = dead_lettered = 0
        for event in leases:
            try:
                self.sink.publish(event.event_type, event.payload, idempotency_key=str(event.event_id))
                self.service.mark_outbox_published(event.event_id, event.lease_token, self.publisher_id)
                published += 1
            except Exception as error:  # A sink failure must preserve the durable outbox event.
                try:
                    if event.publish_attempts >= self.retry_policy.max_attempts:
                        self.service.dead_letter_outbox(event.event_id, event.lease_token, self.publisher_id, error)
                        dead_lettered += 1
                    else:
                        delay = self.legacy_retry_seconds or self.retry_policy.retry_delay_seconds(
                            event.publish_attempts, random_value=self.random_value()
                        )
                        self.service.defer_outbox(
                            event.event_id, event.lease_token, self.publisher_id, error, retry_seconds=delay
                        )
                        deferred += 1
                except ReportFlowError:
                    # The lease can expire after broker publication and before acknowledgement.
                    # Do not stop the batch: the event remains durable and its consumer must deduplicate.
                    pass
        return OutboxRunResult(
            claimed=len(leases), published=published, deferred=deferred, dead_lettered=dead_lettered
        )


def _safe_outbox_error(error: Exception | str) -> str:
    text = str(error).replace("\n", " ").replace("\r", " ").strip()
    return text[:500] or "outbox_publish_failed"


def _validate_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ReportFlowError(f"{label} is invalid.")

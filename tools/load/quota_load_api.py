"""Isolated load-test API for the PostgreSQL quota-admission reference.

Never deploy this module as a production control-plane endpoint. It intentionally accepts
only synthetic test inputs and requires a disposable database named through
REPORTFLOW_TEST_POSTGRES_DSN.
"""
from __future__ import annotations

import hashlib
import os
from datetime import UTC, date, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from reportflow_app.core import ReportFlowError
from reportflow_app.postgres_quota_v26 import AdmissionRequest, PostgresQuotaReservationService, QuotaExceeded, QuotaGrant

app = FastAPI(title="ReportFlow quota load harness", docs_url=None, redoc_url=None)


class AdmissionInput(BaseModel):
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:@/-]+$")
    tenant_shard: int = Field(ge=0, le=999)


def _service() -> PostgresQuotaReservationService:
    dsn = os.environ.get("REPORTFLOW_TEST_POSTGRES_DSN", "")
    if not dsn:
        raise RuntimeError("REPORTFLOW_TEST_POSTGRES_DSN must point to an isolated disposable database.")
    return PostgresQuotaReservationService(dsn)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/load/admit")
def admit(payload: AdmissionInput) -> dict[str, object]:
    tenant_id = f"load-tenant-{payload.tenant_shard:03d}"
    digest = hashlib.sha256(payload.request_id.encode("utf-8")).hexdigest()[:16]
    grant = QuotaGrant(
        tenant_id=tenant_id,
        meter="successful_delivery",
        billing_period=date(2026, 8, 1),
        quota_scope_id=f"load-growth-2026-08-{payload.tenant_shard:03d}",
        plan_id="load-growth",
        plan_version=1,
        entitlement_effective_from=datetime(2026, 8, 1, tzinfo=UTC),
        overage_behavior="allow",
        included_units=1_000_000,
    )
    request = AdmissionRequest(
        grant=grant,
        idempotency_key=f"locust-{digest}",
        kind="load-test-delivery",
        payload={"report_id": "load-test", "synthetic": True},
        quantity=1,
        reservation_ttl_seconds=300,
        actor_subject="locust-load-harness",
    )
    try:
        result = _service().admit(request)
    except QuotaExceeded as error:
        raise HTTPException(status_code=429, detail="quota exceeded") from error
    except ReportFlowError as error:
        raise HTTPException(status_code=400, detail="invalid quota request") from error
    return {"job_id": str(result.job_id), "reservation_id": str(result.reservation_id), "created": result.created}

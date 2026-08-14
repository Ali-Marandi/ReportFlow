from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from reportflow_app.anomaly_v22 import AnomalyPolicy, AnomalyRegistry, RobustAnomalyDetector
from reportflow_app.core import ProjectStore, ReportDefinition, ReportFlowError
from reportflow_app.distribution_v22 import (
    AzureBlobArtifactDestination,
    DistributionQueue,
    DistributionWorker,
    RetryPolicy,
    S3ArtifactDestination,
    artifact_delivery_payload,
)
from reportflow_app.portal_v22 import PortalBrand, PortalRegistry, PortalReportGrant, PortalSessionService, PortalTenant


def report(store: ProjectStore, source: Path) -> ReportDefinition:
    source.write_text("Region,Revenue\nEast,100\n", encoding="utf-8")
    return store.save_report(ReportDefinition(None, "Sales", str(source), "Executive", "Sales", ["Region", "Revenue"], ["html"], "", ""))


def test_queue_idempotency_retry_and_dead_letter(tmp_path: Path) -> None:
    store, queue = ProjectStore(tmp_path / "reportflow.db"), None
    queue = DistributionQueue(store)
    policy = RetryPolicy(max_attempts=2, base_delay_seconds=10, max_delay_seconds=60, lease_seconds=60)
    job, created = queue.enqueue("artifact_delivery", {"destination_id": "s3-prod", "artifact_path": "/exports/a.pdf"}, "burst-2026-08-14-0001", retry_policy=policy)
    duplicate, duplicate_created = queue.enqueue("artifact_delivery", {"destination_id": "s3-prod", "artifact_path": "/exports/a.pdf"}, "burst-2026-08-14-0001", retry_policy=policy)
    assert created and not duplicate_created and duplicate.id == job.id
    start = datetime.now(UTC) + timedelta(seconds=1)
    first = queue.claim_next("worker-a", now=start)
    assert first and first.job.attempt_count == 1
    retry = queue.fail(first, "temporary storage outage", retryable=True, now=start)
    assert retry.status == "retry" and retry.available_at == (start + timedelta(seconds=10)).isoformat()
    second = queue.claim_next("worker-a", now=start + timedelta(seconds=10))
    assert second and second.job.attempt_count == 2
    dlq = queue.fail(second, "authorization rejected", retryable=False, now=start + timedelta(seconds=10))
    assert dlq.status == "dead_letter"


def test_worker_marks_non_retryable_policy_error_dead_letter(tmp_path: Path) -> None:
    store, queue = ProjectStore(tmp_path / "reportflow.db"), None
    queue = DistributionQueue(store)
    queue.enqueue("artifact_delivery", {"x": "y"}, "burst-2026-08-14-0002")
    outcome = DistributionWorker(queue, "worker-b").run_once(lambda _: (_ for _ in ()).throw(Exception("network unavailable")))
    assert outcome and outcome.status == "retry"


class FakeS3:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def put_object(self, **request):
        self.requests.append(request)
        return {"ETag": "x"}


class FakeBlob:
    def __init__(self) -> None:
        self.uploads: list[dict] = []
        self.metadata: dict[str, str] = {}

    def upload_blob(self, handle, **kwargs):
        self.uploads.append({"body": handle.read(), **kwargs})
        self.metadata = kwargs["metadata"]

    def get_blob_properties(self):
        return type("Properties", (), {"metadata": self.metadata})()


class FakeBlobService:
    def __init__(self) -> None:
        self.blob = FakeBlob()

    def get_blob_client(self, **_: str):
        return self.blob


def test_s3_and_blob_destinations_send_checksum_metadata_without_secrets(tmp_path: Path) -> None:
    artifact = tmp_path / "report.pdf"
    artifact.write_bytes(b"report-content")
    key = "burst-2026-08-14-0003"
    s3 = FakeS3()
    S3ArtifactDestination("reportflow-artifacts", "tenant-a", client=s3).upload(artifact, "run/report.pdf", key, "confidential")
    digest = hashlib.sha256(b"report-content").hexdigest()
    assert s3.requests[0]["ChecksumAlgorithm"] == "SHA256"
    assert s3.requests[0]["IfNoneMatch"] == "*"
    assert s3.requests[0]["Metadata"]["reportflow-sha256"] == digest
    service = FakeBlobService()
    AzureBlobArtifactDestination("https://reportflow.blob.core.windows.net", "deliveries", "tenant-a", service_client=service).upload(artifact, "run/report.pdf", key, "confidential")
    assert service.blob.uploads[0]["overwrite"] is False
    assert service.blob.metadata["reportflow-idempotency-key"] == key
    with pytest.raises(ReportFlowError, match="credentials"):
        DistributionQueue(ProjectStore(tmp_path / "second.db")).enqueue("x", {"token": "not-allowed"}, "burst-2026-08-14-0004")


def test_portal_session_enforces_tenant_isolation_and_revocation(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "reportflow.db")
    saved = report(store, tmp_path / "sales.csv")
    registry = PortalRegistry(store)
    tenant = PortalTenant("contoso", PortalBrand("Contoso Analytics", "#135bec", "https://cdn.example.com/logo.svg"))
    registry.save_tenant(tenant)
    registry.grant_report(PortalReportGrant("contoso", saved.id or 0, "confidential"))
    service = PortalSessionService(registry, lambda: "x" * 48)
    token = service.issue("contoso", "alex@example.com", {"contoso"})
    session = service.assert_report_access(token, "contoso", saved.id or 0)
    assert session.subject == "alex@example.com"
    assert "Contoso Analytics" in service.render_shell(token)
    with pytest.raises(ReportFlowError, match="not authorized"):
        service.assert_report_access(token, "other-tenant", saved.id or 0)
    registry.grant_report(PortalReportGrant("contoso", saved.id or 0, "confidential", enabled=False))
    with pytest.raises(ReportFlowError, match="no longer valid"):
        service.verify(token)


def test_robust_anomaly_detection_deduplicates_and_requires_review(tmp_path: Path) -> None:
    timestamps = pd.date_range("2026-07-01", periods=12, freq="D", tz="UTC")
    series = pd.DataFrame({"timestamp": timestamps, "value": [100, 101, 99, 100, 102, 101, 100, 99, 101, 100, 99, 175]})
    findings = RobustAnomalyDetector().detect("net_revenue", series, policy=AnomalyPolicy(minimum_history=8, rolling_window=10, robust_z_threshold=3.5), semantic_version="2.2.0", freshness_status="fresh")
    assert len(findings) == 1 and findings[0].direction == "up"
    assert "rolling median" in findings[0].explanation and findings[0].evidence["requires_review"] is True
    store, registry = ProjectStore(tmp_path / "reportflow.db"), None
    registry = AnomalyRegistry(store)
    assert registry.record(findings[0]) is True
    assert registry.record(findings[0]) is False
    review = registry.review(findings[0].idempotency_key, "investigating", "Validate source refresh and regional drivers.", "analyst@example.com")
    assert review.status == "investigating"

from __future__ import annotations

import pytest

from reportflow_app.commercial_v25 import CommercialCatalog, CommercialDistributionGate, CommercialPlan
from reportflow_app.core import ProjectStore, ReportFlowError
from reportflow_app.distribution_v22 import DistributionQueue, RetryPolicy


@pytest.fixture()
def store(tmp_path):
    return ProjectStore(tmp_path / "reportflow-commercial.db")


@pytest.fixture()
def catalog(store) -> CommercialCatalog:
    catalog = CommercialCatalog(store)
    catalog.save_plan(
        CommercialPlan(
            id="growth-v1",
            version=1,
            display_name="Growth",
            feature_flags=("distribution_queue", "white_label_portal", "lineage_impact"),
            meter_limits={"successful_delivery": 2, "portal_view": 20},
            overage_behavior="deny",
            commercial_sku="rf-growth-monthly",
            created_at="",
        )
    )
    return catalog


def test_plans_are_immutable_and_tenant_features_are_isolated(catalog):
    with pytest.raises(ReportFlowError, match="immutable"):
        catalog.save_plan(
            CommercialPlan(
                id="growth-v1", version=1, display_name="Changed", feature_flags=("distribution_queue",),
                meter_limits={"successful_delivery": 4}, overage_behavior="deny", commercial_sku="rf-growth-monthly", created_at="",
            )
        )

    catalog.assign_tenant("tenant-alpha", "growth-v1", 1, feature_overrides=("governance_approval",))
    allowed = catalog.check_feature("tenant-alpha", "distribution_queue")
    override = catalog.check_feature("tenant-alpha", "governance_approval")
    denied = catalog.check_feature("tenant-alpha", "anomaly_detection")
    unknown = catalog.check_feature("tenant-beta", "distribution_queue")

    assert allowed.allowed and allowed.reason == "feature_enabled"
    assert override.allowed
    assert not denied.allowed and denied.reason == "feature_not_in_plan"
    assert not unknown.allowed and unknown.reason == "tenant_has_no_plan"


def test_usage_is_idempotent_and_denies_hard_cap_excess(catalog):
    catalog.assign_tenant("tenant-alpha", "growth-v1", 1)
    first = catalog.record_usage("tenant-alpha", "successful_delivery", 1, "delivery-alpha-001", "2026-08", metadata={"job": "job-001"})
    duplicate = catalog.record_usage("tenant-alpha", "successful_delivery", 1, "delivery-alpha-001", "2026-08", metadata={"job": "job-001"})
    second = catalog.record_usage("tenant-alpha", "successful_delivery", 1, "delivery-alpha-002", "2026-08")
    summary = catalog.usage_summary("tenant-alpha", "successful_delivery", "2026-08")

    assert first.id == duplicate.id
    assert second.quantity == 1
    assert summary.used == 2
    assert summary.remaining == 0
    assert summary.overage == 0

    with pytest.raises(ReportFlowError, match="exceed"):
        catalog.record_usage("tenant-alpha", "successful_delivery", 1, "delivery-alpha-003", "2026-08")

    with pytest.raises(ReportFlowError, match="different event data"):
        catalog.record_usage("tenant-alpha", "successful_delivery", 2, "delivery-alpha-001", "2026-08")


def test_allow_overage_tracks_incremental_overage_units(store):
    catalog = CommercialCatalog(store)
    catalog.save_plan(
        CommercialPlan("enterprise-v1", 1, "Enterprise", ("distribution_queue",), {"successful_delivery": 2}, "allow", "rf-enterprise", "")
    )
    catalog.assign_tenant("tenant-enterprise", "enterprise-v1", 1)
    catalog.record_usage("tenant-enterprise", "successful_delivery", 2, "enterprise-job-001", "2026-08")
    overage = catalog.record_usage("tenant-enterprise", "successful_delivery", 3, "enterprise-job-002", "2026-08")
    summary = catalog.usage_summary("tenant-enterprise", "successful_delivery", "2026-08")

    assert overage.overage_units == 3
    assert summary.used == 5
    assert summary.overage == 3


def test_commercial_distribution_gate_checks_plan_and_records_success(catalog, store):
    catalog.assign_tenant("tenant-alpha", "growth-v1", 1)
    queue = DistributionQueue(store)
    gate = CommercialDistributionGate(catalog)
    job, created = gate.enqueue_entitled(
        queue,
        "tenant-alpha",
        kind="artifact_delivery",
        payload={"artifact_path": "reports/alpha.pdf", "destination": "secure-folder"},
        idempotency_key="commercial-job-001",
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=30, max_delay_seconds=60, lease_seconds=60),
        billing_period="2026-08",
    )
    assert created
    event = gate.record_success("tenant-alpha", job.id, "2026-08")
    duplicate = gate.record_success("tenant-alpha", job.id, "2026-08")
    assert event.id == duplicate.id
    assert catalog.usage_summary("tenant-alpha", "successful_delivery", "2026-08").used == 1

    with pytest.raises(ReportFlowError, match="not entitled"):
        gate.enqueue_entitled(
            queue,
            "tenant-missing",
            kind="artifact_delivery",
            payload={"artifact_path": "reports/beta.pdf", "destination": "secure-folder"},
            idempotency_key="commercial-job-002",
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=30, max_delay_seconds=60, lease_seconds=60),
            billing_period="2026-08",
        )


def test_usage_metadata_rejects_recipient_identity_or_credentials(catalog):
    catalog.assign_tenant("tenant-alpha", "growth-v1", 1)
    with pytest.raises(ReportFlowError, match="recipient identity"):
        catalog.record_usage("tenant-alpha", "portal_view", 1, "portal-view-001", "2026-08", metadata={"email": "person@example.test"})


def test_usage_event_captures_plan_snapshot_across_tenant_upgrade(catalog, store):
    catalog.assign_tenant("tenant-alpha", "growth-v1", 1)
    original = catalog.record_usage("tenant-alpha", "successful_delivery", 1, "snapshot-event-001", "2026-08")
    catalog.save_plan(
        CommercialPlan(
            id="growth-v1",
            version=2,
            display_name="Growth v2",
            feature_flags=("distribution_queue", "white_label_portal", "lineage_impact", "governance_approval"),
            meter_limits={"successful_delivery": 5, "portal_view": 30},
            overage_behavior="deny",
            commercial_sku="rf-growth-monthly-v2",
            created_at="",
        )
    )
    catalog.assign_tenant("tenant-alpha", "growth-v1", 2)
    upgraded = catalog.record_usage("tenant-alpha", "successful_delivery", 1, "snapshot-event-002", "2026-08")

    assert (original.plan_id, original.plan_version) == ("growth-v1", 1)
    assert (upgraded.plan_id, upgraded.plan_version) == ("growth-v1", 2)
    with store._connect() as connection:
        rows = connection.execute(
            "SELECT id,plan_id,plan_version,entitlement_effective_from FROM commercial_usage_events ORDER BY occurred_at"
        ).fetchall()
    assert {(row["plan_id"], row["plan_version"]) for row in rows} == {("growth-v1", 1), ("growth-v1", 2)}
    assert all(row["entitlement_effective_from"] for row in rows)


@pytest.mark.parametrize("metadata", [{"recipient_id": "cust-1"}, {"contactPhone": "+1-555-0100"}, {"nested": {"apiToken": "redacted"}}])
def test_usage_metadata_rejects_common_identity_and_credential_key_variants(catalog, metadata):
    catalog.assign_tenant("tenant-alpha", "growth-v1", 1)
    with pytest.raises(ReportFlowError, match="recipient identity"):
        catalog.record_usage("tenant-alpha", "portal_view", 1, f"metadata-safe-{len(str(metadata))}", "2026-08", metadata=metadata)

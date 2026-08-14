from __future__ import annotations

import pytest

from reportflow_app.core import ProjectStore, ReportFlowError
from reportflow_app.distribution_v22 import DistributionQueue, RetryPolicy
from reportflow_app.governance_v23 import ApprovalPolicy, ApprovalService, GovernedDistributionGate, IntegrityLedger


@pytest.fixture()
def store(tmp_path):
    return ProjectStore(tmp_path / "reportflow-governance.db")


@pytest.fixture()
def policy() -> ApprovalPolicy:
    return ApprovalPolicy(
        policy_id="restricted-external",
        minimum_approvals=2,
        required_roles=("data_owner", "security_officer"),
        governed_classifications=("confidential", "restricted"),
    )


@pytest.fixture()
def approved_content() -> dict[str, str]:
    return {
        "destination_id": "finance-archive",
        "artifact_sha256": "a" * 64,
        "object_key": "finance/2026/q3-report.pdf",
        "classification": "restricted",
    }


def test_two_person_approval_requires_distinct_roles_and_binds_content(store, policy, approved_content):
    ledger = IntegrityLedger(store, b"reportflow-governance-key-32-bytes")
    approvals = ApprovalService(store, ledger)
    request = approvals.submit("distribution_job", "job-2026-q3", "reporter-1", "restricted", approved_content, policy)

    with pytest.raises(ReportFlowError, match="Requester cannot"):
        approvals.decide(request.id, "reporter-1", "approved", roles=("data_owner",))

    still_pending, _ = approvals.decide(request.id, "owner-1", "approved", roles=("data_owner",), comment="Financial owner approved.")
    assert still_pending.status == "pending"

    approved, decision = approvals.decide(request.id, "security-1", "approved", roles=("security_officer",))
    assert decision.approver == "security-1"
    assert approved.status == "approved"
    assert len(approvals.decisions_for(request.id)) == 2

    authorization = approvals.authorize_delivery(request.id, approved_content, actor="worker-west-1")
    assert authorization.content_fingerprint == request.content_fingerprint
    assert ledger.verify().valid

    changed_destination = {**approved_content, "destination_id": "unapproved-external"}
    with pytest.raises(ReportFlowError, match="changed after approval"):
        approvals.authorize_delivery(request.id, changed_destination, actor="worker-west-1")
    assert ledger.verify().valid


def test_role_coverage_and_one_decision_per_approver_are_enforced(store, policy, approved_content):
    approvals = ApprovalService(store)
    request = approvals.submit("distribution_job", "job-coverage", "reporter-2", "restricted", approved_content, policy)

    state, _ = approvals.decide(request.id, "owner-1", "approved", roles=("data_owner",))
    assert state.status == "pending"
    state, _ = approvals.decide(request.id, "owner-2", "approved", roles=("data_owner",))
    assert state.status == "pending"  # Quorum is met but the security role is absent.

    with pytest.raises(ReportFlowError, match="only one decision"):
        approvals.decide(request.id, "owner-1", "approved", roles=("security_officer",))

    state, _ = approvals.decide(request.id, "security-2", "approved", roles=("security_officer",))
    assert state.status == "approved"


def test_rejection_and_cancellation_are_terminal_controls(store, policy, approved_content):
    approvals = ApprovalService(store)
    request = approvals.submit("distribution_job", "job-rejected", "reporter-3", "restricted", approved_content, policy)
    rejected, _ = approvals.decide(request.id, "security-3", "rejected", roles=("security_officer",), comment="Destination not approved.")
    assert rejected.status == "rejected"
    with pytest.raises(ReportFlowError, match="Only pending"):
        approvals.decide(request.id, "owner-3", "approved", roles=("data_owner",))

    cancellable = approvals.submit("distribution_job", "job-cancelled", "reporter-4", "restricted", approved_content, policy)
    cancelled = approvals.cancel(cancellable.id, "reporter-4")
    assert cancelled.status == "cancelled"
    with pytest.raises(ReportFlowError, match="Only the requester"):
        approvals.cancel(cancellable.id, "another-user")


def test_tamper_evident_ledger_detects_modified_history(store):
    ledger = IntegrityLedger(store, b"reportflow-governance-key-32-bytes")
    first = ledger.append("governance.submitted", "reporter-1", "approval_request", "request-1", {"classification": "restricted"})
    ledger.append("governance.approved", "security-1", "approval_request", "request-1", {"role": "security_officer"})
    verification = ledger.verify()
    assert verification.valid
    assert verification.event_count == 2
    assert verification.head_hash != "0" * 64

    with store._connect() as connection:
        connection.execute("UPDATE governance_ledger_events SET details=? WHERE sequence=?", ('{"classification":"public"}', first.sequence))

    verification = ledger.verify()
    assert not verification.valid
    assert "hash mismatch" in verification.failure.lower()


def test_governed_gate_enqueues_only_approved_unchanged_payload(store, policy, approved_content):
    approvals = ApprovalService(store)
    request = approvals.submit("distribution_job", "job-gated", "reporter-5", "restricted", approved_content, policy)
    approvals.decide(request.id, "owner-5", "approved", roles=("data_owner",))
    approvals.decide(request.id, "security-5", "approved", roles=("security_officer",))

    queue = DistributionQueue(store)
    gate = GovernedDistributionGate(approvals)
    job, created = gate.enqueue_approved(
        queue,
        request.id,
        kind="artifact_delivery",
        payload=approved_content,
        idempotency_key="delivery-2026-q3-gated",
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=30, max_delay_seconds=60, lease_seconds=60),
        priority=10,
        actor="worker-west-2",
    )
    assert created
    assert job.status == "queued"

    with pytest.raises(ReportFlowError, match="changed after approval"):
        gate.enqueue_approved(
            queue,
            request.id,
            kind="artifact_delivery",
            payload={**approved_content, "object_key": "finance/2026/q3-amended.pdf"},
            idempotency_key="delivery-2026-q3-amended",
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=30, max_delay_seconds=60, lease_seconds=60),
            actor="worker-west-2",
        )

    actions = [row["action"] for row in store.list_audit_events()]
    assert "governance.delivery_authorized" in actions
    assert "distribution.enqueued" in actions

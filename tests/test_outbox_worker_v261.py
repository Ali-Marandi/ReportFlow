from __future__ import annotations

from uuid import uuid4

from reportflow_app.core import ReportFlowError
from reportflow_app.postgres_quota_v26 import OutboxLease, TransactionalOutboxWorker


class FakeService:
    def __init__(self, events: list[OutboxLease]) -> None:
        self.events = events
        self.claim_calls = []
        self.published = []
        self.deferred = []

    def claim_outbox(self, publisher_id, *, batch_size, lease_seconds):
        self.claim_calls.append((publisher_id, batch_size, lease_seconds))
        return list(self.events)

    def mark_outbox_published(self, event_id, lease_token, publisher_id):
        self.published.append((event_id, lease_token, publisher_id))

    def defer_outbox(self, event_id, lease_token, publisher_id, error, *, retry_seconds):
        self.deferred.append((event_id, lease_token, publisher_id, str(error), retry_seconds))


class FakeSink:
    def __init__(self, fail_event_ids=()):
        self.fail_event_ids = set(fail_event_ids)
        self.published = []

    def publish(self, event_type, payload, *, idempotency_key):
        if idempotency_key in self.fail_event_ids:
            raise RuntimeError("broker temporarily unavailable")
        self.published.append((event_type, dict(payload), idempotency_key))


def _event(event_type="distribution.admitted"):
    event_id = uuid4()
    return OutboxLease(event_id, event_type, uuid4(), {"job_id": "job-001"}, uuid4(), "outbox-publisher-1")


def test_worker_claims_and_acknowledges_each_successful_event_with_event_id_dedupe():
    event = _event()
    service = FakeService([event])
    sink = FakeSink()
    worker = TransactionalOutboxWorker(service, sink, publisher_id="outbox-publisher-1", batch_size=10, lease_seconds=60)

    result = worker.run_once()

    assert result.claimed == result.published == 1
    assert result.deferred == 0
    assert service.claim_calls == [("outbox-publisher-1", 10, 60)]
    assert sink.published == [("distribution.admitted", {"job_id": "job-001"}, str(event.event_id))]
    assert service.published == [(event.event_id, event.lease_token, "outbox-publisher-1")]


def test_worker_defers_failed_event_but_continues_to_publish_later_events():
    failed, successful = _event(), _event("quota.consumed")
    service = FakeService([failed, successful])
    sink = FakeSink({str(failed.event_id)})
    worker = TransactionalOutboxWorker(service, sink, publisher_id="outbox-publisher-1", retry_seconds=45)

    result = worker.run_once()

    assert (result.claimed, result.published, result.deferred) == (2, 1, 1)
    assert service.deferred == [(failed.event_id, failed.lease_token, "outbox-publisher-1", "broker temporarily unavailable", 45)]
    assert service.published == [(successful.event_id, successful.lease_token, "outbox-publisher-1")]


def test_worker_keeps_batch_live_when_lease_is_lost_before_retry_transition():
    failed, successful = _event(), _event()

    class LeaseRaceService(FakeService):
        def defer_outbox(self, *args, **kwargs):
            raise ReportFlowError("Outbox retry update was rejected because its lease is invalid.")

    service = LeaseRaceService([failed, successful])
    sink = FakeSink({str(failed.event_id)})
    worker = TransactionalOutboxWorker(service, sink, publisher_id="outbox-publisher-1")

    result = worker.run_once()

    assert (result.claimed, result.published, result.deferred) == (2, 1, 1)
    assert service.published == [(successful.event_id, successful.lease_token, "outbox-publisher-1")]

-- ReportFlow v2.7: terminal outbox dead-letter state and retry claim index.
-- Execute after 001_v26_atomic_quota_reservation.sql and 002_v261_outbox_worker_leases.sql.

BEGIN;

ALTER TABLE rf_outbox_events
    ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT,
    ADD COLUMN IF NOT EXISTS dead_lettered_by TEXT;

CREATE INDEX IF NOT EXISTS rf_outbox_ready_claim_v27_idx
    ON rf_outbox_events (available_at ASC, occurred_at ASC)
    WHERE published_at IS NULL AND dead_lettered_at IS NULL;

CREATE INDEX IF NOT EXISTS rf_outbox_dead_letter_v27_idx
    ON rf_outbox_events (dead_lettered_at DESC)
    WHERE dead_lettered_at IS NOT NULL;

COMMIT;

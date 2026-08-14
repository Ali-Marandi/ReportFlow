-- ReportFlow v2.6.1: durable publisher ownership and retry scheduling for transactional outbox.
-- Execute after 001_v26_atomic_quota_reservation.sql.

BEGIN;

ALTER TABLE rf_outbox_events
    ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS lease_owner TEXT;

CREATE INDEX IF NOT EXISTS rf_outbox_claim_v261_idx
    ON rf_outbox_events (available_at ASC, occurred_at ASC)
    WHERE published_at IS NULL;

COMMIT;

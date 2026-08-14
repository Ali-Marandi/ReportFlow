-- ReportFlow v2.6 sample schema: PostgreSQL atomic quota reservation + transactional outbox.
-- Run this only in the server-side control plane. The desktop executable must never connect
-- with privileges that can mutate quota, reservations, jobs or outbox state.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
    CREATE TYPE rf_overage_behavior AS ENUM ('deny', 'allow');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE rf_reservation_state AS ENUM ('held', 'consumed', 'released', 'expired');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE rf_reservation_reason AS ENUM ('enqueue', 'success', 'cancelled', 'dead_letter', 'ttl_expiry', 'manual_adjustment');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE TYPE rf_job_status AS ENUM ('queued', 'running', 'retry', 'succeeded', 'dead_letter', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS rf_quota_buckets (
    tenant_id TEXT NOT NULL,
    meter TEXT NOT NULL,
    billing_period DATE NOT NULL,
    quota_scope_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL CHECK (plan_version > 0),
    entitlement_effective_from TIMESTAMPTZ NOT NULL,
    overage_behavior rf_overage_behavior NOT NULL,
    included_units BIGINT NOT NULL CHECK (included_units >= 0),
    consumed_units BIGINT NOT NULL DEFAULT 0 CHECK (consumed_units >= 0),
    held_units BIGINT NOT NULL DEFAULT 0 CHECK (held_units >= 0),
    overage_held_units BIGINT NOT NULL DEFAULT 0 CHECK (overage_held_units >= 0),
    overage_consumed_units BIGINT NOT NULL DEFAULT 0 CHECK (overage_consumed_units >= 0),
    row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, meter, billing_period, quota_scope_id),
    CHECK (billing_period = date_trunc('month', billing_period)::date),
    CHECK (consumed_units + held_units >= 0)
);

CREATE TABLE IF NOT EXISTS rf_distribution_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL,
    status rf_job_status NOT NULL DEFAULT 'queued',
    priority SMALLINT NOT NULL DEFAULT 0 CHECK (priority BETWEEN -100 AND 100),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((status = 'running') = (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS rf_distribution_claim_idx
    ON rf_distribution_jobs (status, priority DESC, created_at ASC)
    WHERE status IN ('queued', 'retry');

CREATE TABLE IF NOT EXISTS rf_quota_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    meter TEXT NOT NULL,
    billing_period DATE NOT NULL,
    quota_scope_id TEXT NOT NULL,
    distribution_job_id UUID NOT NULL UNIQUE REFERENCES rf_distribution_jobs(id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    overage_units BIGINT NOT NULL DEFAULT 0 CHECK (overage_units >= 0),
    state rf_reservation_state NOT NULL DEFAULT 'held',
    reason rf_reservation_reason NOT NULL DEFAULT 'enqueue',
    plan_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL CHECK (plan_version > 0),
    entitlement_effective_from TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    last_heartbeat_at TIMESTAMPTZ,
    actor_subject TEXT NOT NULL,
    worker_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalized_at TIMESTAMPTZ,
    CHECK (billing_period = date_trunc('month', billing_period)::date),
    CHECK ((state = 'held' AND finalized_at IS NULL) OR (state <> 'held' AND finalized_at IS NOT NULL)),
    FOREIGN KEY (tenant_id, meter, billing_period, quota_scope_id)
        REFERENCES rf_quota_buckets(tenant_id, meter, billing_period, quota_scope_id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS rf_reservation_sweep_idx
    ON rf_quota_reservations (state, expires_at)
    WHERE state = 'held';
CREATE INDEX IF NOT EXISTS rf_reservation_scope_idx
    ON rf_quota_reservations (tenant_id, meter, billing_period, quota_scope_id);

CREATE TABLE IF NOT EXISTS rf_usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reservation_id UUID NOT NULL UNIQUE REFERENCES rf_quota_reservations(id) ON DELETE RESTRICT,
    tenant_id TEXT NOT NULL,
    meter TEXT NOT NULL,
    billing_period DATE NOT NULL,
    quota_scope_id TEXT NOT NULL,
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    overage_units BIGINT NOT NULL DEFAULT 0 CHECK (overage_units >= 0),
    plan_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL CHECK (plan_version > 0),
    entitlement_effective_from TIMESTAMPTZ NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (billing_period = date_trunc('month', billing_period)::date)
);

CREATE TABLE IF NOT EXISTS rf_outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type TEXT NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    publish_attempts INTEGER NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS rf_outbox_unpublished_idx
    ON rf_outbox_events (occurred_at ASC)
    WHERE published_at IS NULL;

COMMIT;

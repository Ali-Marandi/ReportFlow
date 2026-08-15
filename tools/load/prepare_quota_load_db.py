"""Prepare a disposable PostgreSQL database for the quota Locust harness."""
from __future__ import annotations

import os
from pathlib import Path

from psycopg import connect


def main() -> None:
    dsn = os.environ.get("REPORTFLOW_TEST_POSTGRES_DSN", "")
    if not dsn:
        raise SystemExit("REPORTFLOW_TEST_POSTGRES_DSN is required and must reference a disposable database.")
    root = Path(__file__).parents[2]
    migrations = [
        root / "migrations/postgres/001_v26_atomic_quota_reservation.sql",
        root / "migrations/postgres/002_v261_outbox_worker_leases.sql",
        root / "migrations/postgres/003_v27_outbox_dead_letter.sql",
    ]
    with connect(dsn, autocommit=True) as connection:
        for migration in migrations:
            connection.execute(migration.read_text(encoding="utf-8"))
        connection.execute(
            "TRUNCATE rf_usage_events,rf_quota_reservations,rf_distribution_jobs,rf_quota_buckets,rf_outbox_events RESTART IDENTITY CASCADE"
        )
    print("prepared isolated quota load database")


if __name__ == "__main__":
    main()

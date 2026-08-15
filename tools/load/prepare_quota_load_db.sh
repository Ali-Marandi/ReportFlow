#!/usr/bin/env bash
set -euo pipefail
: "${REPORTFLOW_TEST_POSTGRES_DSN:?REPORTFLOW_TEST_POSTGRES_DSN is required}"
exec python3 "$(dirname "$0")/prepare_quota_load_db.py"

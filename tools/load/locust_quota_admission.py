"""Locust workload for the isolated ReportFlow quota-admission harness.

Example:
  REPORTFLOW_LOAD_RPS_PER_USER=10 locust -f tools/load/locust_quota_admission.py --headless \
    -u 100 -r 50 -t 30s --host http://127.0.0.1:8090 --csv .task_artifacts/locust/quota_1000rps
"""
from __future__ import annotations

import itertools
import os

from locust import HttpUser, constant_throughput, task

_REQUESTS = itertools.count()
_RUN_ID = os.environ.get("REPORTFLOW_LOAD_RUN_ID", "local")
_RPS_PER_USER = float(os.environ.get("REPORTFLOW_LOAD_RPS_PER_USER", "10"))


class QuotaAdmissionUser(HttpUser):
    # With 100 users and 10 calls/s each, this targets approximately 1,000 RPS.
    wait_time = constant_throughput(_RPS_PER_USER)

    @task
    def admit_synthetic_delivery(self) -> None:
        sequence = next(_REQUESTS)
        # 128 independent commercial scopes avoid benchmarking one hot quota row only.
        payload = {"request_id": f"load-{_RUN_ID}-{sequence:012d}", "tenant_shard": sequence % 128}
        with self.client.post("/load/admit", json=payload, name="POST /load/admit", catch_response=True) as response:
            if response.status_code == 200:
                body = response.json()
                if not body.get("job_id") or not body.get("reservation_id"):
                    response.failure("admission response is missing immutable identifiers")
            else:
                response.failure(f"unexpected status {response.status_code}")

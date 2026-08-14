"""Server-side dispatch for v2.2 distribution jobs.

Construct the registry only in the protected worker process. The payload stores
an approved destination ID, never a bucket credential, service principal, or
connection string.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from reportflow_app.core import ProjectStore, ReportFlowError
from reportflow_app.distribution_v22 import ArtifactDestination, DeliveredArtifact, DistributionJob, NonRetryableDistributionError


class DestinationRegistry:
    def __init__(self) -> None:
        self._destinations: dict[str, ArtifactDestination] = {}

    def register(self, destination_id: str, destination: ArtifactDestination) -> None:
        if not destination_id or destination_id in self._destinations:
            raise ReportFlowError("Distribution destination ID is empty or already registered.")
        self._destinations[destination_id] = destination

    def resolve(self, destination_id: str) -> ArtifactDestination:
        try:
            return self._destinations[destination_id]
        except KeyError as error:
            raise NonRetryableDistributionError("Distribution destination is not approved for this worker.") from error


class ArtifactDeliveryProcessor:
    def __init__(self, registry: DestinationRegistry, store: ProjectStore) -> None:
        self.registry, self.store = registry, store

    def __call__(self, job: DistributionJob) -> None:
        if job.kind != "artifact_delivery":
            raise NonRetryableDistributionError("Worker received an unsupported distribution job kind.")
        payload = job.payload
        required = {"destination_id", "artifact_path", "object_key", "idempotency_key", "classification"}
        if set(payload) != required:
            raise NonRetryableDistributionError("Artifact job payload does not match the approved schema.")
        destination = self.registry.resolve(str(payload["destination_id"]))
        delivered = destination.upload(
            Path(str(payload["artifact_path"])), str(payload["object_key"]), str(payload["idempotency_key"]), str(payload["classification"]),
        )
        self.store.audit(
            "distribution.artifact_delivered", "distribution_job", job.id,
            {"destination_id": payload["destination_id"], "remote_uri": delivered.remote_uri, "sha256": delivered.sha256},
            actor="distribution-worker",
        )

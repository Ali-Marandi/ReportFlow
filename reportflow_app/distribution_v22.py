"""Persistent, policy-aware distribution primitives for ReportFlow v2.2.

This module is a durable control-plane foundation. A production worker must run
server-side, behind TLS and identity controls; the desktop application only
submits approved jobs and shows their audit-safe status.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal, Protocol
from uuid import uuid4

from reportflow_app.core import ProjectStore, ReportFlowError, utc_now


JobStatus = Literal["queued", "running", "retry", "succeeded", "dead_letter", "cancelled"]
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{7,200}$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,800}$")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: int = 30
    max_delay_seconds: int = 3_600
    lease_seconds: int = 300

    def validate(self) -> None:
        if not 1 <= self.max_attempts <= 20:
            raise ReportFlowError("Retry policy max_attempts must be between 1 and 20.")
        if not 1 <= self.base_delay_seconds <= self.max_delay_seconds <= 86_400:
            raise ReportFlowError("Retry policy delay bounds are invalid.")
        if not 30 <= self.lease_seconds <= 3_600:
            raise ReportFlowError("Queue lease must be between 30 and 3600 seconds.")

    def delay_for_attempt(self, attempt: int) -> int:
        self.validate()
        return min(self.max_delay_seconds, self.base_delay_seconds * (2 ** max(0, attempt - 1)))


@dataclass(frozen=True, slots=True)
class DistributionJob:
    id: str
    idempotency_key: str
    kind: str
    payload: dict[str, Any]
    status: JobStatus
    priority: int
    attempt_count: int
    retry_policy: RetryPolicy
    created_at: str
    available_at: str
    lease_token: str | None = None
    lease_expires_at: str | None = None
    last_error: str = ""


@dataclass(frozen=True, slots=True)
class JobClaim:
    job: DistributionJob
    lease_token: str


@dataclass(frozen=True, slots=True)
class JobExecutionOutcome:
    job_id: str
    status: JobStatus
    message: str


class DistributionQueue:
    """SQLite queue with idempotent enrollment, leases, exponential retry and DLQ state."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self._initialize()

    def _initialize(self) -> None:
        with self.store._connect() as connection:  # ProjectStore owns the shared SQLite boundary.
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS distribution_jobs (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','retry','succeeded','dead_letter','cancelled')),
                    priority INTEGER NOT NULL DEFAULT 0 CHECK(priority BETWEEN -100 AND 100),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    base_delay_seconds INTEGER NOT NULL,
                    max_delay_seconds INTEGER NOT NULL,
                    lease_seconds INTEGER NOT NULL,
                    available_at TEXT NOT NULL,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_distribution_jobs_claim
                ON distribution_jobs(status, available_at, priority DESC, created_at ASC);
                """
            )

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        *,
        retry_policy: RetryPolicy = RetryPolicy(),
        priority: int = 0,
        actor: str = "local-user",
    ) -> tuple[DistributionJob, bool]:
        retry_policy.validate()
        if not kind or not _SAFE_KEY.fullmatch(idempotency_key):
            raise ReportFlowError("Queue job kind or idempotency key is invalid.")
        if not -100 <= priority <= 100:
            raise ReportFlowError("Queue job priority must be between -100 and 100.")
        _validate_payload(payload)
        now, job_id = utc_now(), str(uuid4())
        with self.store._connect() as connection:
            existing = connection.execute("SELECT * FROM distribution_jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing is not None:
                return self._row_to_job(existing), False
            connection.execute(
                """INSERT INTO distribution_jobs(
                    id,idempotency_key,kind,payload,status,priority,attempt_count,max_attempts,base_delay_seconds,max_delay_seconds,
                    lease_seconds,available_at,lease_token,lease_expires_at,last_error,created_at,updated_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, 0, ?, ?, ?, ?, ?, NULL, NULL, '', ?, ?)""",
                (
                    job_id, idempotency_key, kind, json.dumps(payload, ensure_ascii=False, sort_keys=True), priority,
                    retry_policy.max_attempts, retry_policy.base_delay_seconds, retry_policy.max_delay_seconds,
                    retry_policy.lease_seconds, now, now, now,
                ),
            )
            row = connection.execute("SELECT * FROM distribution_jobs WHERE id=?", (job_id,)).fetchone()
        job = self._row_to_job(row)
        self.store.audit("distribution.enqueued", "distribution_job", job.id, {"kind": kind, "priority": priority, "idempotency_key": idempotency_key}, actor)
        return job, True

    def claim_next(self, worker_id: str, now: datetime | None = None) -> JobClaim | None:
        if not worker_id or len(worker_id) > 128:
            raise ReportFlowError("Worker ID is required and must be at most 128 characters.")
        current = now or datetime.now(UTC)
        current_text = _as_utc_text(current)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._recover_expired_leases(connection, current)
            row = connection.execute(
                """SELECT * FROM distribution_jobs
                WHERE status IN ('queued','retry') AND available_at <= ?
                ORDER BY priority DESC, created_at ASC LIMIT 1""",
                (current_text,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            policy = RetryPolicy(row["max_attempts"], row["base_delay_seconds"], row["max_delay_seconds"], row["lease_seconds"])
            token = str(uuid4())
            expires = _as_utc_text(current + timedelta(seconds=policy.lease_seconds))
            connection.execute(
                """UPDATE distribution_jobs SET status='running', attempt_count=attempt_count+1, lease_token=?, lease_expires_at=?, updated_at=? WHERE id=?""",
                (token, expires, current_text, row["id"]),
            )
            claimed = connection.execute("SELECT * FROM distribution_jobs WHERE id=?", (row["id"],)).fetchone()
            connection.commit()
        job = self._row_to_job(claimed)
        self.store.audit("distribution.claimed", "distribution_job", job.id, {"worker_id": worker_id, "attempt": job.attempt_count})
        return JobClaim(job, token)

    def complete(self, claim: JobClaim, actor: str = "distribution-worker") -> DistributionJob:
        now = utc_now()
        with self.store._connect() as connection:
            cursor = connection.execute(
                """UPDATE distribution_jobs SET status='succeeded', lease_token=NULL, lease_expires_at=NULL, updated_at=?
                WHERE id=? AND status='running' AND lease_token=?""",
                (now, claim.job.id, claim.lease_token),
            )
            if cursor.rowcount != 1:
                raise ReportFlowError("Queue completion was rejected because the worker lease is no longer valid.")
            row = connection.execute("SELECT * FROM distribution_jobs WHERE id=?", (claim.job.id,)).fetchone()
        job = self._row_to_job(row)
        self.store.audit("distribution.succeeded", "distribution_job", job.id, {"attempt": job.attempt_count}, actor)
        return job

    def fail(self, claim: JobClaim, error: Exception | str, *, retryable: bool, now: datetime | None = None, actor: str = "distribution-worker") -> DistributionJob:
        current = now or datetime.now(UTC)
        safe_error = _safe_error(error)
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM distribution_jobs WHERE id=?", (claim.job.id,)).fetchone()
            if row is None or row["status"] != "running" or row["lease_token"] != claim.lease_token:
                raise ReportFlowError("Queue failure update was rejected because the worker lease is no longer valid.")
            policy = RetryPolicy(row["max_attempts"], row["base_delay_seconds"], row["max_delay_seconds"], row["lease_seconds"])
            can_retry = retryable and int(row["attempt_count"]) < policy.max_attempts
            status: JobStatus = "retry" if can_retry else "dead_letter"
            available_at = _as_utc_text(current + timedelta(seconds=policy.delay_for_attempt(int(row["attempt_count"])))) if can_retry else _as_utc_text(current)
            connection.execute(
                """UPDATE distribution_jobs SET status=?, available_at=?, lease_token=NULL, lease_expires_at=NULL, last_error=?, updated_at=?
                WHERE id=?""",
                (status, available_at, safe_error, _as_utc_text(current), claim.job.id),
            )
            updated = connection.execute("SELECT * FROM distribution_jobs WHERE id=?", (claim.job.id,)).fetchone()
        job = self._row_to_job(updated)
        self.store.audit(f"distribution.{status}", "distribution_job", job.id, {"attempt": job.attempt_count, "retryable": retryable, "error": safe_error}, actor)
        return job

    def cancel(self, job_id: str, actor: str = "local-user") -> DistributionJob:
        with self.store._connect() as connection:
            cursor = connection.execute(
                """UPDATE distribution_jobs SET status='cancelled', lease_token=NULL, lease_expires_at=NULL, updated_at=?
                WHERE id=? AND status IN ('queued','retry')""", (utc_now(), job_id)
            )
            if cursor.rowcount != 1:
                raise ReportFlowError("Only queued or retrying jobs can be cancelled.")
            row = connection.execute("SELECT * FROM distribution_jobs WHERE id=?", (job_id,)).fetchone()
        job = self._row_to_job(row)
        self.store.audit("distribution.cancelled", "distribution_job", job_id, actor=actor)
        return job

    def get(self, job_id: str) -> DistributionJob:
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM distribution_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ReportFlowError("Distribution job was not found.")
        return self._row_to_job(row)

    def list(self, statuses: tuple[JobStatus, ...] | None = None, limit: int = 100) -> list[DistributionJob]:
        if not 1 <= limit <= 1_000:
            raise ReportFlowError("Queue list limit must be between 1 and 1000.")
        allowed = {"queued", "running", "retry", "succeeded", "dead_letter", "cancelled"}
        with self.store._connect() as connection:
            if statuses:
                if not set(statuses).issubset(allowed) or len(statuses) > len(allowed):
                    raise ReportFlowError("Queue list contains an invalid job status.")
                queries = {
                    1: "SELECT * FROM distribution_jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    2: "SELECT * FROM distribution_jobs WHERE status IN (?,?) ORDER BY created_at DESC LIMIT ?",
                    3: "SELECT * FROM distribution_jobs WHERE status IN (?,?,?) ORDER BY created_at DESC LIMIT ?",
                    4: "SELECT * FROM distribution_jobs WHERE status IN (?,?,?,?) ORDER BY created_at DESC LIMIT ?",
                    5: "SELECT * FROM distribution_jobs WHERE status IN (?,?,?,?,?) ORDER BY created_at DESC LIMIT ?",
                    6: "SELECT * FROM distribution_jobs WHERE status IN (?,?,?,?,?,?) ORDER BY created_at DESC LIMIT ?",
                }
                rows = connection.execute(queries[len(statuses)], (*statuses, limit)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM distribution_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(row) for row in rows]

    def _recover_expired_leases(self, connection: sqlite3.Connection, now: datetime) -> None:
        rows = connection.execute("SELECT * FROM distribution_jobs WHERE status='running' AND lease_expires_at < ?", (_as_utc_text(now),)).fetchall()
        for row in rows:
            policy = RetryPolicy(row["max_attempts"], row["base_delay_seconds"], row["max_delay_seconds"], row["lease_seconds"])
            can_retry = int(row["attempt_count"]) < policy.max_attempts
            status = "retry" if can_retry else "dead_letter"
            available = _as_utc_text(now + timedelta(seconds=policy.delay_for_attempt(int(row["attempt_count"])))) if can_retry else _as_utc_text(now)
            connection.execute(
                """UPDATE distribution_jobs SET status=?, available_at=?, lease_token=NULL, lease_expires_at=NULL,
                last_error='Worker lease expired.', updated_at=? WHERE id=?""",
                (status, available, _as_utc_text(now), row["id"]),
            )

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> DistributionJob:
        return DistributionJob(
            id=row["id"], idempotency_key=row["idempotency_key"], kind=row["kind"], payload=json.loads(row["payload"]),
            status=row["status"], priority=row["priority"], attempt_count=row["attempt_count"],
            retry_policy=RetryPolicy(row["max_attempts"], row["base_delay_seconds"], row["max_delay_seconds"], row["lease_seconds"]),
            created_at=row["created_at"], available_at=row["available_at"], lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"], last_error=row["last_error"],
        )


class JobProcessor(Protocol):
    def __call__(self, job: DistributionJob) -> None: ...


class DistributionWorker:
    """A single iteration worker; the hosting environment owns scheduling and lifecycle."""

    def __init__(self, queue: DistributionQueue, worker_id: str) -> None:
        self.queue, self.worker_id = queue, worker_id

    def run_once(self, processor: JobProcessor) -> JobExecutionOutcome | None:
        claim = self.queue.claim_next(self.worker_id)
        if claim is None:
            return None
        try:
            processor(claim.job)
            job = self.queue.complete(claim)
            return JobExecutionOutcome(job.id, job.status, "Job completed.")
        except NonRetryableDistributionError as error:
            job = self.queue.fail(claim, error, retryable=False)
            return JobExecutionOutcome(job.id, job.status, job.last_error)
        except Exception as error:
            job = self.queue.fail(claim, error, retryable=True)
            return JobExecutionOutcome(job.id, job.status, job.last_error)


class NonRetryableDistributionError(ReportFlowError):
    """Use only for policy, validation, or authorization errors that cannot succeed on retry."""


@dataclass(frozen=True, slots=True)
class DeliveredArtifact:
    local_path: str
    remote_uri: str
    sha256: str
    idempotency_key: str


class ArtifactDestination(Protocol):
    def upload(self, artifact: Path, object_key: str, idempotency_key: str, classification: str) -> DeliveredArtifact: ...


class S3ArtifactDestination:
    """S3 upload adapter with checksum, KMS policy and immutable object-key semantics."""

    def __init__(self, bucket: str, key_prefix: str, *, expected_bucket_owner: str | None = None, kms_key_id: str | None = None, client: Any | None = None) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ReportFlowError("S3 bucket name is invalid.")
        self.bucket, self.key_prefix, self.expected_bucket_owner, self.kms_key_id = bucket, _safe_prefix(key_prefix), expected_bucket_owner, kms_key_id
        self._client = client

    def upload(self, artifact: Path, object_key: str, idempotency_key: str, classification: str) -> DeliveredArtifact:
        _validate_artifact(artifact, object_key, idempotency_key, classification)
        client = self._client or _new_s3_client()
        key = f"{self.key_prefix}{object_key}"
        digest = _file_sha256(artifact)
        request: dict[str, Any] = {
            "Bucket": self.bucket, "Key": key, "Body": artifact.read_bytes(), "ChecksumAlgorithm": "SHA256",
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(digest)).decode("ascii"), "IfNoneMatch": "*",
            "Metadata": {"reportflow-sha256": digest, "reportflow-idempotency-key": idempotency_key, "classification": classification},
        }
        if self.expected_bucket_owner:
            request["ExpectedBucketOwner"] = self.expected_bucket_owner
        if self.kms_key_id:
            request.update({"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms_key_id})
        try:
            client.put_object(**request)
        except Exception as error:
            response = getattr(error, "response", {}) or {}
            code = str(response.get("Error", {}).get("Code", ""))
            if code in {"PreconditionFailed", "412"} and self._is_same_existing_object(client, key, idempotency_key, digest):
                return DeliveredArtifact(str(artifact), f"s3://{self.bucket}/{key}", digest, idempotency_key)
            raise _classify_storage_error(error)
        return DeliveredArtifact(str(artifact), f"s3://{self.bucket}/{key}", digest, idempotency_key)

    def _is_same_existing_object(self, client: Any, key: str, idempotency_key: str, digest: str) -> bool:
        try:
            response = client.head_object(Bucket=self.bucket, Key=key, **({"ExpectedBucketOwner": self.expected_bucket_owner} if self.expected_bucket_owner else {}))
            metadata = {str(k).lower(): str(v) for k, v in response.get("Metadata", {}).items()}
            return metadata.get("reportflow-idempotency-key") == idempotency_key and metadata.get("reportflow-sha256") == digest
        except Exception:
            return False


class AzureBlobArtifactDestination:
    """Azure Blob upload adapter using workload identity and conditional-create semantics."""

    def __init__(self, account_url: str, container: str, key_prefix: str, *, credential: Any | None = None, service_client: Any | None = None) -> None:
        if not account_url.startswith("https://") or ".blob.core.windows.net" not in account_url:
            raise ReportFlowError("Azure Blob account URL must be an HTTPS blob endpoint.")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?", container):
            raise ReportFlowError("Azure Blob container name is invalid.")
        self.account_url, self.container, self.key_prefix, self.credential, self._service_client = account_url.rstrip("/"), container, _safe_prefix(key_prefix), credential, service_client

    def upload(self, artifact: Path, object_key: str, idempotency_key: str, classification: str) -> DeliveredArtifact:
        _validate_artifact(artifact, object_key, idempotency_key, classification)
        service = self._service_client or _new_blob_service_client(self.account_url, self.credential)
        name, digest = f"{self.key_prefix}{object_key}", _file_sha256(artifact)
        blob = service.get_blob_client(container=self.container, blob=name)
        metadata = {"reportflow-sha256": digest, "reportflow-idempotency-key": idempotency_key, "classification": classification}
        try:
            with artifact.open("rb") as handle:
                blob.upload_blob(handle, overwrite=False, metadata=metadata, validate_content=True, if_none_match="*")
        except Exception as error:
            if error.__class__.__name__ in {"ResourceExistsError", "ResourceModifiedError"} and self._is_same_existing_blob(blob, idempotency_key, digest):
                return DeliveredArtifact(str(artifact), f"azblob://{self.account_url.split('://', 1)[1]}/{self.container}/{name}", digest, idempotency_key)
            raise _classify_storage_error(error)
        return DeliveredArtifact(str(artifact), f"azblob://{self.account_url.split('://', 1)[1]}/{self.container}/{name}", digest, idempotency_key)

    @staticmethod
    def _is_same_existing_blob(blob: Any, idempotency_key: str, digest: str) -> bool:
        try:
            metadata = {str(k).lower(): str(v) for k, v in blob.get_blob_properties().metadata.items()}
            return metadata.get("reportflow-idempotency-key") == idempotency_key and metadata.get("reportflow-sha256") == digest
        except Exception:
            return False


def artifact_delivery_payload(destination_id: str, artifact: Path, object_key: str, idempotency_key: str, classification: str = "internal") -> dict[str, str]:
    """Create a queue-safe payload. Destination credentials are resolved only in the worker registry."""
    _validate_artifact(artifact, object_key, idempotency_key, classification)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,127}", destination_id):
        raise ReportFlowError("Distribution destination ID is invalid.")
    return {"destination_id": destination_id, "artifact_path": str(artifact.resolve()), "object_key": object_key, "idempotency_key": idempotency_key, "classification": classification}


def _new_s3_client() -> Any:
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as error:
        raise NonRetryableDistributionError("S3 destination requires optional dependency boto3.") from error
    return boto3.client("s3")  # Workload identity / instance role is resolved by the approved environment.


def _new_blob_service_client(account_url: str, credential: Any | None) -> Any:
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
        from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]
    except ImportError as error:
        raise NonRetryableDistributionError("Azure Blob destination requires optional Azure Identity and Storage Blob dependencies.") from error
    return BlobServiceClient(account_url=account_url, credential=credential or DefaultAzureCredential())


def _validate_payload(payload: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ReportFlowError("Queue payload must be JSON-serializable.") from error
    if len(encoded.encode("utf-8")) > 64_000:
        raise ReportFlowError("Queue payload exceeds the 64 KiB control-plane limit; store artifacts externally.")
    forbidden = {"password", "secret", "token", "access_key", "private_key"}
    if any(key.lower() in forbidden for key in _walk_keys(payload)):
        raise ReportFlowError("Queue payload cannot contain credentials; use a central secret provider in the worker.")


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _validate_artifact(artifact: Path, object_key: str, idempotency_key: str, classification: str) -> None:
    if not artifact.is_file() or artifact.is_symlink():
        raise NonRetryableDistributionError("Distribution artifact must be an existing regular file.")
    if artifact.stat().st_size > 512 * 1024 * 1024:
        raise NonRetryableDistributionError("Distribution artifact exceeds the 512 MiB policy limit.")
    if not _SAFE_PATH.fullmatch(object_key) or ".." in object_key.split("/") or object_key.startswith("/"):
        raise NonRetryableDistributionError("Storage object key is invalid or unsafe.")
    if not _SAFE_KEY.fullmatch(idempotency_key):
        raise NonRetryableDistributionError("Artifact idempotency key is invalid.")
    if classification not in {"public", "internal", "confidential", "restricted"}:
        raise NonRetryableDistributionError("Artifact classification is invalid.")


def _safe_prefix(value: str) -> str:
    value = value.strip().strip("/")
    if value and (not _SAFE_PATH.fullmatch(value) or ".." in value.split("/")):
        raise ReportFlowError("Storage key prefix is invalid or unsafe.")
    return f"{value}/" if value else ""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_error(error: Exception | str) -> str:
    message = str(error).replace("\n", " ").strip()
    return (message or error.__class__.__name__)[:500]


def _classify_storage_error(error: Exception) -> Exception:
    name = error.__class__.__name__
    if name in {"ClientError", "HttpResponseError", "ServiceRequestError", "ServiceResponseError", "EndpointConnectionError"}:
        return error  # The worker applies a bounded retry policy to transient transport/service errors.
    return NonRetryableDistributionError("Storage destination rejected the artifact by policy or configuration.")


def _as_utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ReportFlowError("Queue timestamps must be timezone-aware.")
    return value.astimezone(UTC).isoformat()

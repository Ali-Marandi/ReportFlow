"""Enterprise governance controls for ReportFlow v2.3.

The module deliberately separates delivery approval from queue execution.  A queue
worker must ask this module for authorization immediately before a sensitive
artifact is dispatched.  The local SQLite ledger is tamper-evident through a
canonical hash chain; production deployments should anchor checkpoints in an
independent immutable service.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, Mapping, TYPE_CHECKING
from uuid import uuid4

from reportflow_app.core import ProjectStore, ReportFlowError, utc_now

if TYPE_CHECKING:
    from reportflow_app.distribution_v22 import DistributionJob, DistributionQueue, RetryPolicy


ApprovalStatus = Literal["pending", "approved", "rejected", "cancelled"]
Decision = Literal["approved", "rejected"]
Classification = Literal["public", "internal", "confidential", "restricted"]

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$")
_SAFE_ROLE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_ALLOWED_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}


@dataclass(frozen=True, slots=True)
class ApprovalPolicy:
    """A deterministic approval rule stored with the request that it governs."""

    policy_id: str
    minimum_approvals: int
    required_roles: tuple[str, ...] = ()
    governed_classifications: tuple[Classification, ...] = ("confidential", "restricted")

    def validate(self) -> None:
        _validate_identifier(self.policy_id, "Policy ID")
        if not 1 <= self.minimum_approvals <= 5:
            raise ReportFlowError("Approval policy minimum_approvals must be between 1 and 5.")
        if len(set(self.required_roles)) != len(self.required_roles):
            raise ReportFlowError("Approval policy roles must be unique.")
        if any(not _SAFE_ROLE.fullmatch(role) for role in self.required_roles):
            raise ReportFlowError("Approval policy contains an invalid role name.")
        if not self.governed_classifications or not set(self.governed_classifications).issubset(_ALLOWED_CLASSIFICATIONS):
            raise ReportFlowError("Approval policy contains an invalid governed classification.")

    def snapshot(self) -> dict[str, Any]:
        self.validate()
        return {
            "policy_id": self.policy_id,
            "minimum_approvals": self.minimum_approvals,
            "required_roles": list(self.required_roles),
            "governed_classifications": list(self.governed_classifications),
        }

    @classmethod
    def from_snapshot(cls, value: Mapping[str, Any]) -> "ApprovalPolicy":
        policy = cls(
            policy_id=str(value["policy_id"]),
            minimum_approvals=int(value["minimum_approvals"]),
            required_roles=tuple(str(item) for item in value.get("required_roles", [])),
            governed_classifications=tuple(str(item) for item in value.get("governed_classifications", [])),  # type: ignore[arg-type]
        )
        policy.validate()
        return policy


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    id: str
    subject_type: str
    subject_id: str
    requester: str
    classification: Classification
    content: dict[str, Any]
    content_fingerprint: str
    policy: ApprovalPolicy
    status: ApprovalStatus
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    id: str
    request_id: str
    approver: str
    decision: Decision
    roles: tuple[str, ...]
    comment: str
    decided_at: str


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    sequence: int
    id: str
    occurred_at: str
    action: str
    actor: str
    entity_type: str
    entity_id: str
    details: dict[str, Any]
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class LedgerVerification:
    valid: bool
    event_count: int
    head_hash: str
    failure: str = ""


class IntegrityLedger:
    """Append-only event chain with optional HMAC protection.

    A plain hash chain detects ordinary database edits and reordering. Supplying an
    integrity key makes recalculation impossible for a database-only attacker. The
    key must come from an OS or central secret provider and must never be saved in
    the project database.
    """

    _GENESIS = "0" * 64

    def __init__(self, store: ProjectStore, integrity_key: bytes | None = None) -> None:
        if integrity_key is not None and len(integrity_key) < 16:
            raise ReportFlowError("Ledger integrity key must be at least 16 bytes.")
        self.store, self._integrity_key = store, integrity_key
        self._initialize()

    def _initialize(self) -> None:
        with self.store._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS governance_ledger_events (
                    sequence INTEGER PRIMARY KEY,
                    id TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    details TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL
                )
                """
            )

    def append(self, action: str, actor: str, entity_type: str, entity_id: str, details: Mapping[str, Any] | None = None) -> LedgerEvent:
        _validate_identifier(action, "Ledger action")
        _validate_identifier(actor, "Ledger actor")
        _validate_identifier(entity_type, "Ledger entity type")
        _validate_identifier(entity_id, "Ledger entity ID")
        safe_details = _safe_json_object(details or {}, "Ledger details")
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT sequence, event_hash FROM governance_ledger_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = int(previous["sequence"]) + 1 if previous else 1
            previous_hash = str(previous["event_hash"]) if previous else self._GENESIS
            event_id, occurred_at = str(uuid4()), utc_now()
            payload = self._payload_for_hash(sequence, event_id, occurred_at, action, actor, entity_type, entity_id, safe_details, previous_hash)
            event_hash = self._digest(payload)
            connection.execute(
                """INSERT INTO governance_ledger_events(
                    sequence,id,occurred_at,action,actor,entity_type,entity_id,details,previous_hash,event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sequence, event_id, occurred_at, action, actor, entity_type, entity_id,
                 _canonical_json(safe_details), previous_hash, event_hash),
            )
            connection.commit()
        return LedgerEvent(sequence, event_id, occurred_at, action, actor, entity_type, entity_id, safe_details, previous_hash, event_hash)

    def list_events(self, limit: int = 500) -> list[LedgerEvent]:
        if not 1 <= limit <= 10_000:
            raise ReportFlowError("Ledger list limit must be between 1 and 10000.")
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM governance_ledger_events ORDER BY sequence DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_event(row) for row in reversed(rows)]

    def verify(self) -> LedgerVerification:
        expected_previous, expected_sequence, count = self._GENESIS, 1, 0
        with self.store._connect() as connection:
            rows = connection.execute("SELECT * FROM governance_ledger_events ORDER BY sequence ASC").fetchall()
        for row in rows:
            event = self._row_to_event(row)
            if event.sequence != expected_sequence:
                return LedgerVerification(False, count, expected_previous, f"Unexpected ledger sequence {event.sequence}.")
            if not hmac.compare_digest(event.previous_hash, expected_previous):
                return LedgerVerification(False, count, expected_previous, f"Previous hash mismatch at sequence {event.sequence}.")
            expected_hash = self._digest(
                self._payload_for_hash(event.sequence, event.id, event.occurred_at, event.action, event.actor,
                                       event.entity_type, event.entity_id, event.details, event.previous_hash)
            )
            if not hmac.compare_digest(event.event_hash, expected_hash):
                return LedgerVerification(False, count, expected_previous, f"Event hash mismatch at sequence {event.sequence}.")
            expected_previous, expected_sequence, count = event.event_hash, expected_sequence + 1, count + 1
        return LedgerVerification(True, count, expected_previous)

    def _digest(self, payload: str) -> str:
        encoded = payload.encode("utf-8")
        if self._integrity_key is None:
            return hashlib.sha256(encoded).hexdigest()
        return hmac.new(self._integrity_key, encoded, hashlib.sha256).hexdigest()

    @staticmethod
    def _payload_for_hash(sequence: int, event_id: str, occurred_at: str, action: str, actor: str,
                          entity_type: str, entity_id: str, details: Mapping[str, Any], previous_hash: str) -> str:
        return _canonical_json({
            "sequence": sequence,
            "id": event_id,
            "occurred_at": occurred_at,
            "action": action,
            "actor": actor,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details,
            "previous_hash": previous_hash,
        })

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> LedgerEvent:
        return LedgerEvent(
            sequence=int(row["sequence"]), id=str(row["id"]), occurred_at=str(row["occurred_at"]),
            action=str(row["action"]), actor=str(row["actor"]), entity_type=str(row["entity_type"]),
            entity_id=str(row["entity_id"]), details=json.loads(row["details"]),
            previous_hash=str(row["previous_hash"]), event_hash=str(row["event_hash"]),
        )


class ApprovalService:
    """Two-person approval control with role coverage and artifact binding."""

    def __init__(self, store: ProjectStore, ledger: IntegrityLedger | None = None) -> None:
        self.store = store
        self.ledger = ledger or IntegrityLedger(store)
        self._initialize()

    def _initialize(self) -> None:
        with self.store._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS governance_approval_requests (
                    id TEXT PRIMARY KEY,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    requester TEXT NOT NULL,
                    classification TEXT NOT NULL CHECK(classification IN ('public','internal','confidential','restricted')),
                    content TEXT NOT NULL,
                    content_fingerprint TEXT NOT NULL,
                    policy_snapshot TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_governance_approval_status
                    ON governance_approval_requests(status, classification, created_at DESC);
                CREATE TABLE IF NOT EXISTS governance_approval_decisions (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    approver TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
                    roles TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    UNIQUE(request_id, approver),
                    FOREIGN KEY(request_id) REFERENCES governance_approval_requests(id) ON DELETE CASCADE
                );
                """
            )

    def submit(self, subject_type: str, subject_id: str, requester: str, classification: Classification,
               content: Mapping[str, Any], policy: ApprovalPolicy) -> ApprovalRequest:
        _validate_identifier(subject_type, "Subject type")
        _validate_identifier(subject_id, "Subject ID")
        _validate_identifier(requester, "Requester")
        if classification not in _ALLOWED_CLASSIFICATIONS:
            raise ReportFlowError("Approval request classification is invalid.")
        policy.validate()
        if classification not in policy.governed_classifications:
            raise ReportFlowError("The selected policy does not govern this classification.")
        safe_content = _safe_json_object(content, "Approval content")
        request_id, now = str(uuid4()), utc_now()
        fingerprint = content_fingerprint(safe_content)
        with self.store._connect() as connection:
            connection.execute(
                """INSERT INTO governance_approval_requests(
                    id,subject_type,subject_id,requester,classification,content,content_fingerprint,policy_snapshot,status,created_at,updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (request_id, subject_type, subject_id, requester, classification, _canonical_json(safe_content), fingerprint,
                 _canonical_json(policy.snapshot()), now, now),
            )
            row = connection.execute("SELECT * FROM governance_approval_requests WHERE id=?", (request_id,)).fetchone()
        request = self._row_to_request(row)
        self.ledger.append("governance.submitted", requester, "approval_request", request.id, {
            "subject_type": subject_type, "subject_id": subject_id, "classification": classification,
            "content_fingerprint": fingerprint, "policy_id": policy.policy_id,
        })
        self.store.audit("governance.submitted", "approval_request", request.id, {
            "subject_type": subject_type, "subject_id": subject_id, "classification": classification,
            "content_fingerprint": fingerprint, "policy_id": policy.policy_id,
        }, actor=requester)
        return request

    def decide(self, request_id: str, approver: str, decision: Decision, *, roles: tuple[str, ...], comment: str = "") -> tuple[ApprovalRequest, ApprovalDecision]:
        _validate_identifier(request_id, "Approval request ID")
        _validate_identifier(approver, "Approver")
        if decision not in {"approved", "rejected"}:
            raise ReportFlowError("Approval decision is invalid.")
        normalized_roles = _normalize_roles(roles)
        clean_comment = _clean_comment(comment)
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM governance_approval_requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise ReportFlowError("Approval request was not found.")
            request = self._row_to_request(row)
            if request.status != "pending":
                raise ReportFlowError("Only pending approval requests can receive a decision.")
            if hmac.compare_digest(approver, request.requester):
                raise ReportFlowError("Requester cannot approve or reject their own request.")
            decision_id, now = str(uuid4()), utc_now()
            try:
                connection.execute(
                    """INSERT INTO governance_approval_decisions(id,request_id,approver,decision,roles,comment,decided_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (decision_id, request_id, approver, decision, _canonical_json(list(normalized_roles)), clean_comment, now),
                )
            except sqlite3.IntegrityError as error:
                raise ReportFlowError("An approver may submit only one decision for a request.") from error
            status: ApprovalStatus = "rejected" if decision == "rejected" else "pending"
            if decision == "approved":
                rows = connection.execute(
                    "SELECT roles FROM governance_approval_decisions WHERE request_id=? AND decision='approved'", (request_id,)
                ).fetchall()
                approved_roles = {role for item in rows for role in json.loads(item["roles"])}
                if len(rows) >= request.policy.minimum_approvals and set(request.policy.required_roles).issubset(approved_roles):
                    status = "approved"
            connection.execute(
                "UPDATE governance_approval_requests SET status=?, updated_at=? WHERE id=?", (status, now, request_id)
            )
            updated_row = connection.execute("SELECT * FROM governance_approval_requests WHERE id=?", (request_id,)).fetchone()
            connection.commit()
        updated = self._row_to_request(updated_row)
        recorded = ApprovalDecision(decision_id, request_id, approver, decision, normalized_roles, clean_comment, now)
        details = {"decision": decision, "roles": list(normalized_roles), "status": updated.status,
                   "content_fingerprint": updated.content_fingerprint}
        self.ledger.append(f"governance.{decision}", approver, "approval_request", request_id, details)
        self.store.audit(f"governance.{decision}", "approval_request", request_id, details, actor=approver)
        return updated, recorded

    def cancel(self, request_id: str, actor: str) -> ApprovalRequest:
        _validate_identifier(request_id, "Approval request ID")
        _validate_identifier(actor, "Cancellation actor")
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM governance_approval_requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise ReportFlowError("Approval request was not found.")
            request = self._row_to_request(row)
            if request.status != "pending" or not hmac.compare_digest(request.requester, actor):
                raise ReportFlowError("Only the requester can cancel a pending approval request.")
            now = utc_now()
            connection.execute("UPDATE governance_approval_requests SET status='cancelled', updated_at=? WHERE id=?", (now, request_id))
            updated_row = connection.execute("SELECT * FROM governance_approval_requests WHERE id=?", (request_id,)).fetchone()
        updated = self._row_to_request(updated_row)
        self.ledger.append("governance.cancelled", actor, "approval_request", request_id, {"content_fingerprint": updated.content_fingerprint})
        self.store.audit("governance.cancelled", "approval_request", request_id, actor=actor)
        return updated

    def authorize_delivery(self, request_id: str, current_content: Mapping[str, Any], *, actor: str = "distribution-worker") -> ApprovalRequest:
        _validate_identifier(request_id, "Approval request ID")
        _validate_identifier(actor, "Authorization actor")
        request = self.get(request_id)
        if request.status != "approved":
            raise ReportFlowError("Distribution is not authorized because the approval request is not approved.")
        observed_fingerprint = content_fingerprint(_safe_json_object(current_content, "Current distribution content"))
        if not hmac.compare_digest(request.content_fingerprint, observed_fingerprint):
            self.ledger.append("governance.authorization_denied", actor, "approval_request", request_id, {
                "expected_fingerprint": request.content_fingerprint, "observed_fingerprint": observed_fingerprint,
            })
            self.store.audit("governance.authorization_denied", "approval_request", request_id, {
                "expected_fingerprint": request.content_fingerprint, "observed_fingerprint": observed_fingerprint,
            }, actor=actor)
            raise ReportFlowError("Distribution content changed after approval and must be approved again.")
        self.ledger.append("governance.delivery_authorized", actor, "approval_request", request_id, {
            "content_fingerprint": observed_fingerprint,
        })
        self.store.audit("governance.delivery_authorized", "approval_request", request_id, {
            "content_fingerprint": observed_fingerprint,
        }, actor=actor)
        return request

    def get(self, request_id: str) -> ApprovalRequest:
        _validate_identifier(request_id, "Approval request ID")
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM governance_approval_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise ReportFlowError("Approval request was not found.")
        return self._row_to_request(row)

    def decisions_for(self, request_id: str) -> list[ApprovalDecision]:
        _validate_identifier(request_id, "Approval request ID")
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM governance_approval_decisions WHERE request_id=? ORDER BY decided_at ASC, id ASC", (request_id,)
            ).fetchall()
        return [ApprovalDecision(str(row["id"]), str(row["request_id"]), str(row["approver"]), str(row["decision"]),
                                 tuple(json.loads(row["roles"])), str(row["comment"]), str(row["decided_at"])) for row in rows]

    def list(self, status: ApprovalStatus | None = None, limit: int = 100) -> list[ApprovalRequest]:
        if not 1 <= limit <= 1_000:
            raise ReportFlowError("Approval list limit must be between 1 and 1000.")
        with self.store._connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM governance_approval_requests ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            elif status in {"pending", "approved", "rejected", "cancelled"}:
                rows = connection.execute(
                    "SELECT * FROM governance_approval_requests WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit)
                ).fetchall()
            else:
                raise ReportFlowError("Approval request status is invalid.")
        return [self._row_to_request(row) for row in rows]

    @staticmethod
    def _row_to_request(row: sqlite3.Row) -> ApprovalRequest:
        return ApprovalRequest(
            id=str(row["id"]), subject_type=str(row["subject_type"]), subject_id=str(row["subject_id"]),
            requester=str(row["requester"]), classification=str(row["classification"]), content=json.loads(row["content"]),
            content_fingerprint=str(row["content_fingerprint"]), policy=ApprovalPolicy.from_snapshot(json.loads(row["policy_snapshot"])),
            status=str(row["status"]), created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
        )


class GovernedDistributionGate:
    """Thin adapter that requires governance authorization before queue enrollment."""

    def __init__(self, approvals: ApprovalService) -> None:
        self.approvals = approvals

    def enqueue_approved(self, queue: "DistributionQueue", request_id: str, *, kind: str, payload: Mapping[str, Any],
                         idempotency_key: str, retry_policy: "RetryPolicy", priority: int = 0,
                         actor: str = "distribution-worker") -> tuple["DistributionJob", bool]:
        self.approvals.authorize_delivery(request_id, payload, actor=actor)
        # DistributionQueue independently validates the payload and rejects credentials.
        return queue.enqueue(kind, dict(payload), idempotency_key, retry_policy=retry_policy, priority=priority, actor=actor)


def content_fingerprint(content: Mapping[str, Any]) -> str:
    """Return the SHA-256 fingerprint of a canonical approval payload."""
    safe_content = _safe_json_object(content, "Approval content")
    return hashlib.sha256(_canonical_json(safe_content).encode("utf-8")).hexdigest()


def _canonical_json(value: Mapping[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _safe_json_object(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReportFlowError(f"{label} must be a JSON object.")
    try:
        copied = json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError) as error:
        raise ReportFlowError(f"{label} must be JSON-serializable without non-finite values.") from error
    if len(_canonical_json(copied).encode("utf-8")) > 64_000:
        raise ReportFlowError(f"{label} exceeds the 64 KiB governance limit.")
    return copied


def _validate_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ReportFlowError(f"{label} is invalid.")


def _normalize_roles(roles: tuple[str, ...]) -> tuple[str, ...]:
    if not roles or len(roles) > 8:
        raise ReportFlowError("Approver must provide between one and eight roles.")
    normalized = tuple(sorted({str(role).strip() for role in roles}))
    if len(normalized) != len(roles) or any(not _SAFE_ROLE.fullmatch(role) for role in normalized):
        raise ReportFlowError("Approver roles are invalid or duplicated.")
    return normalized


def _clean_comment(value: str) -> str:
    if not isinstance(value, str):
        raise ReportFlowError("Approval comment must be text.")
    return value.replace("\x00", "").strip()[:1_000]

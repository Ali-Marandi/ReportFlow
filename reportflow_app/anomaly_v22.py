"""Explainable, deterministic anomaly detection for governed ReportFlow metrics."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import pandas as pd

from reportflow_app.core import ProjectStore, ReportFlowError, utc_now


Severity = Literal["low", "medium", "high"]
ReviewStatus = Literal["open", "acknowledged", "dismissed", "investigating", "resolved"]


@dataclass(frozen=True, slots=True)
class AnomalyPolicy:
    minimum_history: int = 8
    rolling_window: int = 28
    robust_z_threshold: float = 3.5
    minimum_absolute_deviation: float = 0.0

    def validate(self) -> None:
        if not 8 <= self.minimum_history <= self.rolling_window <= 365:
            raise ReportFlowError("Anomaly policy requires 8–365 observations and a valid rolling window.")
        if not 2.0 <= self.robust_z_threshold <= 10.0:
            raise ReportFlowError("Anomaly robust z-score threshold must be between 2.0 and 10.0.")
        if self.minimum_absolute_deviation < 0:
            raise ReportFlowError("Anomaly minimum absolute deviation cannot be negative.")


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    idempotency_key: str
    metric_id: str
    observed_at: str
    observed_value: float
    baseline_median: float
    deviation: float
    robust_z_score: float
    severity: Severity
    direction: Literal["up", "down"]
    explanation: str
    evidence: dict[str, object]
    review_status: ReviewStatus = "open"


@dataclass(frozen=True, slots=True)
class AnomalyReview:
    finding_key: str
    status: ReviewStatus
    rationale: str
    reviewed_by: str
    reviewed_at: str


class RobustAnomalyDetector:
    """Rolling MAD detector designed for transparency, not unsupervised black-box alerts."""

    def detect(
        self,
        metric_id: str,
        series: pd.DataFrame,
        *,
        timestamp_column: str = "timestamp",
        value_column: str = "value",
        policy: AnomalyPolicy = AnomalyPolicy(),
        semantic_version: str = "",
        freshness_status: str = "unknown",
        quality_passed: bool = True,
    ) -> list[AnomalyFinding]:
        policy.validate()
        if not metric_id.strip() or timestamp_column not in series.columns or value_column not in series.columns:
            raise ReportFlowError("Anomaly series needs a metric ID plus timestamp and numeric value columns.")
        frame = series.loc[:, [timestamp_column, value_column]].copy()
        frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], errors="coerce", utc=True)
        frame[value_column] = pd.to_numeric(frame[value_column], errors="coerce")
        if frame.isna().any().any():
            raise ReportFlowError("Anomaly series contains invalid timestamps or non-numeric values.")
        frame = frame.sort_values(timestamp_column, kind="stable").reset_index(drop=True)
        if frame[timestamp_column].duplicated().any():
            raise ReportFlowError("Anomaly series has duplicate timestamps; aggregate at one consistent grain first.")
        findings: list[AnomalyFinding] = []
        for index in range(policy.minimum_history, len(frame)):
            observed = float(frame.at[index, value_column])
            history = frame.loc[max(0, index - policy.rolling_window):index - 1, value_column].astype(float).to_numpy()
            median, mad = float(np.median(history)), float(np.median(np.abs(history - np.median(history))))
            deviation = observed - median
            robust_z = self._robust_z(observed, history, median, mad)
            if abs(deviation) < policy.minimum_absolute_deviation or abs(robust_z) < policy.robust_z_threshold:
                continue
            observed_at = frame.at[index, timestamp_column].to_pydatetime().astimezone(UTC).isoformat()
            direction: Literal["up", "down"] = "up" if deviation > 0 else "down"
            severity = _severity(abs(robust_z), policy.robust_z_threshold)
            key = hashlib.sha256(f"{metric_id}|{observed_at}|{semantic_version}|{observed:.12g}".encode("utf-8")).hexdigest()
            explanation = (
                f"Observed {metric_id} was {observed:.4g}, which is {abs(deviation):.4g} {'above' if direction == 'up' else 'below'} "
                f"the rolling median of {median:.4g} across {len(history)} prior observations (robust z-score {robust_z:.2f})."
            )
            findings.append(AnomalyFinding(
                idempotency_key=key, metric_id=metric_id, observed_at=observed_at, observed_value=observed, baseline_median=median,
                deviation=deviation, robust_z_score=robust_z, severity=severity, direction=direction, explanation=explanation,
                evidence={
                    "algorithm": "rolling_median_mad", "history_count": len(history), "rolling_window": policy.rolling_window,
                    "threshold": policy.robust_z_threshold, "semantic_version": semantic_version, "freshness_status": freshness_status,
                    "quality_passed": quality_passed, "requires_review": True,
                },
            ))
        return findings

    @staticmethod
    def _robust_z(observed: float, history: np.ndarray, median: float, mad: float) -> float:
        if mad > 0:
            return 0.6745 * (observed - median) / mad
        standard_deviation = float(np.std(history, ddof=1)) if len(history) > 1 else 0.0
        if standard_deviation > 0:
            return (observed - median) / standard_deviation
        return 0.0 if observed == median else (float("inf") if observed > median else float("-inf"))


class AnomalyRegistry:
    """Deduplicates findings and records the human decision separately from detection."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        with self.store._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS anomaly_findings (
                    idempotency_key TEXT PRIMARY KEY,
                    metric_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    review_status TEXT NOT NULL CHECK(review_status IN ('open','acknowledged','dismissed','investigating','resolved')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS anomaly_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    finding_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    reviewed_by TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    FOREIGN KEY(finding_key) REFERENCES anomaly_findings(idempotency_key) ON DELETE CASCADE
                );
                """
            )

    def record(self, finding: AnomalyFinding, actor: str = "anomaly-worker") -> bool:
        payload = asdict(finding)
        with self.store._connect() as connection:
            existing = connection.execute("SELECT 1 FROM anomaly_findings WHERE idempotency_key=?", (finding.idempotency_key,)).fetchone()
            if existing:
                return False
            connection.execute(
                """INSERT INTO anomaly_findings(idempotency_key,metric_id,observed_at,payload,review_status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""",
                (finding.idempotency_key, finding.metric_id, finding.observed_at, json.dumps(payload, ensure_ascii=False), finding.review_status, utc_now(), utc_now()),
            )
        self.store.audit("anomaly.detected", "anomaly_finding", finding.idempotency_key, {"metric_id": finding.metric_id, "severity": finding.severity, "direction": finding.direction}, actor)
        return True

    def review(self, finding_key: str, status: ReviewStatus, rationale: str, reviewed_by: str) -> AnomalyReview:
        if status == "open" or not rationale.strip() or not reviewed_by.strip():
            raise ReportFlowError("Anomaly review needs a terminal or active status, rationale, and reviewer.")
        reviewed_at = utc_now()
        with self.store._connect() as connection:
            if connection.execute("SELECT 1 FROM anomaly_findings WHERE idempotency_key=?", (finding_key,)).fetchone() is None:
                raise ReportFlowError("Anomaly finding was not found.")
            connection.execute("UPDATE anomaly_findings SET review_status=?,updated_at=? WHERE idempotency_key=?", (status, reviewed_at, finding_key))
            connection.execute("INSERT INTO anomaly_reviews(finding_key,status,rationale,reviewed_by,reviewed_at) VALUES(?,?,?,?,?)", (finding_key, status, rationale.strip()[:2000], reviewed_by.strip()[:256], reviewed_at))
        review = AnomalyReview(finding_key, status, rationale.strip()[:2000], reviewed_by.strip()[:256], reviewed_at)
        self.store.audit("anomaly.reviewed", "anomaly_finding", finding_key, {"status": status, "reviewer": reviewed_by.strip()})
        return review

    def list_open(self, limit: int = 100) -> list[AnomalyFinding]:
        with self.store._connect() as connection:
            rows = connection.execute("SELECT payload,review_status FROM anomaly_findings WHERE review_status IN ('open','acknowledged','investigating') ORDER BY observed_at DESC LIMIT ?", (limit,)).fetchall()
        return [AnomalyFinding(**{**json.loads(row["payload"]), "review_status": row["review_status"]}) for row in rows]


def _severity(score: float, threshold: float) -> Severity:
    if score >= threshold * 2:
        return "high"
    if score >= threshold * 1.35:
        return "medium"
    return "low"

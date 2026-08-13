"""Versioned semantic contracts and deterministic evidence for ReportFlow v2.1."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd

from reportflow_app.core import ReportFlowError
from reportflow_app.enterprise import DimensionDefinition, MetricDefinition, MetricResult, SemanticEngine, SemanticModel


FilterOperator = Literal["eq", "in", "between", "is_null"]


@dataclass(frozen=True, slots=True)
class SemanticFilter:
    dimension_id: str
    operator: FilterOperator
    value: Any = None


@dataclass(frozen=True, slots=True)
class DataQualityRule:
    id: str
    field: str
    kind: Literal["not_null", "range", "freshness"]
    minimum: float | None = None
    maximum: float | None = None
    max_age_hours: int | None = None


@dataclass(frozen=True, slots=True)
class QualityCheckResult:
    rule_id: str
    status: Literal["passed", "failed", "unknown"]
    detail: str


@dataclass(frozen=True, slots=True)
class SemanticContract:
    model: SemanticModel
    status: Literal["draft", "in_review", "published", "deprecated"]
    grain: str
    quality_rules: tuple[DataQualityRule, ...] = ()
    freshness_field: str | None = None
    freshness_sla_hours: int | None = None
    deprecation_note: str = ""

    def validate(self) -> None:
        if self.status == "published":
            if not self.grain.strip():
                raise ReportFlowError("Published semantic contracts require an explicit business grain.")
            if any(not metric.owner.strip() or not metric.certified for metric in self.model.metrics):
                raise ReportFlowError("Published semantic contracts require an owner and certification for every metric.")
        field_names = {dimension.field for dimension in self.model.dimensions}
        field_names.update(metric.field for metric in self.model.metrics if metric.field)
        for rule in self.quality_rules:
            if not rule.id.strip() or rule.field not in field_names:
                raise ReportFlowError("Semantic quality rules require unique IDs and an approved source field.")
            if rule.kind == "range" and (rule.minimum is None or rule.maximum is None or rule.minimum > rule.maximum):
                raise ReportFlowError("Range quality rules require an ordered minimum and maximum.")
            if rule.kind == "freshness" and (rule.max_age_hours is None or rule.max_age_hours < 1):
                raise ReportFlowError("Freshness rules require a positive maximum age in hours.")


@dataclass(frozen=True, slots=True)
class EvidenceCard:
    metric_id: str
    label: str
    value: float | int
    format_string: str
    filters: list[dict[str, Any]]
    semantic_model_id: str
    semantic_version: str
    owner: str
    certified: bool
    sensitivity: str
    lineage: dict[str, Any]
    quality: list[QualityCheckResult]
    freshness_status: Literal["fresh", "stale", "unknown"]


class SemanticEngineV21:
    """Extends the deterministic v2.0 engine with rich, allowlisted filters and evidence."""

    def __init__(self) -> None:
        self._base = SemanticEngine()

    def evaluate(
        self,
        contract: SemanticContract,
        data: pd.DataFrame,
        metric_ids: list[str],
        filters: list[SemanticFilter] | None = None,
        observed_at: datetime | None = None,
    ) -> tuple[list[MetricResult], list[EvidenceCard]]:
        contract.validate()
        applied = filters or []
        frame = self._apply_filters(contract.model, data, applied)
        base_filters = {item.dimension_id: self._filter_value_for_lineage(item) for item in applied}
        results = self._base.execute(contract.model, frame, metric_ids, {})
        quality = self.run_quality_checks(contract, data, observed_at)
        freshness = self._freshness_status(contract, data, observed_at)
        metrics = {metric.id: metric for metric in contract.model.metrics}
        cards = [
            EvidenceCard(
                metric_id=result.metric_id,
                label=result.metric_label,
                value=result.value,
                format_string=result.format_string,
                filters=[asdict(item) for item in applied],
                semantic_model_id=result.semantic_model_id,
                semantic_version=result.semantic_model_version,
                owner=metrics[result.metric_id].owner,
                certified=metrics[result.metric_id].certified,
                sensitivity=metrics[result.metric_id].sensitivity,
                lineage={**result.lineage, "contract_status": contract.status, "grain": contract.grain, "filter_summary": base_filters},
                quality=quality,
                freshness_status=freshness,
            )
            for result in results
        ]
        return results, cards

    def run_quality_checks(self, contract: SemanticContract, data: pd.DataFrame, observed_at: datetime | None = None) -> list[QualityCheckResult]:
        output: list[QualityCheckResult] = []
        for rule in contract.quality_rules:
            if rule.field not in data.columns:
                output.append(QualityCheckResult(rule.id, "unknown", "Source field is absent from the current dataset."))
                continue
            values = data[rule.field]
            if rule.kind == "not_null":
                missing = int(values.isna().sum())
                output.append(QualityCheckResult(rule.id, "passed" if missing == 0 else "failed", f"null_count={missing}"))
            elif rule.kind == "range":
                numeric = pd.to_numeric(values, errors="coerce")
                outside = int(((numeric < rule.minimum) | (numeric > rule.maximum)).fillna(False).sum())
                output.append(QualityCheckResult(rule.id, "passed" if outside == 0 else "failed", f"outside_range_count={outside}"))
            else:
                output.append(QualityCheckResult(rule.id, "unknown", "Freshness is evaluated from the contract freshness field."))
        return output

    def _apply_filters(self, model: SemanticModel, data: pd.DataFrame, filters: list[SemanticFilter]) -> pd.DataFrame:
        dimensions = {item.id: item for item in model.dimensions}
        frame = data.copy()
        for item in filters:
            dimension = dimensions.get(item.dimension_id)
            if dimension is None or not dimension.filterable:
                raise ReportFlowError("Semantic filter references an unapproved dimension.")
            if dimension.field not in frame.columns:
                raise ReportFlowError("Semantic filter source field is absent from the dataset.")
            column = frame[dimension.field]
            if item.operator == "eq":
                frame = frame.loc[column.astype(str) == str(item.value)]
            elif item.operator == "in":
                if not isinstance(item.value, list) or not item.value or len(item.value) > 100:
                    raise ReportFlowError("The semantic 'in' filter needs 1–100 approved values.")
                frame = frame.loc[column.astype(str).isin({str(value) for value in item.value})]
            elif item.operator == "between":
                if not isinstance(item.value, list) or len(item.value) != 2:
                    raise ReportFlowError("The semantic 'between' filter needs exactly two boundary values.")
                numeric = pd.to_numeric(column, errors="coerce")
                frame = frame.loc[numeric.between(float(item.value[0]), float(item.value[1]), inclusive="both")]
            elif item.operator == "is_null":
                if item.value not in {True, False, None}:
                    raise ReportFlowError("The semantic 'is_null' filter accepts only a boolean value.")
                frame = frame.loc[column.isna() if item.value is not False else column.notna()]
            else:
                raise ReportFlowError("Unsupported semantic filter operator.")
        return frame

    @staticmethod
    def _filter_value_for_lineage(item: SemanticFilter) -> Any:
        return item.value if item.operator == "eq" else {"operator": item.operator, "value": item.value}

    @staticmethod
    def _freshness_status(contract: SemanticContract, data: pd.DataFrame, observed_at: datetime | None) -> Literal["fresh", "stale", "unknown"]:
        if not contract.freshness_field or not contract.freshness_sla_hours or contract.freshness_field not in data.columns:
            return "unknown"
        timestamps = pd.to_datetime(data[contract.freshness_field], errors="coerce", utc=True).dropna()
        if timestamps.empty:
            return "unknown"
        now = observed_at or datetime.now(UTC)
        newest = timestamps.max().to_pydatetime()
        age_hours = (now - newest).total_seconds() / 3600
        return "fresh" if age_hours <= contract.freshness_sla_hours else "stale"

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from reportflow_app.core import ProjectStore, ReportFlowError
from reportflow_app.copilot_v21 import CopilotEvidencePolicy, CopilotNarrativeService
from reportflow_app.enterprise import DimensionDefinition, MetricDefinition, SemanticModel
from reportflow_app.semantic_v21 import DataQualityRule, SemanticContract, SemanticEngineV21, SemanticFilter


def contract() -> SemanticContract:
    model = SemanticModel(
        id="sales-v21", name="Sales", dataset_id="sales-data", version="2.1.0", owner="finance@example.com",
        dimensions=[DimensionDefinition("region", "Region", "Region"), DimensionDefinition("period", "Period", "Period")],
        metrics=[MetricDefinition("revenue", "Revenue", "Revenue", "sum", owner="finance@example.com", certified=True, sensitivity="internal")],
        status="published",
    )
    return SemanticContract(
        model=model, status="published", grain="one sales order", freshness_field="UpdatedAt", freshness_sla_hours=24,
        quality_rules=(DataQualityRule("revenue-present", "Revenue", "not_null"), DataQualityRule("revenue-range", "Revenue", "range", 0, 1_000_000)),
    )


def data() -> pd.DataFrame:
    return pd.DataFrame(
        {"Region": ["East", "East", "West"], "Period": ["Q1", "Q2", "Q1"], "Revenue": [120.0, 80.0, 250.0], "UpdatedAt": ["2026-08-14T08:00:00Z"] * 3}
    )


def test_semantic_v21_evaluates_multi_filter_quality_and_freshness() -> None:
    _, cards = SemanticEngineV21().evaluate(
        contract(), data(), ["revenue"], [SemanticFilter("region", "in", ["East", "West"]), SemanticFilter("period", "eq", "Q1")],
        observed_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
    )
    assert cards[0].value == 370.0
    assert cards[0].freshness_status == "fresh"
    assert all(item.status == "passed" for item in cards[0].quality)
    with pytest.raises(ReportFlowError, match="unapproved"):
        SemanticEngineV21().evaluate(contract(), data(), ["revenue"], [SemanticFilter("unknown", "eq", "x")])


def test_published_contract_requires_certified_owned_metrics() -> None:
    invalid = contract()
    invalid_metric = MetricDefinition("uncertified", "Uncertified", "Revenue", "sum", owner="", certified=False)
    with pytest.raises(ReportFlowError, match="owner and certification"):
        SemanticContract(model=SemanticModel(
            id="bad", name="Bad", dataset_id="d", version="2", owner="o", dimensions=[], metrics=[invalid_metric]
        ), status="published", grain="row").validate()


def test_copilot_v21_rejects_restricted_evidence_and_requires_review_for_stale_freshness(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "reportflow.db")
    service = CopilotNarrativeService(store)
    _, stale_cards = SemanticEngineV21().evaluate(contract(), data(), ["revenue"], observed_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC))
    stale_request = service.prepare("analyst@example.com", "summary", "Summarize revenue", contract(), stale_cards)
    with pytest.raises(ReportFlowError, match="must request review"):
        service.validate_answer(stale_request, {
            "summary": "Revenue is 450.", "evidence": [{"metric_id": "revenue", "statement": "Revenue is 450."}], "drivers": [], "assumptions": [],
            "recommended_actions": [{"action": "Review performance", "rationale_metric_ids": ["revenue"]}], "confidence": "high", "needs_review": False,
        })
    with pytest.raises(ReportFlowError, match="sensitivity"):
        service.prepare("analyst@example.com", "summary", "Summarize revenue", contract(), [replace(stale_cards[0], sensitivity="restricted")])


def test_copilot_v21_validates_grounded_recommendations(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "reportflow.db")
    service = CopilotNarrativeService(store)
    _, cards = SemanticEngineV21().evaluate(contract(), data(), ["revenue"], observed_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC))
    request = service.prepare("analyst@example.com", "summary", "Summarize revenue", contract(), cards, CopilotEvidencePolicy())
    answer = service.validate_answer(request, {
        "summary": "Governed revenue is 450.", "evidence": [{"metric_id": "revenue", "statement": "Revenue is 450."}],
        "drivers": ["East and West Q1 records contribute to the total."], "assumptions": ["The selected data snapshot is complete."],
        "recommended_actions": [{"action": "Review regional performance.", "rationale_metric_ids": ["revenue"]}], "confidence": "medium", "needs_review": False,
    })
    assert answer.recommended_actions[0].rationale_metric_ids == ["revenue"]
    with pytest.raises(ReportFlowError, match="outside"):
        service.validate_answer(request, {
            "summary": "Invalid", "evidence": [{"metric_id": "invented", "statement": "No."}], "drivers": [], "assumptions": [],
            "recommended_actions": [{"action": "No", "rationale_metric_ids": ["revenue"]}], "confidence": "low", "needs_review": True,
        })

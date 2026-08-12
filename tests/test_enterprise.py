from pathlib import Path

import pandas as pd
import pytest

from reportflow_app.core import ProjectStore, ReportDefinition, ReportFlowError
from reportflow_app.enterprise import (
    BurstDefinition,
    BurstRecipient,
    ConnectorProfile,
    CopilotGroundingService,
    DimensionDefinition,
    EnterpriseCatalog,
    MetricDefinition,
    ReportBurstService,
    SecureFolderDestination,
    SemanticEngine,
    SemanticModel,
    validate_connector_profile,
    validate_read_only_query,
)


def sales_model() -> SemanticModel:
    return SemanticModel(
        id="sales_v1",
        name="Sales performance",
        dataset_id="sales_data",
        version="1.0.0",
        owner="finance@example.com",
        dimensions=[DimensionDefinition(id="region", label="Region", field="Region", synonyms=["territory"])],
        metrics=[
            MetricDefinition(id="revenue", label="Net Revenue", field="Revenue", aggregation="sum", certified=True, owner="finance@example.com"),
            MetricDefinition(id="order_count", label="Orders", field=None, aggregation="count", certified=True, owner="finance@example.com"),
        ],
        status="published",
    )


def source_data() -> pd.DataFrame:
    return pd.DataFrame(
        {"Region": ["East", "East", "West"], "Revenue": [120.0, 80.0, 250.0], "Period": ["Q1", "Q2", "Q1"]}
    )


def saved_report(store: ProjectStore, source: Path) -> ReportDefinition:
    source_data().to_csv(source, index=False)
    return store.save_report(
        ReportDefinition(None, "Regional Sales", str(source), "Executive", "Regional Sales Pack", ["Region", "Revenue", "Period"], ["html"], "", "")
    )


def test_semantic_engine_executes_only_governed_metrics_and_filters() -> None:
    model = sales_model()
    results = SemanticEngine().execute(model, source_data(), ["revenue", "order_count"], {"region": "East"})
    assert [item.value for item in results] == [200.0, 2]
    assert all(item.semantic_model_version == "1.0.0" for item in results)
    with pytest.raises(ReportFlowError, match="not allowed"):
        SemanticEngine().execute(model, source_data(), ["revenue"], {"unknown": "East"})


def test_copilot_grounding_requires_governed_metric_citations() -> None:
    model = sales_model()
    results = SemanticEngine().execute(model, source_data(), ["revenue"], {"region": "East"})
    service = CopilotGroundingService()
    request = service.prepare("analyst@example.com", "How did the East region perform?", model, results)
    answer = service.validate_answer(
        request,
        {
            "answer": "East region net revenue is 200.00 based on the governed metric result.",
            "assumptions": ["The selected region filter is East."],
            "cited_metric_ids": ["revenue"],
            "confidence": "high",
            "needs_review": False,
        },
    )
    assert answer.cited_metric_ids == ["revenue"]
    with pytest.raises(ReportFlowError, match="not allowed"):
        service.validate_answer(
            request,
            {"answer": "Unsupported", "assumptions": [], "cited_metric_ids": ["invented"], "confidence": "low", "needs_review": True},
        )


def test_connector_profiles_reject_embedded_secrets_and_mutating_sql() -> None:
    with pytest.raises(ReportFlowError, match="secrets"):
        validate_connector_profile(ConnectorProfile("crm", "CRM", "rest_json", {"url": "https://api.example.com", "token": "never-store-this"}))
    validate_read_only_query("SELECT * FROM sales WHERE region = 'East'")
    with pytest.raises(ReportFlowError, match="read-only"):
        validate_read_only_query("DELETE FROM sales")
    with pytest.raises(ReportFlowError, match="single read-only"):
        validate_read_only_query("SELECT * FROM sales; DROP TABLE sales")


def test_enterprise_catalog_versions_semantic_model_and_audits(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "reportflow.db")
    catalog = EnterpriseCatalog(store)
    saved = catalog.save_semantic_model(sales_model())
    loaded = catalog.get_semantic_model(saved.id)
    assert loaded.metrics[0].label == "Net Revenue"
    assert loaded.dimensions[0].synonyms == ["territory"]
    assert store.list_audit_events()[0]["action"] == "semantic_model.saved"


def test_report_burst_is_dry_run_by_default_and_delivers_per_recipient(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "reportflow.db")
    report = saved_report(store, tmp_path / "sales.csv")
    catalog = EnterpriseCatalog(store)
    definition = BurstDefinition(
        id="regional-burst", name="Regional sales delivery", report_id=report.id or 0, filter_field="Region",
        recipients=[
            BurstRecipient("east-manager", "East Manager", "east@example.com", {"Region": "East"}),
            BurstRecipient("west-manager", "West Manager", "west@example.com", {"Region": "West"}),
        ],
        output_formats=["html"],
    )
    catalog.save_burst_definition(definition)
    service = ReportBurstService(catalog, store, tmp_path / "exports")
    dry_result = service.execute(definition, source_data(), SecureFolderDestination(tmp_path / "delivery"))
    assert dry_result.dry_run is True
    assert [item.status for item in dry_result.deliveries] == ["dry_run", "dry_run"]
    sent_result = service.execute(definition, source_data(), SecureFolderDestination(tmp_path / "delivery"), dry_run=False, approved=True)
    assert [item.status for item in sent_result.deliveries] == ["delivered", "delivered"]
    assert all(Path(item.artifacts[0]).exists() for item in sent_result.deliveries)

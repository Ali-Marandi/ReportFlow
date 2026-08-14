from __future__ import annotations

import pytest

from reportflow_app.core import ProjectStore, ReportDefinition, ReportFlowError
from reportflow_app.enterprise import BurstDefinition, BurstRecipient, DimensionDefinition, MetricDefinition, SemanticModel
from reportflow_app.lineage_v24 import LineageCatalog, lineage_asset_id


@pytest.fixture()
def store(tmp_path):
    return ProjectStore(tmp_path / "reportflow-lineage.db")


@pytest.fixture()
def semantic_model() -> SemanticModel:
    return SemanticModel(
        id="sales-model-v1",
        name="Sales semantic model",
        dataset_id="sales-curated",
        version="1.0.0",
        owner="data-steward",
        dimensions=[DimensionDefinition(id="region", label="Region", field="region", data_type="string")],
        metrics=[MetricDefinition(id="net-revenue", label="Net revenue", field="net_revenue", aggregation="sum", owner="finance-owner", sensitivity="restricted", certified=True)],
        status="published",
    )


@pytest.fixture()
def report() -> ReportDefinition:
    return ReportDefinition(
        id=101,
        name="Executive sales report",
        source_path="C:/approved/sales.csv",
        template="Executive",
        title="Executive sales",
        selected_columns=["region", "net_revenue"],
        formats=["pdf", "xlsx"],
        created_at="2026-08-14T00:00:00+00:00",
        updated_at="2026-08-14T00:00:00+00:00",
    )


def test_semantic_lineage_materializes_end_to_end_impact(store, semantic_model, report):
    catalog = LineageCatalog(store)
    semantic = catalog.register_semantic_model(semantic_model, actor="lineage-worker")
    report_asset = catalog.register_report(report, semantic_model.id, classification="restricted", actor="lineage-worker")
    burst = BurstDefinition(
        id="finance-burst",
        name="Finance restricted delivery",
        report_id=101,
        filter_field="region",
        recipients=[BurstRecipient("north-finance", "North finance", "finance@example.test", {"region": "North"})],
        output_formats=["pdf"],
        destination_kind="s3",
        destination_settings={"destination_id": "finance-archive"},
        approval_required=True,
    )
    burst_asset, destination_asset = catalog.register_burst(burst, classification="restricted", actor="lineage-worker")

    source_field = lineage_asset_id("field", "sales-curated:net_revenue")
    impact = catalog.impact_analysis(source_field, direction="downstream")
    impacted_ids = {item.asset.id for item in impact.paths}
    assert lineage_asset_id("metric", "sales-model-v1:net-revenue") in impacted_ids
    assert semantic.id in impacted_ids
    assert report_asset.id in impacted_ids
    assert burst_asset.id in impacted_ids
    assert destination_asset.id in impacted_ids
    assert impact.affected_by_kind["destination"] == 1
    destination_path = next(item for item in impact.paths if item.asset.id == destination_asset.id)
    assert destination_path.path_asset_ids[0] == source_field
    assert destination_path.path_relations[-1] == "delivers_to"

    upstream = catalog.impact_analysis(destination_asset.id, direction="upstream")
    upstream_ids = {item.asset.id for item in upstream.paths}
    assert source_field in upstream_ids
    assert lineage_asset_id("dataset", "sales-curated") in upstream_ids

    graph = catalog.graph()
    assert len(graph.assets) >= 8
    assert len(graph.edges) >= 7


def test_cycles_and_credentials_are_rejected(store, semantic_model, report):
    catalog = LineageCatalog(store)
    catalog.register_semantic_model(semantic_model)
    catalog.register_report(report, semantic_model.id)
    burst = BurstDefinition(
        id="cycle-burst",
        name="Cycle test",
        report_id=101,
        filter_field="region",
        recipients=[],
        output_formats=["pdf"],
        destination_kind="secure_folder",
    )
    _, destination = catalog.register_burst(burst)
    source_field = lineage_asset_id("field", "sales-curated:net_revenue")

    with pytest.raises(ReportFlowError, match="cycle"):
        catalog.link(destination.id, source_field, "invalid_back_edge")

    with pytest.raises(ReportFlowError, match="credentials"):
        catalog.register_asset("artifact", "unsafe-output", "Unsafe", metadata={"token": "do-not-store"})


def test_impact_analysis_is_bounded_and_kind_filtered(store, semantic_model, report):
    catalog = LineageCatalog(store)
    catalog.register_semantic_model(semantic_model)
    catalog.register_report(report, semantic_model.id)
    source_field = lineage_asset_id("field", "sales-curated:net_revenue")

    metrics_only = catalog.impact_analysis(source_field, kinds=("metric",), max_depth=8)
    assert len(metrics_only.paths) == 1
    assert metrics_only.paths[0].asset.kind == "metric"

    shallow = catalog.impact_analysis(source_field, max_depth=1)
    assert all(item.depth == 1 for item in shallow.paths)

    with pytest.raises(ReportFlowError, match="limits"):
        catalog.impact_analysis(source_field, max_nodes=0)

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from reportflow_app.core import ProjectStore, ReportDefinition, ReportFlowError
from reportflow_app.enterprise import BurstDefinition, BurstRecipient, EnterpriseCatalog, SecureFolderDestination
from reportflow_app.enterprise_v21 import (
    AdvancedConnectorProfile,
    AdvancedReportBurstService,
    BurstPolicy,
    ConnectionPolicy,
    recipients_from_mapping,
)


def source_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Region": ["East", "East", "West"],
            "Period": ["Q1", "Q2", "Q1"],
            "Revenue": [120.0, 80.0, 250.0],
        }
    )


def saved_report(store: ProjectStore, source: Path) -> ReportDefinition:
    source_data().to_csv(source, index=False)
    return store.save_report(
        ReportDefinition(None, "Regional Sales", str(source), "Executive", "Regional Sales Pack", ["Region", "Period", "Revenue"], ["html"], "", "")
    )


def test_database_policy_requires_approved_host_database_and_verified_postgres_tls() -> None:
    policy = ConnectionPolicy(
        allowed_hosts=frozenset({"analytics.example.test"}), allowed_databases=frozenset({"warehouse"}),
    )
    good = AdvancedConnectorProfile(
        "warehouse", "Warehouse", "postgresql",
        {"host": "analytics.example.test", "database": "warehouse", "username": "reportflow", "query": "SELECT * FROM sales", "sslmode": "verify-full"},
        "vault:///reportflow/prod/db#password", policy,
    )
    good.validate()
    with pytest.raises(ReportFlowError, match="sslmode"):
        AdvancedConnectorProfile(
            "warehouse", "Warehouse", "postgresql",
            {"host": "analytics.example.test", "database": "warehouse", "username": "reportflow", "query": "SELECT * FROM sales", "sslmode": "require"},
            "vault:///reportflow/prod/db#password", policy,
        ).validate()
    with pytest.raises(ReportFlowError, match="allowlist"):
        AdvancedConnectorProfile(
            "warehouse", "Warehouse", "postgresql",
            {"host": "other.example.test", "database": "warehouse", "username": "reportflow", "query": "SELECT * FROM sales", "sslmode": "verify-full"},
            "vault:///reportflow/prod/db#password", policy,
        ).validate()


def test_recipient_mapping_is_data_driven_validated_and_deduplicated() -> None:
    policy = BurstPolicy(frozenset({"Region", "Period"}), frozenset({"example.com"}))
    mapping = pd.DataFrame(
        {
            "recipient_id": ["east-q1", "west-q1"],
            "display_name": ["East manager", "West manager"],
            "delivery_address": ["east@example.com", "west@example.com"],
            "Region": ["East", "West"],
            "Period": ["Q1", "Q1"],
        }
    )
    recipients = recipients_from_mapping(mapping, ["Region", "Period"], policy)
    assert recipients[0].filters == {"Region": "East", "Period": "Q1"}
    with pytest.raises(ReportFlowError, match="missing required"):
        recipients_from_mapping(mapping.drop(columns=["Period"]), ["Region", "Period"], policy)
    with pytest.raises(ReportFlowError, match="domain"):
        recipients_from_mapping(mapping.assign(delivery_address=["east@other.test", "west@example.com"]), ["Region", "Period"], policy)


def test_advanced_burst_creates_per_recipient_manifest_with_hashed_artifacts(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "reportflow.db")
    report = saved_report(store, tmp_path / "sales.csv")
    catalog = EnterpriseCatalog(store)
    definition = BurstDefinition(
        id="regional-period", name="Regional period burst", report_id=report.id or 0, filter_field="Region",
        recipients=[
            BurstRecipient("east-q1", "East Q1", "east@example.com", {"Region": "East", "Period": "Q1"}),
            BurstRecipient("west-q1", "West Q1", "west@example.com", {"Region": "West", "Period": "Q1"}),
        ],
        output_formats=["html"],
    )
    policy = BurstPolicy(frozenset({"Region", "Period"}), frozenset({"example.com"}), max_rows_per_recipient=10)
    result, manifest_path = AdvancedReportBurstService(catalog, store, tmp_path / "exports").execute(
        definition, source_data(), SecureFolderDestination(tmp_path / "delivery"), policy, dry_run=False, approved=True,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result.status == "completed"
    assert [item["row_count"] for item in manifest["items"]] == [1, 1]
    assert all(item["artifacts"][0]["sha256"] for item in manifest["items"])
    assert all("@" not in item["recipient_address_sha256"] for item in manifest["items"])


def test_advanced_burst_withholds_empty_recipient_result_by_default(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "reportflow.db")
    report = saved_report(store, tmp_path / "sales.csv")
    catalog = EnterpriseCatalog(store)
    definition = BurstDefinition(
        id="empty-result", name="Empty result", report_id=report.id or 0, filter_field="Region",
        recipients=[BurstRecipient("north", "North", "north@example.com", {"Region": "North", "Period": "Q1"})],
        output_formats=["html"],
    )
    policy = BurstPolicy(frozenset({"Region", "Period"}), frozenset({"example.com"}))
    result, manifest_path = AdvancedReportBurstService(catalog, store, tmp_path / "exports").execute(
        definition, source_data(), SecureFolderDestination(tmp_path / "delivery"), policy,
    )
    assert result.status == "completed_with_errors"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["items"][0]["status"] == "failed"

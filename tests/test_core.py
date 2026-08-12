from pathlib import Path

import pandas as pd

from reportflow_app.core import DataInspector, ProjectStore, ReportDefinition, ReportRenderer, ReportService


def definition(source: Path) -> ReportDefinition:
    return ReportDefinition(
        id=None,
        name="Executive pack",
        source_path=str(source),
        template="Executive",
        title="Executive Performance Report",
        selected_columns=["Period", "Revenue", "Net Profit"],
        formats=["html", "pdf", "xlsx"],
        created_at="",
        updated_at="",
    )


def test_profile_identifies_common_quality_signals() -> None:
    data = pd.DataFrame({"Period": ["Q1", "Q1", "Q2"], "Revenue": [100, 100, None]})
    profile = DataInspector.profile(data)
    assert profile.rows == 3
    assert profile.columns == 2
    assert profile.duplicate_rows == 1
    assert profile.missing_cells == 1
    assert profile.numeric_columns == ["Revenue"]


def test_saved_report_round_trips_selected_fields(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    DataInspector.sample_data().to_csv(source, index=False)
    store = ProjectStore(tmp_path / "reportflow.db")
    saved = store.save_report(definition(source))
    loaded = store.get_report(saved.id or 0)
    assert loaded.name == "Executive pack"
    assert loaded.selected_columns == ["Period", "Revenue", "Net Profit"]
    assert loaded.formats == ["html", "pdf", "xlsx"]
    assert store.list_audit_events()[0]["action"] == "report.created"


def test_service_generates_html_pdf_and_excel(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    DataInspector.sample_data().to_csv(source, index=False)
    store = ProjectStore(tmp_path / "reportflow.db")
    saved = store.save_report(definition(source))
    service = ReportService(store, ReportRenderer(tmp_path / "exports"))
    result = service.execute(saved)
    assert result.status == "completed"
    assert {Path(item).suffix for item in result.artifacts} == {".html", ".pdf", ".xlsx"}
    assert all(Path(item).exists() for item in result.artifacts)
    assert store.list_runs()[0]["status"] == "completed"

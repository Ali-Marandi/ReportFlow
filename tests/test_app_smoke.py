import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def test_desktop_window_loads_with_local_workspace(tmp_path: Path, monkeypatch) -> None:
    import reportflow_app.app as application

    monkeypatch.setattr(application, "APP_DATA", tmp_path / "workspace")
    monkeypatch.setattr(application, "EXPORT_DIRECTORY", tmp_path / "workspace" / "exports")
    monkeypatch.setattr(application, "DATABASE_PATH", tmp_path / "workspace" / "reportflow.db")
    app = QApplication.instance() or QApplication([])
    window = application.ReportFlowWindow()
    assert window.windowTitle() == "ReportFlow Desktop"
    assert window.pages.count() == 5
    window.scheduler.shutdown()
    window.deleteLater()
    app.processEvents()

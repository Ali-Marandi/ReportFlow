from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QAction, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QStackedWidget, QStatusBar, QTableWidget,
    QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget,
)

from reportflow_app.core import (
    APP_NAME, APP_VERSION, CredentialVault, DataInspector, ProjectStore,
    ReportDefinition, ReportFlowError, ReportRenderer, ReportScheduler, ReportService,
)


APP_DATA = Path.home() / ".reportflow"
EXPORT_DIRECTORY = APP_DATA / "exports"
DATABASE_PATH = APP_DATA / "reportflow.db"


class MetricCard(QFrame):
    def __init__(self, title: str, value: str, caption: str, accent: str = "#0F6CBD") -> None:
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        title_label = QLabel(title.upper())
        title_label.setObjectName("metricLabel")
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        caption_label = QLabel(caption)
        caption_label.setObjectName("metricCaption")
        bar = QFrame()
        bar.setFixedHeight(3)
        bar.setStyleSheet(f"background:{accent}; border-radius: 1px;")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        layout.addStretch(1)
        layout.addWidget(bar)


class PageTitle(QWidget):
    def __init__(self, eyebrow: str, title: str, subtitle: str, action: QPushButton | None = None) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 16)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        eyebrow_label = QLabel(eyebrow.upper())
        eyebrow_label.setObjectName("eyebrow")
        headline = QLabel(title)
        headline.setObjectName("pageTitle")
        detail = QLabel(subtitle)
        detail.setObjectName("pageSubtitle")
        detail.setWordWrap(True)
        text_layout.addWidget(eyebrow_label)
        text_layout.addWidget(headline)
        text_layout.addWidget(detail)
        layout.addLayout(text_layout, 1)
        if action:
            action.setObjectName("primaryButton")
            layout.addWidget(action, 0, Qt.AlignmentFlag.AlignBottom)


class ReportFlowWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        APP_DATA.mkdir(parents=True, exist_ok=True)
        self.store = ProjectStore(DATABASE_PATH)
        self.service = ReportService(self.store, ReportRenderer(EXPORT_DIRECTORY))
        self.scheduler = ReportScheduler(self.store, self.service)
        self.scheduler.start()
        self.current_data: pd.DataFrame | None = None
        self.current_report_id: int | None = None
        self.setWindowTitle(f"{APP_NAME} Desktop")
        self.setMinimumSize(1120, 720)
        self.resize(1320, 840)
        self._build_window()
        self._apply_styles()
        self.refresh_all()

    def _build_window(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._create_sidebar())
        self.pages = QStackedWidget()
        self.dashboard_page = self._create_dashboard()
        self.builder_page = self._create_builder()
        self.library_page = self._create_library()
        self.history_page = self._create_history()
        self.governance_page = self._create_governance()
        for page in [self.dashboard_page, self.builder_page, self.library_page, self.history_page, self.governance_page]:
            self.pages.addWidget(page)
        root_layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        status = QStatusBar()
        status.showMessage("Local workspace ready · Credentials stay in the operating-system vault.")
        self.setStatusBar(status)

    def _create_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(252)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 18)
        brand = QLabel("REPORTFLOW")
        brand.setObjectName("brand")
        tagline = QLabel("Enterprise reporting,\nwithout the reporting friction.")
        tagline.setObjectName("brandTagline")
        layout.addWidget(brand)
        layout.addWidget(tagline)
        layout.addSpacing(30)
        self.nav_buttons: list[QPushButton] = []
        for index, (label, caption) in enumerate([
            ("Overview", "Workspace health"), ("Report builder", "Design & deliver"),
            ("Report library", "Reusable definitions"), ("Run history", "Evidence & outputs"),
            ("Governance", "Schedules & vault"),
        ]):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(caption)
            button.clicked.connect(lambda checked=False, page=index: self.navigate(page))
            button.setObjectName("navButton")
            self.nav_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        info = QFrame()
        info.setObjectName("sidebarInfo")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(14, 13, 14, 13)
        title = QLabel("LOCAL-FIRST BY DESIGN")
        title.setObjectName("sidebarInfoTitle")
        body = QLabel("Data remains on this device unless an approved connector is configured.")
        body.setWordWrap(True)
        body.setObjectName("sidebarInfoBody")
        info_layout.addWidget(title)
        info_layout.addWidget(body)
        layout.addWidget(info)
        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("versionLabel")
        layout.addWidget(version)
        self.nav_buttons[0].setChecked(True)
        return sidebar

    def _page_shell(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        return page, layout

    def _create_dashboard(self) -> QWidget:
        page, layout = self._page_shell()
        build_button = QPushButton("Create a report")
        build_button.clicked.connect(lambda: self.navigate(1))
        layout.addWidget(PageTitle("Workspace / Overview", "Confidence in every decision.", "Manage report definitions, validate data quality, and distribute polished outputs from a single local workspace.", build_button))
        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        self.metric_reports = MetricCard("Saved reports", "0", "Reusable, versioned definitions", "#0F6CBD")
        self.metric_runs = MetricCard("Completed runs", "0", "Documented delivery evidence", "#12B886")
        self.metric_success = MetricCard("Success rate", "—", "Across the recent run history", "#7C3AED")
        self.metric_schedules = MetricCard("Active schedules", "0", "Local automated delivery", "#F59E0B")
        for position, card in enumerate([self.metric_reports, self.metric_runs, self.metric_success, self.metric_schedules]):
            cards.addWidget(card, 0, position)
        layout.addLayout(cards)
        content = QSplitter(Qt.Orientation.Horizontal)
        activity_group = QGroupBox("Recent activity")
        activity_layout = QVBoxLayout(activity_group)
        self.dashboard_activity = QTableWidget(0, 4)
        self._configure_table(self.dashboard_activity, ["Report", "Status", "Finished", "Artifacts"])
        activity_layout.addWidget(self.dashboard_activity)
        quality_group = QGroupBox("Enterprise readiness")
        quality_layout = QVBoxLayout(quality_group)
        quality_layout.setSpacing(12)
        checks = [
            ("Data quality preview", "Inspect blank values and duplicate rows before production output."),
            ("Multi-format delivery", "Produce presentation-ready HTML, PDF, and Excel workbooks in one run."),
            ("Governed automation", "Schedule local runs and keep an append-only execution trail."),
            ("Secret isolation", "Credential values are stored separately from report definitions."),
        ]
        for title, detail in checks:
            check = QFrame()
            check.setObjectName("checkCard")
            check_layout = QVBoxLayout(check)
            check_layout.setContentsMargins(14, 12, 14, 12)
            title_label = QLabel("✓  " + title)
            title_label.setObjectName("checkTitle")
            detail_label = QLabel(detail)
            detail_label.setObjectName("checkDetail")
            detail_label.setWordWrap(True)
            check_layout.addWidget(title_label)
            check_layout.addWidget(detail_label)
            quality_layout.addWidget(check)
        quality_layout.addStretch(1)
        content.addWidget(activity_group)
        content.addWidget(quality_group)
        content.setSizes([720, 360])
        layout.addWidget(content, 1)
        return page

    def _create_builder(self) -> QWidget:
        page, layout = self._page_shell()
        layout.addWidget(PageTitle("Studio / Report Builder", "Build once. Deliver everywhere.", "Select a tabular source, validate it immediately, and create a branded report definition for repeatable runs."))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        form_box = QGroupBox("Report definition")
        form = QVBoxLayout(form_box)
        form.setContentsMargins(20, 22, 20, 20)
        self.report_name = QLineEdit()
        self.report_name.setPlaceholderText("e.g. Executive performance pack")
        self.report_title = QLineEdit()
        self.report_title.setPlaceholderText("e.g. Executive Performance Report")
        self.template_choice = QComboBox()
        self.template_choice.addItems(["Executive", "Financial", "Operational", "Client-facing"])
        source_row = QHBoxLayout()
        self.source_path = QLineEdit()
        self.source_path.setPlaceholderText("Choose a CSV or Excel file")
        source_button = QPushButton("Browse")
        source_button.clicked.connect(self.choose_source)
        sample_button = QPushButton("Use sample")
        sample_button.clicked.connect(self.create_sample_source)
        source_row.addWidget(self.source_path, 1)
        source_row.addWidget(source_button)
        source_row.addWidget(sample_button)
        form.addWidget(self._field("Report name", self.report_name))
        form.addWidget(self._field("Output title", self.report_title))
        form.addWidget(self._field("Template", self.template_choice))
        source_container = QWidget()
        source_container.setLayout(source_row)
        form.addWidget(self._field("Source data", source_container))
        form.addWidget(QLabel("Export formats"))
        formats = QHBoxLayout()
        self.export_html = QCheckBox("HTML")
        self.export_pdf = QCheckBox("PDF")
        self.export_excel = QCheckBox("Excel")
        for checkbox in [self.export_html, self.export_pdf, self.export_excel]:
            checkbox.setChecked(True)
            formats.addWidget(checkbox)
        formats.addStretch(1)
        format_container = QWidget()
        format_container.setLayout(formats)
        form.addWidget(format_container)
        form.addWidget(QLabel("Included fields"))
        self.column_list = QListWidget()
        self.column_list.setMinimumHeight(165)
        form.addWidget(self.column_list)
        action_row = QHBoxLayout()
        save_button = QPushButton("Save definition")
        save_button.setObjectName("secondaryButton")
        save_button.clicked.connect(self.save_definition)
        run_button = QPushButton("Generate report")
        run_button.setObjectName("primaryButton")
        run_button.clicked.connect(self.generate_report)
        action_row.addWidget(save_button)
        action_row.addWidget(run_button)
        form.addStretch(1)
        form.addLayout(action_row)
        preview_box = QGroupBox("Data intelligence")
        preview_layout = QVBoxLayout(preview_box)
        self.preview_summary = QLabel("Load a CSV or Excel source to see data-quality indicators, a field inventory, and a preview before any output is generated.")
        self.preview_summary.setObjectName("previewSummary")
        self.preview_summary.setWordWrap(True)
        preview_layout.addWidget(self.preview_summary)
        self.preview_table = QTableWidget(0, 0)
        self.preview_table.setObjectName("previewTable")
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        preview_layout.addWidget(self.preview_table, 1)
        self.quality_notes = QLabel()
        self.quality_notes.setObjectName("qualityNotes")
        self.quality_notes.setWordWrap(True)
        preview_layout.addWidget(self.quality_notes)
        splitter.addWidget(form_box)
        splitter.addWidget(preview_box)
        splitter.setSizes([420, 780])
        layout.addWidget(splitter, 1)
        return page

    def _create_library(self) -> QWidget:
        page, layout = self._page_shell()
        create_button = QPushButton("New report")
        create_button.clicked.connect(self.new_report)
        layout.addWidget(PageTitle("Catalog / Report Library", "Standardize what matters.", "Reusable definitions preserve templates, selected fields, output formats, and a traceable local modification history.", create_button))
        self.library_table = QTableWidget(0, 6)
        self._configure_table(self.library_table, ["Name", "Template", "Formats", "Source", "Updated", "Actions"])
        layout.addWidget(self.library_table, 1)
        return page

    def _create_history(self) -> QWidget:
        page, layout = self._page_shell()
        open_exports = QPushButton("Open exports folder")
        open_exports.clicked.connect(self.open_export_folder)
        layout.addWidget(PageTitle("Evidence / Run History", "A clear record of delivery.", "Every run captures its status, timing, generated artifacts, and error message when a delivery cannot be completed.", open_exports))
        self.history_table = QTableWidget(0, 5)
        self._configure_table(self.history_table, ["Report", "Status", "Finished", "Artifacts", "Message"])
        layout.addWidget(self.history_table, 1)
        return page

    def _create_governance(self) -> QWidget:
        page, layout = self._page_shell()
        layout.addWidget(PageTitle("Control / Governance", "Protect the reporting supply chain.", "Configure local schedules, keep source credentials out of report files, and review the immutable local audit log."))
        upper = QSplitter(Qt.Orientation.Horizontal)
        schedule_group = QGroupBox("Scheduled delivery")
        schedule_layout = QVBoxLayout(schedule_group)
        schedule_copy = QLabel("This release provides local daily scheduling. Enterprise deployments can replace this with a centrally governed worker without changing report definitions.")
        schedule_copy.setWordWrap(True)
        schedule_copy.setObjectName("groupDetail")
        self.schedule_report = QComboBox()
        self.schedule_time = QTimeEdit(QTime.currentTime())
        self.schedule_time.setDisplayFormat("HH:mm")
        schedule_button = QPushButton("Save daily schedule")
        schedule_button.setObjectName("primaryButton")
        schedule_button.clicked.connect(self.save_schedule)
        schedule_layout.addWidget(schedule_copy)
        schedule_layout.addWidget(self._field("Report", self.schedule_report))
        schedule_layout.addWidget(self._field("Local time", self.schedule_time))
        schedule_layout.addWidget(schedule_button)
        schedule_layout.addStretch(1)
        vault_group = QGroupBox("Credential vault")
        vault_layout = QVBoxLayout(vault_group)
        vault_copy = QLabel("Store a source credential under a reference name. Only the reference belongs in a future connector configuration; the secret never enters source code or report records.")
        vault_copy.setWordWrap(True)
        vault_copy.setObjectName("groupDetail")
        self.vault_reference = QLineEdit()
        self.vault_reference.setPlaceholderText("e.g. production-sql-readonly")
        self.vault_secret = QLineEdit()
        self.vault_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.vault_secret.setPlaceholderText("Secret value")
        vault_button = QPushButton("Store in operating-system vault")
        vault_button.setObjectName("secondaryButton")
        vault_button.clicked.connect(self.store_secret)
        vault_layout.addWidget(vault_copy)
        vault_layout.addWidget(self._field("Reference", self.vault_reference))
        vault_layout.addWidget(self._field("Secret", self.vault_secret))
        vault_layout.addWidget(vault_button)
        vault_layout.addStretch(1)
        upper.addWidget(schedule_group)
        upper.addWidget(vault_group)
        audit_group = QGroupBox("Audit trail")
        audit_layout = QVBoxLayout(audit_group)
        self.audit_table = QTableWidget(0, 5)
        self._configure_table(self.audit_table, ["Timestamp", "Actor", "Action", "Entity", "Details"])
        audit_layout.addWidget(self.audit_table)
        upper.addWidget(audit_group)
        upper.setSizes([310, 340, 650])
        layout.addWidget(upper, 1)
        return page

    def _field(self, label: str, widget: QWidget) -> QWidget:
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label_widget = QLabel(label)
        label_widget.setObjectName("fieldLabel")
        layout.addWidget(label_widget)
        layout.addWidget(widget)
        return frame

    def _configure_table(self, table: QTableWidget, headers: list[str]) -> None:
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setShowGrid(False)

    def navigate(self, page: int) -> None:
        self.pages.setCurrentIndex(page)
        for index, button in enumerate(self.nav_buttons):
            button.setChecked(index == page)
        self.refresh_all()

    def choose_source(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, "Choose source data", str(Path.home()), "Data files (*.csv *.xlsx *.xls)")
        if source:
            self.source_path.setText(source)
            self.load_source(source)

    def create_sample_source(self) -> None:
        sample_path = APP_DATA / "sample-performance-data.csv"
        DataInspector.sample_data().to_csv(sample_path, index=False)
        self.source_path.setText(str(sample_path))
        self.load_source(str(sample_path))
        self.statusBar().showMessage("Sample dataset loaded. It is safe to experiment with this local file.", 6000)

    def load_source(self, source: str) -> None:
        try:
            self.current_data = DataInspector.load(source)
            profile = DataInspector.profile(self.current_data)
            self.column_list.clear()
            for column in self.current_data.columns:
                item = QListWidgetItem(str(column))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                self.column_list.addItem(item)
            preview = self.current_data.head(25)
            self.preview_table.setRowCount(len(preview))
            self.preview_table.setColumnCount(len(preview.columns))
            self.preview_table.setHorizontalHeaderLabels([str(column) for column in preview.columns])
            for row_index, row in enumerate(preview.itertuples(index=False, name=None)):
                for column_index, value in enumerate(row):
                    self.preview_table.setItem(row_index, column_index, QTableWidgetItem("" if pd.isna(value) else str(value)))
            self.preview_summary.setText(f"{profile.rows:,} records · {profile.columns} fields · {len(profile.numeric_columns)} numeric measures · {len(profile.categorical_columns)} descriptive fields")
            if profile.warnings:
                self.quality_notes.setText("Quality signals: " + "  •  ".join(profile.warnings))
            else:
                self.quality_notes.setText("Quality signals: no blank cells or duplicate rows were detected in the loaded source.")
            self.statusBar().showMessage("Source loaded and profiled locally.", 4000)
        except ReportFlowError as error:
            self.show_error(str(error))

    def selected_columns(self) -> list[str]:
        return [self.column_list.item(index).text() for index in range(self.column_list.count()) if self.column_list.item(index).checkState() == Qt.CheckState.Checked]

    def build_definition(self) -> ReportDefinition:
        formats: list[str] = []
        if self.export_html.isChecked():
            formats.append("html")
        if self.export_pdf.isChecked():
            formats.append("pdf")
        if self.export_excel.isChecked():
            formats.append("xlsx")
        title = self.report_title.text().strip() or self.report_name.text().strip()
        return ReportDefinition(
            self.current_report_id, self.report_name.text(), self.source_path.text(), self.template_choice.currentText(), title,
            self.selected_columns(), formats, "", "",
        )

    def save_definition(self) -> None:
        try:
            definition = self.store.save_report(self.build_definition())
            self.current_report_id = definition.id
            self.statusBar().showMessage(f"‘{definition.name}’ saved to the report library.", 5000)
            self.refresh_all()
        except ReportFlowError as error:
            self.show_error(str(error))

    def generate_report(self) -> None:
        try:
            definition = self.build_definition()
            if definition.id is None:
                definition = self.store.save_report(definition)
                self.current_report_id = definition.id
            result = self.service.execute(definition)
            self.refresh_all()
            QMessageBox.information(self, "Report generated", f"{result.message}\n\nArtifacts:\n" + "\n".join(result.artifacts))
            self.statusBar().showMessage("Report generated and recorded in the evidence log.", 7000)
        except ReportFlowError as error:
            self.show_error(str(error))

    def new_report(self) -> None:
        self.current_report_id = None
        self.report_name.clear()
        self.report_title.clear()
        self.source_path.clear()
        self.column_list.clear()
        self.preview_table.setRowCount(0)
        self.preview_table.setColumnCount(0)
        self.preview_summary.setText("Load a CSV or Excel source to see data-quality indicators, a field inventory, and a preview before any output is generated.")
        self.quality_notes.clear()
        self.navigate(1)

    def edit_report(self, report_id: int) -> None:
        try:
            report = self.store.get_report(report_id)
            self.current_report_id = report.id
            self.report_name.setText(report.name)
            self.report_title.setText(report.title)
            self.source_path.setText(report.source_path)
            self.template_choice.setCurrentText(report.template)
            self.export_html.setChecked("html" in report.formats)
            self.export_pdf.setChecked("pdf" in report.formats)
            self.export_excel.setChecked("xlsx" in report.formats or "excel" in report.formats)
            self.load_source(report.source_path)
            for index in range(self.column_list.count()):
                item = self.column_list.item(index)
                item.setCheckState(Qt.CheckState.Checked if item.text() in report.selected_columns else Qt.CheckState.Unchecked)
            self.navigate(1)
        except ReportFlowError as error:
            self.show_error(str(error))

    def execute_report(self, report_id: int) -> None:
        try:
            result = self.service.execute(self.store.get_report(report_id))
            self.refresh_all()
            self.statusBar().showMessage(f"{result.message} {len(result.artifacts)} artifact(s) created.", 7000)
        except ReportFlowError as error:
            self.show_error(str(error))

    def delete_report(self, report_id: int) -> None:
        response = QMessageBox.question(self, "Delete report", "Delete this report definition and its associated schedules? Existing output files will remain untouched.")
        if response == QMessageBox.StandardButton.Yes:
            self.store.delete_report(report_id)
            self.refresh_all()

    def save_schedule(self) -> None:
        report_id = self.schedule_report.currentData()
        if report_id is None:
            self.show_error("Create a report definition before configuring its schedule.")
            return
        time = self.schedule_time.time()
        self.store.upsert_schedule(int(report_id), time.hour(), time.minute())
        self.scheduler.reload()
        self.refresh_all()
        self.statusBar().showMessage("Daily schedule saved and loaded into the local automation service.", 6000)

    def store_secret(self) -> None:
        try:
            CredentialVault.set_secret(self.vault_reference.text(), self.vault_secret.text())
            self.store.audit("credential.stored", "credential", self.vault_reference.text(), {"reference": self.vault_reference.text()})
            self.vault_secret.clear()
            self.refresh_all()
            self.statusBar().showMessage("Credential stored in the operating-system vault; only its reference is auditable.", 6000)
        except Exception as error:
            self.show_error(f"The operating-system vault could not store the credential: {error}")

    def open_export_folder(self) -> None:
        import os
        import subprocess
        if sys.platform.startswith("win"):
            os.startfile(EXPORT_DIRECTORY)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(EXPORT_DIRECTORY)], check=False)
        else:
            subprocess.run(["xdg-open", str(EXPORT_DIRECTORY)], check=False)

    def refresh_all(self) -> None:
        reports = self.store.list_reports()
        runs = self.store.list_runs()
        schedules = self.store.list_schedules()
        completed = [run for run in runs if run["status"] == "completed"]
        total = len(runs)
        values = [
            (self.metric_reports, str(len(reports)), "Reusable, versioned definitions"),
            (self.metric_runs, str(len(completed)), "Documented delivery evidence"),
            (self.metric_success, "—" if not total else f"{len(completed) / total * 100:.0f}%", "Across the recent run history"),
            (self.metric_schedules, str(len(schedules)), "Local automated delivery"),
        ]
        for card, value, caption in values:
            card.findChild(QLabel, "metricValue").setText(value)
            card.findChild(QLabel, "metricCaption").setText(caption)
        self._populate_runs(self.dashboard_activity, runs[:8])
        self._populate_runs(self.history_table, runs)
        self._populate_library(reports)
        self._populate_audit()
        self.schedule_report.clear()
        for report in reports:
            self.schedule_report.addItem(report.name, report.id)

    def _populate_runs(self, table: QTableWidget, runs: list) -> None:
        table.setRowCount(len(runs))
        for row_index, run in enumerate(runs):
            name = run["report_name"] or "Ad-hoc report"
            artifacts = ", ".join(Path(path).name for path in json_artifacts(run["artifacts"]))
            values = [name, run["status"].title(), run["finished_at"].replace("T", " ").replace("+00:00", " UTC"), artifacts, run["message"]]
            for column_index, value in enumerate(values[:table.columnCount()]):
                item = QTableWidgetItem(value)
                if column_index == 1:
                    item.setForeground(QColor("#12715B" if run["status"] == "completed" else "#B42318"))
                table.setItem(row_index, column_index, item)

    def _populate_library(self, reports: list[ReportDefinition]) -> None:
        self.library_table.setRowCount(len(reports))
        for row_index, report in enumerate(reports):
            source_name = Path(report.source_path).name
            values = [report.name, report.template, ", ".join(value.upper() for value in report.formats), source_name, report.updated_at.replace("T", " ").replace("+00:00", " UTC")]
            for column_index, value in enumerate(values):
                self.library_table.setItem(row_index, column_index, QTableWidgetItem(value))
            actions = QWidget()
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(0, 0, 0, 0)
            edit = QPushButton("Edit")
            edit.setObjectName("tableButton")
            edit.clicked.connect(lambda checked=False, report_id=report.id: self.edit_report(report_id or 0))
            run = QPushButton("Run")
            run.setObjectName("tableButton")
            run.clicked.connect(lambda checked=False, report_id=report.id: self.execute_report(report_id or 0))
            delete = QPushButton("Delete")
            delete.setObjectName("dangerButton")
            delete.clicked.connect(lambda checked=False, report_id=report.id: self.delete_report(report_id or 0))
            action_layout.addWidget(edit)
            action_layout.addWidget(run)
            action_layout.addWidget(delete)
            self.library_table.setCellWidget(row_index, 5, actions)

    def _populate_audit(self) -> None:
        events = self.store.list_audit_events()
        self.audit_table.setRowCount(len(events))
        for row_index, event in enumerate(events):
            details = event["details"]
            values = [event["timestamp"].replace("T", " ").replace("+00:00", " UTC"), event["actor"], event["action"], f"{event['entity_type']} · {event['entity_id'] or '—'}", details]
            for column_index, value in enumerate(values):
                self.audit_table.setItem(row_index, column_index, QTableWidgetItem(str(value)))

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "ReportFlow", message)
        self.statusBar().showMessage(message, 7000)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.scheduler.shutdown()
        event.accept()

    def _apply_styles(self) -> None:
        self.setStyleSheet("""
            QWidget { font-family: 'Segoe UI', 'Inter', Arial, sans-serif; color: #102A43; font-size: 13px; }
            QMainWindow { background: #F5F7FA; }
            #sidebar { background: #102A43; }
            #brand { color: #FFFFFF; font-size: 19px; font-weight: 800; letter-spacing: 2px; }
            #brandTagline { color: #BFD4EA; font-size: 12px; line-height: 1.35; }
            #navButton { text-align: left; border: 0; padding: 12px 14px; border-radius: 8px; background: transparent; color: #D9E2EC; font-weight: 600; }
            #navButton:hover { background: #243B53; color: #FFFFFF; }
            #navButton:checked { background: #0F6CBD; color: #FFFFFF; }
            #sidebarInfo { background: #243B53; border: 1px solid #334E68; border-radius: 10px; }
            #sidebarInfoTitle { color: #7FDBCA; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
            #sidebarInfoBody { color: #D9E2EC; font-size: 11px; }
            #versionLabel { color: #829AB1; font-size: 11px; padding-top: 10px; }
            #eyebrow { color: #0F6CBD; font-size: 10px; font-weight: 800; letter-spacing: 1.2px; }
            #pageTitle { color: #102A43; font-size: 27px; font-weight: 750; }
            #pageSubtitle { color: #627D98; font-size: 13px; max-width: 760px; }
            #metricCard, QGroupBox { background: #FFFFFF; border: 1px solid #D9E2EC; border-radius: 12px; }
            QGroupBox { font-size: 14px; font-weight: 700; padding: 22px 12px 12px 12px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; color: #102A43; }
            #metricLabel { color: #627D98; font-size: 10px; font-weight: 800; letter-spacing: .8px; }
            #metricValue { color: #102A43; font-size: 27px; font-weight: 750; }
            #metricCaption, #checkDetail, #groupDetail { color: #627D98; font-size: 11px; }
            #checkCard { background: #F8FAFC; border: 1px solid #E5EDF5; border-radius: 9px; }
            #checkTitle { color: #102A43; font-weight: 700; }
            #fieldLabel { color: #486581; font-size: 11px; font-weight: 700; }
            QLineEdit, QComboBox, QListWidget, QTimeEdit { background: #FFFFFF; border: 1px solid #BCCCDC; border-radius: 7px; padding: 8px 10px; min-height: 34px; }
            QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTimeEdit:focus { border: 2px solid #0F6CBD; }
            QListWidget::item { padding: 6px; border-radius: 5px; }
            QListWidget::item:hover { background: #E6F1FB; }
            QPushButton { border: 1px solid #BCCCDC; background: #FFFFFF; color: #243B53; padding: 8px 12px; border-radius: 7px; font-weight: 650; }
            QPushButton:hover { background: #F0F4F8; }
            #primaryButton { background: #0F6CBD; border-color: #0F6CBD; color: #FFFFFF; }
            #primaryButton:hover { background: #0B5AA5; }
            #secondaryButton { background: #E6F1FB; border-color: #A9D2F3; color: #0B5AA5; }
            #tableButton { padding: 4px 7px; font-size: 11px; min-height: 25px; }
            #dangerButton { padding: 4px 7px; font-size: 11px; min-height: 25px; color: #B42318; border-color: #FECACA; }
            QTableWidget { background: #FFFFFF; border: 0; border-radius: 8px; alternate-background-color: #F8FAFC; gridline-color: transparent; }
            QTableWidget::item { padding: 7px; }
            QHeaderView::section { background: #F0F4F8; color: #486581; border: 0; border-bottom: 1px solid #D9E2EC; padding: 9px; font-size: 10px; font-weight: 800; }
            #previewSummary { color: #0B5AA5; background: #E6F1FB; border: 1px solid #B9DCF8; border-radius: 8px; padding: 11px; font-weight: 650; }
            #qualityNotes { color: #486581; background: #F8FAFC; border-radius: 7px; padding: 10px; }
            QCheckBox { spacing: 7px; color: #243B53; }
            QStatusBar { background: #FFFFFF; border-top: 1px solid #D9E2EC; color: #486581; }
        """)


def json_artifacts(value: str) -> list[str]:
    import json
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ReportFlow")
    app.setFont(QFont("Segoe UI", 10))
    window = ReportFlowWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())

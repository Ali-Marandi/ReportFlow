"""Enterprise foundations for ReportFlow v2.0.

This module contains vendor-neutral, testable foundations for governed metrics,
read-only data connectors, AI Copilot grounding, and report bursting. It does
not execute arbitrary SQL or let an LLM access credentials or raw data.
"""
from __future__ import annotations

import json
import shutil
import smtplib
import sqlite3
import ssl
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import pandas as pd

from reportflow_app.core import CredentialVault, ProjectStore, ReportDefinition, ReportFlowError, ReportRenderer, safe_file_stem, utc_now


ALLOWED_AGGREGATIONS = {"sum", "average", "count", "distinct_count", "min", "max"}
ALLOWED_CONNECTOR_KINDS = {"csv", "excel", "sqlite", "postgresql", "sqlserver", "rest_json"}
FORBIDDEN_SQL_TOKENS = {"alter", "attach", "create", "delete", "detach", "drop", "insert", "pragma", "replace", "update", "vacuum"}


@dataclass(slots=True)
class ConnectorProfile:
    id: str
    name: str
    kind: str
    settings: dict[str, Any]
    credential_reference: str | None = None
    owner: str = "local-user"
    classification: str = "internal"
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class DimensionDefinition:
    id: str
    label: str
    field: str
    data_type: str = "string"
    description: str = ""
    synonyms: list[str] = field(default_factory=list)
    filterable: bool = True
    visible_to_copilot: bool = True


@dataclass(slots=True)
class MetricDefinition:
    id: str
    label: str
    field: str | None
    aggregation: str
    description: str = ""
    format_string: str = "#,##0.00"
    owner: str = ""
    sensitivity: str = "internal"
    certified: bool = False
    visible_to_copilot: bool = True
    synonyms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SemanticModel:
    id: str
    name: str
    dataset_id: str
    version: str
    owner: str
    dimensions: list[DimensionDefinition]
    metrics: list[MetricDefinition]
    description: str = ""
    status: str = "draft"
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class MetricResult:
    metric_id: str
    metric_label: str
    value: float | int
    format_string: str
    filters: dict[str, Any]
    semantic_model_id: str
    semantic_model_version: str
    lineage: dict[str, Any]


@dataclass(slots=True)
class CopilotRequest:
    question: str
    semantic_model_id: str
    semantic_model_version: str
    actor: str
    allowed_metric_ids: list[str]
    metric_results: list[MetricResult]
    grounding: dict[str, Any]


@dataclass(slots=True)
class CopilotAnswer:
    answer: str
    assumptions: list[str]
    cited_metric_ids: list[str]
    confidence: str
    needs_review: bool


@dataclass(slots=True)
class BurstRecipient:
    recipient_id: str
    display_name: str
    delivery_address: str
    filters: dict[str, Any]
    enabled: bool = True


@dataclass(slots=True)
class BurstDefinition:
    id: str
    name: str
    report_id: int
    filter_field: str
    recipients: list[BurstRecipient]
    output_formats: list[str]
    destination_kind: str = "secure_folder"
    destination_settings: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = True
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class BurstDeliveryResult:
    recipient_id: str
    recipient_address: str
    status: str
    filters: dict[str, Any]
    artifacts: list[str]
    message: str


@dataclass(slots=True)
class BurstRunResult:
    id: str
    burst_id: str
    status: str
    dry_run: bool
    started_at: str
    finished_at: str
    deliveries: list[BurstDeliveryResult]


class EnterpriseCatalog:
    """Persistence for v2.0 definitions, sharing the v1 audit trail database."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self.database_path = store.database_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS connector_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    settings TEXT NOT NULL,
                    credential_reference TEXT,
                    owner TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS semantic_models (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(name, version)
                );
                CREATE TABLE IF NOT EXISTS burst_definitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    report_id INTEGER NOT NULL,
                    definition TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(report_id) REFERENCES reports(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS burst_runs (
                    id TEXT PRIMARY KEY,
                    burst_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    deliveries TEXT NOT NULL,
                    FOREIGN KEY(burst_id) REFERENCES burst_definitions(id) ON DELETE CASCADE
                );
                """
            )

    def save_connector(self, profile: ConnectorProfile) -> ConnectorProfile:
        profile = validate_connector_profile(profile)
        now = utc_now()
        created_at = profile.created_at or now
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO connector_profiles(id, name, kind, settings, credential_reference, owner, classification, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind, settings=excluded.settings,
                credential_reference=excluded.credential_reference, owner=excluded.owner, classification=excluded.classification,
                enabled=excluded.enabled, updated_at=excluded.updated_at""",
                (profile.id, profile.name, profile.kind, json.dumps(profile.settings, ensure_ascii=False), profile.credential_reference,
                 profile.owner, profile.classification, int(profile.enabled), created_at, now),
            )
        saved = ConnectorProfile(**{**asdict(profile), "created_at": created_at, "updated_at": now})
        self.store.audit("connector.saved", "connector", saved.id, {"kind": saved.kind, "classification": saved.classification})
        return saved

    def get_connector(self, connector_id: str) -> ConnectorProfile:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM connector_profiles WHERE id=?", (connector_id,)).fetchone()
        if row is None:
            raise ReportFlowError("The connector profile does not exist.")
        return ConnectorProfile(
            id=row["id"], name=row["name"], kind=row["kind"], settings=json.loads(row["settings"]),
            credential_reference=row["credential_reference"], owner=row["owner"], classification=row["classification"],
            enabled=bool(row["enabled"]), created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_connectors(self) -> list[ConnectorProfile]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM connector_profiles ORDER BY name").fetchall()
        return [self.get_connector(str(row["id"])) for row in rows]

    def save_semantic_model(self, model: SemanticModel) -> SemanticModel:
        validate_semantic_model(model)
        now = utc_now()
        created_at = model.created_at or now
        payload = asdict(model)
        payload["created_at"] = created_at
        payload["updated_at"] = now
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO semantic_models(id, name, dataset_id, version, owner, definition, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, dataset_id=excluded.dataset_id, version=excluded.version,
                owner=excluded.owner, definition=excluded.definition, status=excluded.status, updated_at=excluded.updated_at""",
                (model.id, model.name, model.dataset_id, model.version, model.owner, json.dumps(payload, ensure_ascii=False), model.status, created_at, now),
            )
        saved = semantic_model_from_payload(payload)
        self.store.audit("semantic_model.saved", "semantic_model", saved.id, {"name": saved.name, "version": saved.version, "status": saved.status})
        return saved

    def get_semantic_model(self, model_id: str) -> SemanticModel:
        with self._connect() as connection:
            row = connection.execute("SELECT definition FROM semantic_models WHERE id=?", (model_id,)).fetchone()
        if row is None:
            raise ReportFlowError("The semantic model does not exist.")
        return semantic_model_from_payload(json.loads(row["definition"]))

    def list_semantic_models(self) -> list[SemanticModel]:
        with self._connect() as connection:
            rows = connection.execute("SELECT definition FROM semantic_models ORDER BY updated_at DESC").fetchall()
        return [semantic_model_from_payload(json.loads(row["definition"])) for row in rows]

    def save_burst_definition(self, definition: BurstDefinition) -> BurstDefinition:
        validate_burst_definition(definition)
        now = utc_now()
        created_at = definition.created_at or now
        payload = asdict(definition)
        payload["created_at"] = created_at
        payload["updated_at"] = now
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO burst_definitions(id, name, report_id, definition, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, report_id=excluded.report_id, definition=excluded.definition,
                enabled=excluded.enabled, updated_at=excluded.updated_at""",
                (definition.id, definition.name, definition.report_id, json.dumps(payload, ensure_ascii=False), int(definition.enabled), created_at, now),
            )
        saved = burst_definition_from_payload(payload)
        self.store.audit("burst_definition.saved", "burst_definition", saved.id, {"report_id": saved.report_id, "recipients": len(saved.recipients)})
        return saved

    def record_burst_run(self, result: BurstRunResult) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO burst_runs(id, burst_id, status, dry_run, started_at, finished_at, deliveries) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (result.id, result.burst_id, result.status, int(result.dry_run), result.started_at, result.finished_at,
                 json.dumps([asdict(item) for item in result.deliveries], ensure_ascii=False)),
            )
        self.store.audit("burst.executed", "burst_definition", result.burst_id, {"run_id": result.id, "status": result.status, "dry_run": result.dry_run, "delivery_count": len(result.deliveries)})


class Connector(Protocol):
    def load(self, profile: ConnectorProfile) -> pd.DataFrame: ...


class ConnectorRegistry:
    """Instantiates trusted, read-only connector implementations by kind."""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {
            "csv": FileConnector("csv"), "excel": FileConnector("excel"), "sqlite": SQLiteConnector(),
            "postgresql": PostgreSQLConnector(), "sqlserver": SQLServerConnector(), "rest_json": RestJsonConnector(),
        }

    def load(self, profile: ConnectorProfile) -> pd.DataFrame:
        profile = validate_connector_profile(profile)
        if not profile.enabled:
            raise ReportFlowError("The selected connector is disabled.")
        connector = self._connectors[profile.kind]
        return connector.load(profile)


class FileConnector:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def load(self, profile: ConnectorProfile) -> pd.DataFrame:
        path = Path(str(profile.settings.get("path", ""))).expanduser()
        if not path.exists() or not path.is_file():
            raise ReportFlowError("The configured file connector path cannot be found.")
        try:
            if self.kind == "csv":
                return pd.read_csv(path)
            return pd.read_excel(path, sheet_name=profile.settings.get("sheet_name", 0))
        except Exception as error:
            raise ReportFlowError(f"Unable to load connector source: {error}") from error


class SQLiteConnector:
    def load(self, profile: ConnectorProfile) -> pd.DataFrame:
        path = Path(str(profile.settings.get("path", ""))).expanduser().resolve()
        query = str(profile.settings.get("query", "")).strip()
        if not path.exists() or path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
            raise ReportFlowError("SQLite connector requires an existing .db, .sqlite, or .sqlite3 file.")
        validate_read_only_query(query)
        try:
            connection = sqlite3.connect(f"file:{urllib.parse.quote(str(path))}?mode=ro", uri=True)
            try:
                return pd.read_sql_query(query, connection)
            finally:
                connection.close()
        except sqlite3.Error as error:
            raise ReportFlowError(f"SQLite connector failed: {error}") from error


class PostgreSQLConnector:
    def load(self, profile: ConnectorProfile) -> pd.DataFrame:
        validate_read_only_query(str(profile.settings.get("query", "")))
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("PostgreSQL support requires the optional 'psycopg[binary]' enterprise dependency.") from error
        secret = require_secret(profile)
        settings = profile.settings
        try:
            with psycopg.connect(
                host=settings["host"], port=int(settings.get("port", 5432)), dbname=settings["database"],
                user=settings["username"], password=secret, connect_timeout=int(settings.get("connect_timeout", 10)),
                sslmode=settings.get("sslmode", "require"), options="-c default_transaction_read_only=on",
            ) as connection:
                return pd.read_sql_query(str(settings["query"]), connection)
        except Exception as error:
            raise ReportFlowError(f"PostgreSQL connector failed: {error}") from error


class SQLServerConnector:
    def load(self, profile: ConnectorProfile) -> pd.DataFrame:
        validate_read_only_query(str(profile.settings.get("query", "")))
        try:
            import pyodbc  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("SQL Server support requires the optional 'pyodbc' enterprise dependency.") from error
        secret = require_secret(profile)
        settings = profile.settings
        driver = settings.get("driver", "ODBC Driver 18 for SQL Server")
        connection_string = (
            f"DRIVER={{{driver}}};SERVER={settings['server']};DATABASE={settings['database']};UID={settings['username']};"
            f"PWD={secret};Encrypt=yes;TrustServerCertificate=no;Connection Timeout={int(settings.get('connect_timeout', 10))};"
        )
        try:
            with pyodbc.connect(connection_string, readonly=True) as connection:
                return pd.read_sql_query(str(settings["query"]), connection)
        except Exception as error:
            raise ReportFlowError(f"SQL Server connector failed: {error}") from error


class RestJsonConnector:
    MAX_RESPONSE_BYTES = 10 * 1024 * 1024

    def load(self, profile: ConnectorProfile) -> pd.DataFrame:
        url = str(profile.settings.get("url", "")).strip()
        parsed = urllib.parse.urlparse(url)
        allowed_hosts = set(profile.settings.get("allowed_hosts", []))
        if parsed.scheme != "https" or not parsed.hostname:
            raise ReportFlowError("REST connectors require an HTTPS endpoint.")
        if not allowed_hosts or parsed.hostname not in allowed_hosts:
            raise ReportFlowError("The REST endpoint is not present in this connector's approved host allowlist.")
        headers = {"Accept": "application/json"}
        if profile.credential_reference:
            headers[str(profile.settings.get("auth_header", "Authorization"))] = str(profile.settings.get("auth_prefix", "Bearer ")) + require_secret(profile)
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=int(profile.settings.get("timeout_seconds", 15))) as response:
                content_type = response.headers.get_content_type()
                if content_type not in {"application/json", "text/json"}:
                    raise ReportFlowError("The REST connector response is not JSON.")
                payload = response.read(self.MAX_RESPONSE_BYTES + 1)
                if len(payload) > self.MAX_RESPONSE_BYTES:
                    raise ReportFlowError("The REST response exceeds the configured 10 MB safety limit.")
        except ReportFlowError:
            raise
        except Exception as error:
            raise ReportFlowError(f"REST connector failed: {error}") from error
        try:
            value = json.loads(payload.decode("utf-8"))
            record_path = str(profile.settings.get("record_path", "")).strip()
            for segment in [part for part in record_path.split(".") if part]:
                value = value[segment]
            if not isinstance(value, list):
                value = [value]
            return pd.json_normalize(value)
        except Exception as error:
            raise ReportFlowError(f"Unable to normalize the REST JSON response: {error}") from error


class SemanticEngine:
    """Executes a strict, deterministic subset of metric calculations."""

    def execute(self, model: SemanticModel, data: pd.DataFrame, metric_ids: list[str], filters: dict[str, Any] | None = None) -> list[MetricResult]:
        validate_semantic_model(model)
        frame = self._apply_filters(model, data.copy(), filters or {})
        metric_index = {metric.id: metric for metric in model.metrics}
        results: list[MetricResult] = []
        for metric_id in metric_ids:
            metric = metric_index.get(metric_id)
            if metric is None:
                raise ReportFlowError(f"Metric '{metric_id}' is not defined by this semantic model.")
            if metric.aggregation == "count":
                value: float | int = int(len(frame))
            else:
                if not metric.field or metric.field not in frame.columns:
                    raise ReportFlowError(f"Metric '{metric.id}' points to a missing source field.")
                series = frame[metric.field]
                if metric.aggregation == "sum":
                    value = float(pd.to_numeric(series, errors="coerce").sum())
                elif metric.aggregation == "average":
                    value = float(pd.to_numeric(series, errors="coerce").mean())
                elif metric.aggregation == "distinct_count":
                    value = int(series.nunique(dropna=True))
                elif metric.aggregation == "min":
                    value = float(pd.to_numeric(series, errors="coerce").min())
                elif metric.aggregation == "max":
                    value = float(pd.to_numeric(series, errors="coerce").max())
                else:  # guarded by validate_semantic_model
                    raise ReportFlowError("Unsupported metric aggregation.")
            results.append(MetricResult(metric.id, metric.label, value, metric.format_string, filters or {}, model.id, model.version, {"dataset_id": model.dataset_id, "field": metric.field, "aggregation": metric.aggregation, "owner": metric.owner, "certified": metric.certified}))
        return results

    def _apply_filters(self, model: SemanticModel, frame: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
        dimensions = {dimension.id: dimension for dimension in model.dimensions}
        for dimension_id, value in filters.items():
            dimension = dimensions.get(dimension_id)
            if dimension is None or not dimension.filterable:
                raise ReportFlowError(f"The filter '{dimension_id}' is not allowed by the semantic model.")
            if dimension.field not in frame.columns:
                raise ReportFlowError(f"The filter field '{dimension.field}' does not exist in the dataset.")
            if isinstance(value, (list, dict, set, tuple)):
                raise ReportFlowError("The v2.0 semantic engine supports only single-value equality filters.")
            frame = frame.loc[frame[dimension.field].astype(str) == str(value)]
        return frame


class CopilotGroundingService:
    """Builds and validates small, policy-safe LLM contexts; no model call occurs here."""

    def prepare(self, actor: str, question: str, model: SemanticModel, results: list[MetricResult]) -> CopilotRequest:
        visible_metrics = {metric.id: metric for metric in model.metrics if metric.visible_to_copilot}
        exposed = [result for result in results if result.metric_id in visible_metrics]
        if not exposed:
            raise ReportFlowError("No Copilot-visible metric result is available for this request.")
        grounding = {
            "semantic_model": {"id": model.id, "version": model.version, "name": model.name},
            "metrics": [
                {"id": item.metric_id, "label": item.metric_label, "value": item.value, "format": item.format_string,
                 "filters": item.filters, "lineage": item.lineage}
                for item in exposed
            ],
            "instructions": [
                "Use only the supplied metric results.",
                "Do not invent numbers, data sources, filters, or business definitions.",
                "Cite metric IDs used in the response.",
                "Mark the response as needing review when evidence is incomplete.",
            ],
        }
        return CopilotRequest(question, model.id, model.version, actor, list(visible_metrics), exposed, grounding)

    def validate_answer(self, request: CopilotRequest, payload: dict[str, Any]) -> CopilotAnswer:
        required = {"answer", "assumptions", "cited_metric_ids", "confidence", "needs_review"}
        if set(payload) != required:
            raise ReportFlowError("Copilot response does not match the required governed response schema.")
        cited = payload["cited_metric_ids"]
        if not isinstance(cited, list) or not cited or any(metric_id not in request.allowed_metric_ids for metric_id in cited):
            raise ReportFlowError("Copilot response cites a metric that is not allowed by the grounded request.")
        if payload["confidence"] not in {"low", "medium", "high"}:
            raise ReportFlowError("Copilot confidence must be low, medium, or high.")
        if not isinstance(payload["needs_review"], bool):
            raise ReportFlowError("Copilot response must specify whether human review is required.")
        if not isinstance(payload["answer"], str) or not isinstance(payload["assumptions"], list):
            raise ReportFlowError("Copilot response has invalid text fields.")
        return CopilotAnswer(payload["answer"], [str(value) for value in payload["assumptions"]], cited, payload["confidence"], payload["needs_review"])


class BurstDestination(Protocol):
    def deliver(self, recipient: BurstRecipient, artifacts: list[Path], dry_run: bool) -> list[str]: ...


class SecureFolderDestination:
    """Writes per-recipient artifacts to a controlled local delivery folder.

    This is safe by default and serves as the testable reference delivery channel.
    """

    def __init__(self, root_directory: Path) -> None:
        self.root_directory = Path(root_directory)

    def deliver(self, recipient: BurstRecipient, artifacts: list[Path], dry_run: bool) -> list[str]:
        if dry_run:
            return [str(path) for path in artifacts]
        destination = self.root_directory / safe_file_stem(recipient.recipient_id)
        destination.mkdir(parents=True, exist_ok=True)
        delivered: list[str] = []
        for artifact in artifacts:
            target = destination / artifact.name
            shutil.copy2(artifact, target)
            delivered.append(str(target))
        return delivered


class SMTPDestination:
    """Optional production adapter. Sending requires explicit approval at execute time."""

    def __init__(self, host: str, port: int, username: str, credential_reference: str, sender: str, use_starttls: bool = True) -> None:
        self.host, self.port, self.username = host, port, username
        self.credential_reference, self.sender, self.use_starttls = credential_reference, sender, use_starttls

    def deliver(self, recipient: BurstRecipient, artifacts: list[Path], dry_run: bool) -> list[str]:
        if dry_run:
            return [str(path) for path in artifacts]
        password = CredentialVault.get_secret(self.credential_reference)
        if not password:
            raise ReportFlowError("The approved SMTP credential cannot be found in the operating-system vault.")
        message = EmailMessage()
        message["From"], message["To"] = self.sender, recipient.delivery_address
        message["Subject"] = f"ReportFlow delivery for {recipient.display_name}"
        message.set_content("Your personalized ReportFlow delivery is attached.")
        for artifact in artifacts:
            message.add_attachment(artifact.read_bytes(), maintype="application", subtype="octet-stream", filename=artifact.name)
        context = ssl.create_default_context()
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            if self.use_starttls:
                smtp.starttls(context=context)
            smtp.login(self.username, password)
            smtp.send_message(message)
        return [str(path) for path in artifacts]


class ReportBurstService:
    MAX_RECIPIENTS_PER_RUN = 1000

    def __init__(self, catalog: EnterpriseCatalog, store: ProjectStore, export_directory: Path) -> None:
        self.catalog, self.store = catalog, store
        self.export_directory = Path(export_directory)

    def execute(self, definition: BurstDefinition, data: pd.DataFrame, destination: BurstDestination, dry_run: bool = True, approved: bool = False) -> BurstRunResult:
        validate_burst_definition(definition)
        if not dry_run and definition.approval_required and not approved:
            raise ReportFlowError("External delivery requires an explicit approval decision.")
        enabled_recipients = [recipient for recipient in definition.recipients if recipient.enabled]
        if len(enabled_recipients) > self.MAX_RECIPIENTS_PER_RUN:
            raise ReportFlowError("The burst recipient limit is exceeded; split the definition into controlled batches.")
        report = self.store.get_report(definition.report_id)
        if definition.filter_field not in data.columns:
            raise ReportFlowError("The burst filter field does not exist in the report data.")
        run_id = str(uuid4())
        started = utc_now()
        deliveries: list[BurstDeliveryResult] = []
        for recipient in enabled_recipients:
            try:
                if definition.filter_field not in recipient.filters:
                    raise ReportFlowError("Recipient mapping does not define the required burst filter.")
                value = recipient.filters[definition.filter_field]
                frame = data.loc[data[definition.filter_field].astype(str) == str(value)].copy()
                recipient_report = ReportDefinition(
                    id=None, name=f"{report.name}-{safe_file_stem(recipient.recipient_id)}", source_path=report.source_path,
                    template=report.template, title=report.title, selected_columns=report.selected_columns,
                    formats=definition.output_formats, created_at="", updated_at="",
                )
                renderer = ReportRenderer(self.export_directory / "bursts" / run_id / safe_file_stem(recipient.recipient_id))
                artifacts = [Path(path) for path in renderer.render(recipient_report, frame)]
                delivered = destination.deliver(recipient, artifacts, dry_run)
                deliveries.append(BurstDeliveryResult(recipient.recipient_id, recipient.delivery_address, "dry_run" if dry_run else "delivered", recipient.filters, delivered, "Personalized artifact generated."))
            except Exception as error:
                deliveries.append(BurstDeliveryResult(recipient.recipient_id, recipient.delivery_address, "failed", recipient.filters, [], str(error)))
        status = "completed" if all(item.status in {"dry_run", "delivered"} for item in deliveries) else "completed_with_errors"
        result = BurstRunResult(run_id, definition.id, status, dry_run, started, utc_now(), deliveries)
        self.catalog.record_burst_run(result)
        return result


def validate_connector_profile(profile: ConnectorProfile) -> ConnectorProfile:
    if profile.kind not in ALLOWED_CONNECTOR_KINDS:
        raise ReportFlowError("Unsupported enterprise connector kind.")
    if not profile.id.strip() or not profile.name.strip():
        raise ReportFlowError("Connector profiles need stable IDs and names.")
    if not isinstance(profile.settings, dict):
        raise ReportFlowError("Connector settings must be a structured object.")
    prohibited = {"password", "token", "secret", "api_key"}
    if prohibited.intersection(profile.settings):
        raise ReportFlowError("Store credentials in the operating-system vault and reference them by name; do not place secrets in connector settings.")
    return profile


def require_secret(profile: ConnectorProfile) -> str:
    if not profile.credential_reference:
        raise ReportFlowError("This connector requires a credential reference stored in the operating-system vault.")
    secret = CredentialVault.get_secret(profile.credential_reference)
    if not secret:
        raise ReportFlowError("The credential reference cannot be resolved by the operating-system vault.")
    return secret


def validate_read_only_query(query: str) -> None:
    normalized = " ".join(query.lower().split())
    if not normalized.startswith(("select ", "with ")) or ";" in normalized:
        raise ReportFlowError("Connectors accept a single read-only SELECT/CTE query only.")
    tokens = set(normalized.replace("(", " ").replace(")", " ").replace(",", " ").split())
    if tokens.intersection(FORBIDDEN_SQL_TOKENS):
        raise ReportFlowError("The query contains a prohibited data-changing SQL keyword.")


def validate_semantic_model(model: SemanticModel) -> None:
    if not model.id.strip() or not model.name.strip() or not model.version.strip() or not model.dataset_id.strip():
        raise ReportFlowError("Semantic models require ID, name, dataset ID, and version.")
    dimension_ids = [dimension.id for dimension in model.dimensions]
    metric_ids = [metric.id for metric in model.metrics]
    if len(dimension_ids) != len(set(dimension_ids)) or len(metric_ids) != len(set(metric_ids)):
        raise ReportFlowError("Semantic dimension and metric IDs must be unique.")
    for metric in model.metrics:
        if metric.aggregation not in ALLOWED_AGGREGATIONS:
            raise ReportFlowError(f"Metric '{metric.id}' uses an unsupported aggregation.")
        if metric.aggregation != "count" and not metric.field:
            raise ReportFlowError(f"Metric '{metric.id}' requires a source field.")


def validate_burst_definition(definition: BurstDefinition) -> None:
    if not definition.id.strip() or not definition.name.strip() or not definition.filter_field.strip():
        raise ReportFlowError("Burst definitions need ID, name, and filter field.")
    if not definition.recipients:
        raise ReportFlowError("A burst definition must have at least one recipient mapping.")
    if not set(definition.output_formats).issubset({"html", "pdf", "xlsx"}) or not definition.output_formats:
        raise ReportFlowError("Burst output formats must contain HTML, PDF, and/or XLSX.")
    addresses = [recipient.delivery_address.strip().lower() for recipient in definition.recipients]
    if any(not value for value in addresses) or len(addresses) != len(set(addresses)):
        raise ReportFlowError("Burst recipients need unique, nonempty delivery addresses.")


def semantic_model_from_payload(payload: dict[str, Any]) -> SemanticModel:
    return SemanticModel(
        id=payload["id"], name=payload["name"], dataset_id=payload["dataset_id"], version=payload["version"], owner=payload["owner"],
        dimensions=[DimensionDefinition(**item) for item in payload.get("dimensions", [])],
        metrics=[MetricDefinition(**item) for item in payload.get("metrics", [])], description=payload.get("description", ""),
        status=payload.get("status", "draft"), created_at=payload.get("created_at", ""), updated_at=payload.get("updated_at", ""),
    )


def burst_definition_from_payload(payload: dict[str, Any]) -> BurstDefinition:
    return BurstDefinition(
        id=payload["id"], name=payload["name"], report_id=int(payload["report_id"]), filter_field=payload["filter_field"],
        recipients=[BurstRecipient(**item) for item in payload.get("recipients", [])], output_formats=list(payload["output_formats"]),
        destination_kind=payload.get("destination_kind", "secure_folder"), destination_settings=payload.get("destination_settings", {}),
        approval_required=bool(payload.get("approval_required", True)), enabled=bool(payload.get("enabled", True)),
        created_at=payload.get("created_at", ""), updated_at=payload.get("updated_at", ""),
    )

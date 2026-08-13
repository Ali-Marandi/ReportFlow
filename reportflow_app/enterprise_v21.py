"""Enterprise v2.1 extensions for governed connectors and report distribution.

The module deliberately keeps database access read-only and bounded. It is not a
query IDE: connector profiles store no credentials, arbitrary hosts are rejected,
and every burst writes a delivery manifest with artifact hashes.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import pandas as pd

from reportflow_app.core import ProjectStore, ReportDefinition, ReportFlowError, ReportRenderer, safe_file_stem, utc_now
from reportflow_app.enterprise import (
    BurstDefinition,
    BurstDestination,
    BurstDeliveryResult,
    BurstRecipient,
    BurstRunResult,
    EnterpriseCatalog,
    require_secret,
    validate_read_only_query,
)
from reportflow_app.secrets import SecretProvider


_DATABASE_KINDS = frozenset({"postgresql", "sqlserver", "mysql", "snowflake", "databricks_sql"})
_EMAIL = re.compile(r"^[^@\s]+@([^@\s]+)$")


@dataclass(frozen=True, slots=True)
class ConnectionPolicy:
    """Network, TLS, query and result constraints for one database connector."""

    allowed_hosts: frozenset[str]
    allowed_databases: frozenset[str]
    allowed_private_cidrs: tuple[str, ...] = ()
    connect_timeout_seconds: int = 10
    statement_timeout_seconds: int = 60
    max_result_rows: int = 250_000
    require_tls: bool = True
    query_tag: str = "ReportFlow-v2.1"

    def validate(self, settings: dict[str, Any]) -> None:
        host = str(settings.get("host", "")).strip().lower()
        database = str(settings.get("database", "")).strip()
        if not host or host not in {item.lower() for item in self.allowed_hosts}:
            raise ReportFlowError("Database connector host is not in the approved policy allowlist.")
        if not database or database not in self.allowed_databases:
            raise ReportFlowError("Database connector database is not in the approved policy allowlist.")
        if any(character in host for character in "/\\@?; "):
            raise ReportFlowError("Database host must be a plain approved hostname or address.")
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return
        if address.is_private or address.is_loopback or address.is_link_local:
            networks = tuple(ipaddress.ip_network(cidr, strict=False) for cidr in self.allowed_private_cidrs)
            if not any(address in network for network in networks):
                raise ReportFlowError("A private database address requires an explicit approved CIDR policy.")

    def bounded_timeout(self, value: object, minimum: int = 1, maximum: int = 600) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ReportFlowError("Database timeout must be an integer.") from error
        return max(minimum, min(maximum, parsed))

    def bound_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        if len(frame) > self.max_result_rows:
            raise ReportFlowError("Database result exceeds the connector policy row limit.")
        return frame


@dataclass(frozen=True, slots=True)
class AdvancedConnectorProfile:
    id: str
    name: str
    kind: str
    settings: dict[str, Any]
    credential_reference: str
    policy: ConnectionPolicy
    owner: str = "local-user"
    classification: str = "internal"

    def validate(self) -> None:
        if self.kind not in _DATABASE_KINDS:
            raise ReportFlowError("Unsupported advanced database connector kind.")
        if not self.id.strip() or not self.name.strip() or not self.credential_reference.strip():
            raise ReportFlowError("Advanced connector requires an ID, name, and secret reference.")
        if {"password", "token", "secret", "api_key"}.intersection(self.settings):
            raise ReportFlowError("Advanced connector settings cannot embed credentials.")
        query = str(self.settings.get("query", ""))
        validate_read_only_query(query)
        self.policy.validate(self.settings)
        if self.policy.require_tls and self.kind == "postgresql" and self.settings.get("sslmode", "verify-full") != "verify-full":
            raise ReportFlowError("PostgreSQL production policy requires sslmode=verify-full.")
        if self.policy.require_tls and self.kind == "sqlserver" and bool(self.settings.get("trust_server_certificate", False)):
            raise ReportFlowError("SQL Server policy forbids TrustServerCertificate in production.")


class AdvancedDatabaseConnector:
    """Loads data through vendor drivers, with policy constraints before any connection."""

    def __init__(self, secret_provider: SecretProvider | None = None) -> None:
        self.secret_provider = secret_provider

    def load(self, profile: AdvancedConnectorProfile) -> pd.DataFrame:
        profile.validate()
        secret = self._resolve_secret(profile.credential_reference)
        handlers = {
            "postgresql": self._load_postgresql,
            "sqlserver": self._load_sqlserver,
            "mysql": self._load_mysql,
            "snowflake": self._load_snowflake,
            "databricks_sql": self._load_databricks,
        }
        return profile.policy.bound_frame(handlers[profile.kind](profile, secret))

    def _resolve_secret(self, reference: str) -> str:
        if self.secret_provider is None:
            raise ReportFlowError("Advanced database connectors require an approved central secret provider.")
        value = self.secret_provider.resolve(reference)
        if not value:
            raise ReportFlowError("The connector secret provider returned an empty credential.")
        return value

    def _load_postgresql(self, profile: AdvancedConnectorProfile, secret: str) -> pd.DataFrame:
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("PostgreSQL connector requires optional dependency psycopg[binary].") from error
        settings, policy = profile.settings, profile.policy
        options = (
            f"-c default_transaction_read_only=on -c statement_timeout={policy.bounded_timeout(settings.get('statement_timeout_seconds', policy.statement_timeout_seconds)) * 1000} "
            f"-c application_name={policy.query_tag}"
        )
        try:
            with psycopg.connect(
                host=settings["host"], port=int(settings.get("port", 5432)), dbname=settings["database"],
                user=settings["username"], password=secret, sslmode="verify-full",
                sslrootcert=settings.get("sslrootcert"), connect_timeout=policy.bounded_timeout(settings.get("connect_timeout_seconds", policy.connect_timeout_seconds)),
                options=options,
            ) as connection:
                return pd.read_sql_query(str(settings["query"]), connection)
        except Exception as error:
            raise ReportFlowError("PostgreSQL connector failed without disclosing connection details.") from error

    def _load_sqlserver(self, profile: AdvancedConnectorProfile, secret: str) -> pd.DataFrame:
        try:
            import pyodbc  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("SQL Server connector requires optional dependency pyodbc.") from error
        settings, policy = profile.settings, profile.policy
        driver = str(settings.get("driver", "ODBC Driver 18 for SQL Server"))
        if not re.fullmatch(r"ODBC Driver (18|19) for SQL Server", driver):
            raise ReportFlowError("SQL Server driver must be a supported ODBC Driver 18 or 19.")
        hostname_in_certificate = str(settings.get("hostname_in_certificate", settings["host"])).strip()
        connection_string = (
            f"DRIVER={{{driver}}};SERVER={settings['host']},{int(settings.get('port', 1433))};DATABASE={settings['database']};"
            f"UID={settings['username']};PWD={secret};Encrypt=Yes;TrustServerCertificate=No;"
            f"HostNameInCertificate={hostname_in_certificate};ApplicationIntent=ReadOnly;"
            f"Connection Timeout={policy.bounded_timeout(settings.get('connect_timeout_seconds', policy.connect_timeout_seconds))};"
        )
        try:
            with pyodbc.connect(connection_string, readonly=True) as connection:
                cursor = connection.cursor()
                cursor.execute(f"SET LOCK_TIMEOUT {policy.bounded_timeout(settings.get('statement_timeout_seconds', policy.statement_timeout_seconds)) * 1000}")
                return pd.read_sql_query(str(settings["query"]), connection)
        except Exception as error:
            raise ReportFlowError("SQL Server connector failed without disclosing connection details.") from error

    def _load_mysql(self, profile: AdvancedConnectorProfile, secret: str) -> pd.DataFrame:
        try:
            import mysql.connector  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("MySQL connector requires optional dependency mysql-connector-python.") from error
        settings, policy = profile.settings, profile.policy
        try:
            connection = mysql.connector.connect(
                host=settings["host"], port=int(settings.get("port", 3306)), database=settings["database"],
                user=settings["username"], password=secret, connection_timeout=policy.bounded_timeout(settings.get("connect_timeout_seconds", policy.connect_timeout_seconds)),
                ssl_verify_cert=True, ssl_ca=settings.get("ssl_ca"),
            )
            try:
                return pd.read_sql_query(str(settings["query"]), connection)
            finally:
                connection.close()
        except Exception as error:
            raise ReportFlowError("MySQL connector failed without disclosing connection details.") from error

    def _load_snowflake(self, profile: AdvancedConnectorProfile, secret: str) -> pd.DataFrame:
        try:
            import snowflake.connector  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("Snowflake connector requires optional dependency snowflake-connector-python.") from error
        settings = profile.settings
        try:
            with snowflake.connector.connect(
                account=settings["host"], user=settings["username"], password=secret, warehouse=settings["warehouse"],
                database=settings["database"], schema=settings["schema"], role=settings.get("role"),
            ) as connection:
                return pd.read_sql_query(str(settings["query"]), connection)
        except Exception as error:
            raise ReportFlowError("Snowflake connector failed without disclosing connection details.") from error

    def _load_databricks(self, profile: AdvancedConnectorProfile, secret: str) -> pd.DataFrame:
        try:
            from databricks import sql  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("Databricks connector requires optional dependency databricks-sql-connector.") from error
        settings = profile.settings
        try:
            with sql.connect(server_hostname=settings["host"], http_path=settings["http_path"], access_token=secret) as connection:
                return pd.read_sql_query(str(settings["query"]), connection)
        except Exception as error:
            raise ReportFlowError("Databricks SQL connector failed without disclosing connection details.") from error


@dataclass(frozen=True, slots=True)
class BurstPolicy:
    allowed_filter_fields: frozenset[str]
    allowed_delivery_domains: frozenset[str] = frozenset()
    max_recipients: int = 1000
    max_rows_per_recipient: int = 250_000
    require_nonempty_result: bool = True

    def validate_recipient(self, recipient: BurstRecipient) -> None:
        match = _EMAIL.fullmatch(recipient.delivery_address.strip().lower())
        if not match:
            raise ReportFlowError("Burst recipient delivery address is not a valid email address.")
        if self.allowed_delivery_domains and match.group(1).lower() not in {item.lower() for item in self.allowed_delivery_domains}:
            raise ReportFlowError("Burst recipient domain is not approved by the delivery policy.")
        if not recipient.filters or not set(recipient.filters).issubset(self.allowed_filter_fields):
            raise ReportFlowError("Burst recipient uses a filter field outside the approved policy.")


@dataclass(frozen=True, slots=True)
class RecipientMappingColumns:
    recipient_id: str = "recipient_id"
    display_name: str = "display_name"
    delivery_address: str = "delivery_address"


def recipients_from_mapping(
    mapping: pd.DataFrame,
    filter_fields: Iterable[str],
    policy: BurstPolicy,
    columns: RecipientMappingColumns = RecipientMappingColumns(),
) -> list[BurstRecipient]:
    """Build stable recipients from a data-driven mapping frame without hidden columns."""
    filters = tuple(filter_fields)
    required = {columns.recipient_id, columns.display_name, columns.delivery_address, *filters}
    missing = required.difference(mapping.columns)
    if missing:
        raise ReportFlowError(f"Recipient mapping is missing required columns: {', '.join(sorted(missing))}.")
    recipients: list[BurstRecipient] = []
    for row in mapping.loc[:, [columns.recipient_id, columns.display_name, columns.delivery_address, *filters]].to_dict("records"):
        recipient = BurstRecipient(
            recipient_id=str(row[columns.recipient_id]).strip(),
            display_name=str(row[columns.display_name]).strip(),
            delivery_address=str(row[columns.delivery_address]).strip(),
            filters={field: row[field] for field in filters},
        )
        if not recipient.recipient_id or not recipient.display_name:
            raise ReportFlowError("Recipient mapping contains an empty recipient ID or display name.")
        policy.validate_recipient(recipient)
        recipients.append(recipient)
    addresses = [item.delivery_address.lower() for item in recipients]
    if len(addresses) != len(set(addresses)):
        raise ReportFlowError("Recipient mapping contains duplicate delivery addresses.")
    if len(recipients) > policy.max_recipients:
        raise ReportFlowError("Recipient mapping exceeds the burst policy recipient limit.")
    return recipients


@dataclass(frozen=True, slots=True)
class DeliveryManifestItem:
    recipient_id: str
    recipient_address_sha256: str
    filters: dict[str, Any]
    row_count: int
    status: str
    artifacts: list[dict[str, str]]
    message: str


@dataclass(frozen=True, slots=True)
class BurstDeliveryManifest:
    run_id: str
    burst_id: str
    dry_run: bool
    started_at: str
    finished_at: str
    definition_sha256: str
    items: list[DeliveryManifestItem]


class AdvancedReportBurstService:
    """Multi-filter, policy-aware burst execution with a local tamper-evident manifest."""

    def __init__(self, catalog: EnterpriseCatalog, store: ProjectStore, export_directory: Path) -> None:
        self.catalog, self.store, self.export_directory = catalog, store, Path(export_directory)

    def execute(
        self,
        definition: BurstDefinition,
        data: pd.DataFrame,
        destination: BurstDestination,
        policy: BurstPolicy,
        *,
        dry_run: bool = True,
        approved: bool = False,
    ) -> tuple[BurstRunResult, Path]:
        if not dry_run and definition.approval_required and not approved:
            raise ReportFlowError("External delivery requires an explicit approval decision.")
        recipients = [item for item in definition.recipients if item.enabled]
        if not recipients:
            raise ReportFlowError("Burst definition has no enabled recipients.")
        if len(recipients) > policy.max_recipients:
            raise ReportFlowError("Burst definition exceeds the recipient policy limit.")
        report = self.store.get_report(definition.report_id)
        run_id, started = str(uuid4()), utc_now()
        root = self.export_directory / "bursts" / run_id
        deliveries: list[BurstDeliveryResult] = []
        manifest_items: list[DeliveryManifestItem] = []
        for recipient in recipients:
            self._validate_and_filter(recipient, data, policy)
            try:
                scoped = self._apply_filters(data, recipient.filters)
                if policy.require_nonempty_result and scoped.empty:
                    raise ReportFlowError("Recipient filter returned no report rows; delivery is withheld by policy.")
                if len(scoped) > policy.max_rows_per_recipient:
                    raise ReportFlowError("Recipient result exceeds the burst policy row limit.")
                recipient_report = ReportDefinition(
                    id=None, name=f"{report.name}-{safe_file_stem(recipient.recipient_id)}", source_path=report.source_path,
                    template=report.template, title=report.title, selected_columns=report.selected_columns,
                    formats=definition.output_formats, created_at="", updated_at="",
                )
                artifact_paths = [Path(value) for value in ReportRenderer(root / safe_file_stem(recipient.recipient_id)).render(recipient_report, scoped)]
                delivered = destination.deliver(recipient, artifact_paths, dry_run)
                status = "dry_run" if dry_run else "delivered"
                message = "Personalized artifact generated with governed recipient filters."
                deliveries.append(BurstDeliveryResult(recipient.recipient_id, recipient.delivery_address, status, recipient.filters, delivered, message))
                manifest_items.append(self._manifest_item(recipient, scoped, status, artifact_paths, message))
            except Exception as error:
                message = str(error)
                deliveries.append(BurstDeliveryResult(recipient.recipient_id, recipient.delivery_address, "failed", recipient.filters, [], message))
                manifest_items.append(self._manifest_item(recipient, pd.DataFrame(), "failed", [], message))
        status = "completed" if all(item.status in {"dry_run", "delivered"} for item in deliveries) else "completed_with_errors"
        finished = utc_now()
        result = BurstRunResult(run_id, definition.id, status, dry_run, started, finished, deliveries)
        self.catalog.record_burst_run(result)
        manifest = BurstDeliveryManifest(run_id, definition.id, dry_run, started, finished, _definition_hash(definition), manifest_items)
        manifest_path = root / "delivery-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
        self.store.audit("burst.manifested", "burst_definition", definition.id, {"run_id": run_id, "manifest_sha256": _file_hash(manifest_path), "status": status, "delivery_count": len(deliveries)})
        return result, manifest_path

    @staticmethod
    def _validate_and_filter(recipient: BurstRecipient, data: pd.DataFrame, policy: BurstPolicy) -> None:
        policy.validate_recipient(recipient)
        if not set(recipient.filters).issubset(data.columns):
            raise ReportFlowError("Burst recipient filter points to a missing data column.")

    @staticmethod
    def _apply_filters(frame: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
        scoped = frame.copy()
        for field, expected in filters.items():
            if isinstance(expected, (list, tuple, set)):
                values = {str(value) for value in expected}
                scoped = scoped.loc[scoped[field].astype(str).isin(values)]
            elif expected is None:
                scoped = scoped.loc[scoped[field].isna()]
            else:
                scoped = scoped.loc[scoped[field].astype(str) == str(expected)]
        return scoped

    @staticmethod
    def _manifest_item(recipient: BurstRecipient, scoped: pd.DataFrame, status: str, artifacts: list[Path], message: str) -> DeliveryManifestItem:
        return DeliveryManifestItem(
            recipient_id=recipient.recipient_id,
            recipient_address_sha256=hashlib.sha256(recipient.delivery_address.strip().lower().encode("utf-8")).hexdigest(),
            filters=recipient.filters,
            row_count=len(scoped),
            status=status,
            artifacts=[{"name": path.name, "sha256": _file_hash(path)} for path in artifacts],
            message=message,
        )


def _definition_hash(definition: BurstDefinition) -> str:
    return hashlib.sha256(json.dumps(asdict(definition), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

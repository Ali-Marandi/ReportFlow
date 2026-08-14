"""Persistent semantic lineage and impact analysis for ReportFlow v2.4.

The graph is intentionally vendor-neutral. It links source datasets and fields to
metrics, dimensions, semantic models, reports, bursts, and delivery destinations.
The model maps cleanly to the Run/Job/Dataset concepts used by OpenLineage while
preserving the governance IDs already used by ReportFlow.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, TYPE_CHECKING
from uuid import uuid4

from reportflow_app.core import ProjectStore, ReportDefinition, ReportFlowError, utc_now
from reportflow_app.enterprise import BurstDefinition, SemanticModel

if TYPE_CHECKING:
    from reportflow_app.semantic_v21 import SemanticContract


AssetKind = Literal[
    "dataset", "field", "metric", "dimension", "semantic_model", "report", "burst", "destination", "artifact"
]
Direction = Literal["downstream", "upstream"]

_ALLOWED_KINDS = {"dataset", "field", "metric", "dimension", "semantic_model", "report", "burst", "destination", "artifact"}
_ALLOWED_CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,191}$")
_SAFE_RELATION = re.compile(r"^[a-z][a-z0-9_:-]{2,63}$")


@dataclass(frozen=True, slots=True)
class LineageAsset:
    id: str
    kind: AssetKind
    display_name: str
    classification: str
    owner: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class LineageEdge:
    id: str
    from_asset_id: str
    to_asset_id: str
    relation: str
    metadata: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class LineagePath:
    asset: LineageAsset
    depth: int
    path_asset_ids: tuple[str, ...]
    path_relations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImpactAnalysis:
    source_asset: LineageAsset
    direction: Direction
    paths: tuple[LineagePath, ...]
    truncated: bool

    @property
    def affected_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.paths:
            counts[item.asset.kind] = counts.get(item.asset.kind, 0) + 1
        return counts


@dataclass(frozen=True, slots=True)
class LineageGraph:
    assets: tuple[LineageAsset, ...]
    edges: tuple[LineageEdge, ...]


class LineageCatalog:
    """SQLite-backed graph with cycle prevention and bounded impact traversal."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self._initialize()

    def _initialize(self) -> None:
        with self.store._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS lineage_assets (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('dataset','field','metric','dimension','semantic_model','report','burst','destination','artifact')),
                    display_name TEXT NOT NULL,
                    classification TEXT NOT NULL CHECK(classification IN ('public','internal','confidential','restricted')),
                    owner TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lineage_edges (
                    id TEXT PRIMARY KEY,
                    from_asset_id TEXT NOT NULL,
                    to_asset_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(from_asset_id, to_asset_id, relation)
                );
                CREATE INDEX IF NOT EXISTS idx_lineage_edges_from ON lineage_edges(from_asset_id);
                CREATE INDEX IF NOT EXISTS idx_lineage_edges_to ON lineage_edges(to_asset_id);
                """
            )

    def register_asset(self, kind: AssetKind, external_id: str, display_name: str, *, classification: str = "internal",
                       owner: str = "unassigned", metadata: Mapping[str, Any] | None = None, actor: str = "local-user") -> LineageAsset:
        if kind not in _ALLOWED_KINDS:
            raise ReportFlowError("Lineage asset kind is invalid.")
        if classification not in _ALLOWED_CLASSIFICATIONS:
            raise ReportFlowError("Lineage asset classification is invalid.")
        if not display_name.strip() or len(display_name.strip()) > 256:
            raise ReportFlowError("Lineage asset display name is required and must be at most 256 characters.")
        _validate_actor(owner, "Lineage asset owner")
        _validate_actor(actor, "Lineage actor")
        asset_id = lineage_asset_id(kind, external_id)
        safe_metadata = _safe_metadata(metadata or {})
        now = utc_now()
        with self.store._connect() as connection:
            connection.execute(
                """INSERT INTO lineage_assets(id,kind,display_name,classification,owner,metadata,created_at,updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,display_name=excluded.display_name,
                    classification=excluded.classification,owner=excluded.owner,metadata=excluded.metadata,updated_at=excluded.updated_at""",
                (asset_id, kind, display_name.strip(), classification, owner, _canonical_json(safe_metadata), now, now),
            )
            row = connection.execute("SELECT * FROM lineage_assets WHERE id=?", (asset_id,)).fetchone()
        asset = self._row_to_asset(row)
        self.store.audit("lineage.asset_registered", "lineage_asset", asset.id, {"kind": asset.kind, "classification": asset.classification}, actor=actor)
        return asset

    def link(self, from_asset_id: str, to_asset_id: str, relation: str, *, metadata: Mapping[str, Any] | None = None,
             actor: str = "local-user") -> LineageEdge:
        _validate_asset_id(from_asset_id)
        _validate_asset_id(to_asset_id)
        _validate_actor(actor, "Lineage actor")
        if from_asset_id == to_asset_id:
            raise ReportFlowError("Lineage self-links are not allowed.")
        if not _SAFE_RELATION.fullmatch(relation):
            raise ReportFlowError("Lineage relation is invalid.")
        safe_metadata = _safe_metadata(metadata or {})
        with self.store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            known = connection.execute(
                "SELECT id FROM lineage_assets WHERE id IN (?, ?)", (from_asset_id, to_asset_id)
            ).fetchall()
            if len(known) != 2:
                raise ReportFlowError("Both lineage assets must be registered before linking.")
            if self._would_create_cycle(connection, from_asset_id, to_asset_id):
                raise ReportFlowError("Lineage link would create a dependency cycle.")
            existing = connection.execute(
                "SELECT * FROM lineage_edges WHERE from_asset_id=? AND to_asset_id=? AND relation=?",
                (from_asset_id, to_asset_id, relation),
            ).fetchone()
            now = utc_now()
            if existing is None:
                edge_id = str(uuid4())
                connection.execute(
                    "INSERT INTO lineage_edges(id,from_asset_id,to_asset_id,relation,metadata,created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (edge_id, from_asset_id, to_asset_id, relation, _canonical_json(safe_metadata), now),
                )
            else:
                edge_id = str(existing["id"])
                connection.execute("UPDATE lineage_edges SET metadata=? WHERE id=?", (_canonical_json(safe_metadata), edge_id))
            row = connection.execute("SELECT * FROM lineage_edges WHERE id=?", (edge_id,)).fetchone()
            connection.commit()
        edge = self._row_to_edge(row)
        self.store.audit("lineage.edge_registered", "lineage_edge", edge.id, {
            "from_asset_id": edge.from_asset_id, "to_asset_id": edge.to_asset_id, "relation": edge.relation,
        }, actor=actor)
        return edge

    def register_semantic_model(self, model: SemanticModel, *, actor: str = "local-user") -> LineageAsset:
        """Materialize dataset-to-semantic-model lineage from an existing semantic model."""
        _validate_actor(actor, "Lineage actor")
        dataset = self.register_asset("dataset", model.dataset_id, model.dataset_id, classification="internal", owner=model.owner,
                                      metadata={"source": "semantic_model", "semantic_model_id": model.id}, actor=actor)
        semantic = self.register_asset("semantic_model", model.id, model.name, classification="internal", owner=model.owner,
                                       metadata={"dataset_id": model.dataset_id, "version": model.version, "status": model.status}, actor=actor)
        for dimension in model.dimensions:
            field = self.register_asset("field", f"{model.dataset_id}:{dimension.field}", dimension.field, classification="internal",
                                        owner=model.owner, metadata={"dataset_id": model.dataset_id, "data_type": dimension.data_type}, actor=actor)
            dimension_asset = self.register_asset("dimension", f"{model.id}:{dimension.id}", dimension.label, classification="internal",
                                                   owner=model.owner, metadata={"field": dimension.field, "filterable": dimension.filterable}, actor=actor)
            self.link(dataset.id, field.id, "contains_field", actor=actor)
            self.link(field.id, dimension_asset.id, "sources_dimension", actor=actor)
            self.link(dimension_asset.id, semantic.id, "defines", actor=actor)
        for metric in model.metrics:
            metric_asset = self.register_asset("metric", f"{model.id}:{metric.id}", metric.label, classification=_normalize_classification(metric.sensitivity),
                                                owner=metric.owner or model.owner, metadata={
                                                    "field": metric.field, "aggregation": metric.aggregation, "certified": metric.certified,
                                                    "format_string": metric.format_string,
                                                }, actor=actor)
            if metric.field:
                field = self.register_asset("field", f"{model.dataset_id}:{metric.field}", metric.field, classification=_normalize_classification(metric.sensitivity),
                                            owner=model.owner, metadata={"dataset_id": model.dataset_id}, actor=actor)
                self.link(dataset.id, field.id, "contains_field", actor=actor)
                self.link(field.id, metric_asset.id, "sources_metric", actor=actor)
            self.link(metric_asset.id, semantic.id, "defines", actor=actor)
        return semantic

    def register_semantic_contract(self, contract: "SemanticContract", *, actor: str = "local-user") -> LineageAsset:
        """Register a v2.1 contract while preserving contract-specific governance metadata."""
        semantic = self.register_semantic_model(contract.model, actor=actor)
        return self.register_asset("semantic_model", contract.model.id, contract.model.name, classification="internal", owner=contract.model.owner,
                                   metadata={
                                       "dataset_id": contract.model.dataset_id, "version": contract.model.version,
                                       "status": contract.status, "grain": contract.grain,
                                       "quality_rule_count": len(contract.quality_rules), "freshness_sla_hours": contract.freshness_sla_hours,
                                   }, actor=actor)

    def register_report(self, report: ReportDefinition, semantic_model_id: str, *, classification: str = "internal",
                        actor: str = "local-user") -> LineageAsset:
        if report.id is None:
            raise ReportFlowError("A persisted report ID is required for lineage registration.")
        _validate_actor(actor, "Lineage actor")
        semantic_id = lineage_asset_id("semantic_model", semantic_model_id)
        self.get_asset(semantic_id)
        report_asset = self.register_asset("report", str(report.id), report.title or report.name, classification=classification, owner=actor,
                                           metadata={"report_name": report.name, "formats": report.formats, "selected_columns": report.selected_columns}, actor=actor)
        self.link(semantic_id, report_asset.id, "powers_report", actor=actor)
        return report_asset

    def register_burst(self, burst: BurstDefinition, *, classification: str = "internal", actor: str = "local-user") -> tuple[LineageAsset, LineageAsset]:
        _validate_actor(actor, "Lineage actor")
        report_id = lineage_asset_id("report", str(burst.report_id))
        self.get_asset(report_id)
        burst_asset = self.register_asset("burst", burst.id, burst.name, classification=classification, owner=actor,
                                          metadata={"report_id": burst.report_id, "recipient_count": len(burst.recipients),
                                                    "output_formats": burst.output_formats, "approval_required": burst.approval_required}, actor=actor)
        destination_external_id = str(burst.destination_settings.get("destination_id") or f"{burst.destination_kind}:{burst.id}")
        destination = self.register_asset("destination", destination_external_id, burst.destination_kind, classification=classification, owner=actor,
                                          metadata={"destination_kind": burst.destination_kind}, actor=actor)
        self.link(report_id, burst_asset.id, "parameterizes_burst", actor=actor)
        self.link(burst_asset.id, destination.id, "delivers_to", actor=actor)
        return burst_asset, destination

    def get_asset(self, asset_id: str) -> LineageAsset:
        _validate_asset_id(asset_id)
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM lineage_assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise ReportFlowError("Lineage asset was not found.")
        return self._row_to_asset(row)

    def graph(self, limit: int = 5_000) -> LineageGraph:
        if not 1 <= limit <= 20_000:
            raise ReportFlowError("Lineage graph limit must be between 1 and 20000.")
        with self.store._connect() as connection:
            assets = connection.execute("SELECT * FROM lineage_assets ORDER BY kind, display_name LIMIT ?", (limit,)).fetchall()
            edges = connection.execute("SELECT * FROM lineage_edges ORDER BY created_at, id LIMIT ?", (limit,)).fetchall()
        return LineageGraph(tuple(self._row_to_asset(row) for row in assets), tuple(self._row_to_edge(row) for row in edges))

    def impact_analysis(self, asset_id: str, *, direction: Direction = "downstream", max_depth: int = 8,
                        max_nodes: int = 1_000, kinds: Iterable[AssetKind] | None = None) -> ImpactAnalysis:
        _validate_asset_id(asset_id)
        if direction not in {"downstream", "upstream"}:
            raise ReportFlowError("Lineage analysis direction is invalid.")
        if not 1 <= max_depth <= 16 or not 1 <= max_nodes <= 5_000:
            raise ReportFlowError("Lineage analysis limits are out of range.")
        source = self.get_asset(asset_id)
        requested_kinds = set(kinds or _ALLOWED_KINDS)
        if not requested_kinds.issubset(_ALLOWED_KINDS):
            raise ReportFlowError("Lineage analysis kind filter is invalid.")
        paths, visited, queue = [], {asset_id}, deque([(asset_id, 0, (asset_id,), ())])
        truncated = False
        with self.store._connect() as connection:
            while queue:
                current_id, depth, asset_path, relation_path = queue.popleft()
                if depth >= max_depth:
                    continue
                if direction == "downstream":
                    rows = connection.execute(
                        "SELECT * FROM lineage_edges WHERE from_asset_id=? ORDER BY relation, id", (current_id,)
                    ).fetchall()
                    next_column = "to_asset_id"
                else:
                    rows = connection.execute(
                        "SELECT * FROM lineage_edges WHERE to_asset_id=? ORDER BY relation, id", (current_id,)
                    ).fetchall()
                    next_column = "from_asset_id"
                for row in rows:
                    edge = self._row_to_edge(row)
                    next_id = str(row[next_column])
                    if next_id in visited:
                        continue
                    visited.add(next_id)
                    asset_row = connection.execute("SELECT * FROM lineage_assets WHERE id=?", (next_id,)).fetchone()
                    if asset_row is None:
                        continue
                    asset = self._row_to_asset(asset_row)
                    next_path = asset_path + (next_id,)
                    next_relations = relation_path + (edge.relation,)
                    if asset.kind in requested_kinds:
                        paths.append(LineagePath(asset, depth + 1, next_path, next_relations))
                    if len(visited) >= max_nodes:
                        truncated = True
                        queue.clear()
                        break
                    queue.append((next_id, depth + 1, next_path, next_relations))
        return ImpactAnalysis(source, direction, tuple(paths), truncated)

    def _would_create_cycle(self, connection: sqlite3.Connection, from_asset_id: str, to_asset_id: str) -> bool:
        rows = connection.execute(
            """WITH RECURSIVE reachable(id) AS (
                SELECT to_asset_id FROM lineage_edges WHERE from_asset_id=?
                UNION
                SELECT edge.to_asset_id FROM lineage_edges edge JOIN reachable ON edge.from_asset_id=reachable.id
            ) SELECT 1 FROM reachable WHERE id=? LIMIT 1""",
            (to_asset_id, from_asset_id),
        ).fetchone()
        return rows is not None

    @staticmethod
    def _row_to_asset(row: sqlite3.Row) -> LineageAsset:
        return LineageAsset(
            id=str(row["id"]), kind=str(row["kind"]), display_name=str(row["display_name"]),
            classification=str(row["classification"]), owner=str(row["owner"]), metadata=json.loads(row["metadata"]),
            created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> LineageEdge:
        return LineageEdge(
            id=str(row["id"]), from_asset_id=str(row["from_asset_id"]), to_asset_id=str(row["to_asset_id"]),
            relation=str(row["relation"]), metadata=json.loads(row["metadata"]), created_at=str(row["created_at"]),
        )


def lineage_asset_id(kind: AssetKind, external_id: str) -> str:
    """Create a deterministic, opaque-safe graph ID without exposing provider connection details."""
    if kind not in _ALLOWED_KINDS:
        raise ReportFlowError("Lineage asset kind is invalid.")
    if not isinstance(external_id, str) or not external_id.strip() or len(external_id) > 1_024:
        raise ReportFlowError("Lineage external ID is invalid.")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", external_id.strip()).strip(".-")[:120] or "asset"
    digest = hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{slug}-{digest}"


def _normalize_classification(value: str) -> str:
    return value if value in _ALLOWED_CLASSIFICATIONS else "internal"


def _validate_asset_id(value: str) -> None:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ReportFlowError("Lineage asset ID is invalid.")


def _validate_actor(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ReportFlowError(f"{label} is invalid.")


def _safe_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReportFlowError("Lineage metadata must be a JSON object.")
    try:
        copied = json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError) as error:
        raise ReportFlowError("Lineage metadata must be JSON-serializable without non-finite values.") from error
    if len(_canonical_json(copied).encode("utf-8")) > 64_000:
        raise ReportFlowError("Lineage metadata exceeds the 64 KiB limit.")
    forbidden = {"password", "secret", "token", "access_key", "private_key"}
    if any(str(key).lower() in forbidden for key in _walk_keys(copied)):
        raise ReportFlowError("Lineage metadata cannot contain credentials.")
    return copied


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _canonical_json(value: Mapping[str, Any] | dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

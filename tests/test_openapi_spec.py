from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_scim_openapi_contract_is_parseable_and_versioned() -> None:
    path = ROOT / "docs" / "openapi" / "scim-control-plane-v2.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["openapi"].startswith("3.")
    assert document["info"]["version"] == "2.0.0"
    assert "/Users" in document["paths"]
    assert "/Users/{id}" in document["paths"]
    assert "/Groups" in document["paths"]
    assert document["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"

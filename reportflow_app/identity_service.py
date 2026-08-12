"""Optional FastAPI adapter for the ReportFlow SCIM control plane.

Deploy this module only as a server-side enterprise service behind TLS, an API
gateway and a protected network boundary. It is deliberately not started by the
desktop executable.
"""
from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from reportflow_app.core import ReportFlowError
from reportflow_app.identity import SCIMProvisioningService


def create_scim_app(service: SCIMProvisioningService, bearer_token_loader: Callable[[], str]):
    """Create a minimal, SCIM 2.0-compatible control-plane API.

    `bearer_token_loader` must resolve a short-lived or centrally managed token
    from a secret provider at request time; it must not return a literal coded
    into a workflow, configuration file, or packaged executable.
    """
    try:
        from fastapi import FastAPI, Header, HTTPException, Query, Request
        from fastapi.responses import JSONResponse
    except ImportError as error:
        raise ReportFlowError("SCIM control plane requires the optional fastapi and uvicorn enterprise dependencies.") from error

    app = FastAPI(title="ReportFlow SCIM Control Plane", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ReportFlowError)
    async def reportflow_error(_: Request, error: ReportFlowError):
        return JSONResponse(status_code=400, content=_scim_error(str(error), "invalidValue"))

    def authorize(authorization: str | None) -> None:
        token = bearer_token_loader()
        expected = f"Bearer {token}" if token else ""
        if not authorization or not expected or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/scim/v2/ServiceProviderConfig")
    def service_provider_config(authorization: str | None = Header(default=None)):
        authorize(authorization)
        return service.service_provider_config()

    @app.get("/scim/v2/Users")
    def list_users(startIndex: int = Query(default=1, ge=1), count: int = Query(default=100, ge=1, le=100), authorization: str | None = Header(default=None)):
        authorize(authorization)
        users, total = service.identity_store.list_users(startIndex, count)
        return service.to_list_response(users, total, startIndex)

    @app.get("/scim/v2/Users/{scim_id}")
    def get_user(scim_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return service.to_scim_user(service.identity_store.get_user(scim_id))
        except ReportFlowError as error:
            return JSONResponse(status_code=404, content=_scim_error(str(error), "noTarget"))

    @app.post("/scim/v2/Users", status_code=201)
    def upsert_user(payload: dict[str, Any], authorization: str | None = Header(default=None)):
        authorize(authorization)
        return service.upsert_user_resource(payload)

    @app.patch("/scim/v2/Users/{scim_id}")
    def patch_user(scim_id: str, payload: dict[str, Any], authorization: str | None = Header(default=None)):
        authorize(authorization)
        return service.patch_user_resource(scim_id, payload)

    @app.post("/scim/v2/Groups", status_code=201)
    def upsert_group(payload: dict[str, Any], authorization: str | None = Header(default=None)):
        authorize(authorization)
        return service.upsert_group_resource(payload)

    return app


def _scim_error(detail: str, scim_type: str) -> dict[str, Any]:
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"], "status": "400", "scimType": scim_type, "detail": detail}

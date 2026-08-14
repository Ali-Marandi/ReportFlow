"""Optional HTTPS-only server adapter for the v2.2 embedded portal."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from reportflow_app.core import ReportFlowError
from reportflow_app.portal_v22 import PortalSessionService


# Returns a principal subject plus verified tenant memberships after OIDC validation.
AuthenticatedPrincipalLoader = Callable[[str | None], tuple[str, set[str]]]


def create_portal_app(service: PortalSessionService, principal_loader: AuthenticatedPrincipalLoader):
    try:
        from fastapi import FastAPI, Header, HTTPException, Query, Request
        from fastapi.responses import HTMLResponse, JSONResponse
    except ImportError as error:
        raise ReportFlowError("Embedded portal server requires the optional FastAPI enterprise dependency.") from error

    app = FastAPI(title="ReportFlow Embedded Portal", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ReportFlowError)
    async def reportflow_error(_: Request, error: ReportFlowError):
        return JSONResponse(status_code=400, content={"error": "invalid_request", "detail": str(error)})

    def load_principal(authorization: str | None) -> tuple[str, set[str]]:
        try:
            return principal_loader(authorization)
        except Exception as error:
            raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"}) from error

    @app.post("/portal/v2/session")
    def issue_session(tenant_id: str = Query(...), authorization: str | None = Header(default=None)):
        subject, tenants = load_principal(authorization)
        return {"session_token": service.issue(tenant_id, subject, tenants), "expires_in_seconds": 600}

    @app.get("/portal/v2/shell", response_class=HTMLResponse)
    def portal_shell(x_portal_session: str | None = Header(default=None)):
        if not x_portal_session:
            raise HTTPException(status_code=401, detail="Portal session required")
        return HTMLResponse(service.render_shell(x_portal_session), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'self'; img-src https:; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'"})

    @app.get("/portal/v2/tenants/{tenant_id}/reports/{report_id}")
    def report_metadata(tenant_id: str, report_id: int, x_portal_session: str | None = Header(default=None)):
        if not x_portal_session:
            raise HTTPException(status_code=401, detail="Portal session required")
        service.assert_report_access(x_portal_session, tenant_id, report_id)
        report = service.registry.store.get_report(report_id)
        grant = next(item for item in service.registry.list_granted_reports(tenant_id) if item.report_id == report_id)
        return {"id": report.id, "title": report.title, "formats": report.formats, "classification": grant.classification}

    return app

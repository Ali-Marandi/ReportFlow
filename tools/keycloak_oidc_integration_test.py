"""Automated local browser simulation for the Keycloak OIDC integration test.

This script uses only the disposable Keycloak realm and user created under
`.local-keycloak`. It exercises ReportFlow's actual browser authorization URL,
loopback callback listener, authorization-code exchange, JWKS verification and
group-to-role mapping. It never serializes access, refresh, or ID tokens.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reportflow_app.core import ReportFlowError
from reportflow_app.identity import LoopbackCallbackReceiver, NativeOIDCClient, OIDCProviderConfig

RESULT_PATH = ROOT / ".local-keycloak" / "oidc-integration-result.json"


def submit_keycloak_login(authorize_url: str, username: str, password: str) -> None:
    """Follow the local Keycloak HTML login form as a disposable test user agent."""
    session = requests.Session()
    page = session.get(authorize_url, timeout=10)
    page.raise_for_status()
    form = BeautifulSoup(page.text, "html.parser").find("form")
    if form is None or not form.get("action"):
        raise ReportFlowError("Keycloak test login form was not returned by the local IdP.")
    fields: dict[str, str] = {}
    for control in form.select("input[name]"):
        name = str(control.get("name"))
        fields[name] = str(control.get("value", ""))
    fields["username"] = username
    fields["password"] = password
    # Requests honors the Secure flag literally, while browsers permit the disposable local
    # development flow. Forward only cookies created by this loopback test session.
    cookie_header = "; ".join(f"{cookie.name}={cookie.value}" for cookie in session.cookies)
    response = session.post(urllib.parse.urljoin(page.url, str(form["action"])), data=fields,
                            headers={"Cookie": cookie_header}, timeout=10, allow_redirects=True)
    if response.status_code >= 400:
        (ROOT / ".local-keycloak" / "oidc-login-error.html").write_text(response.text, encoding="utf-8")
        raise ReportFlowError(f"Local Keycloak login failed with HTTP {response.status_code}; diagnostic page was saved locally.")


def main() -> None:
    username = os.environ.get("REPORTFLOW_KEYCLOAK_TEST_USERNAME", "")
    password = os.environ.get("REPORTFLOW_KEYCLOAK_TEST_PASSWORD", "")
    if not username or not password:
        raise ReportFlowError("Local test credentials must be supplied through the process environment.")
    config = OIDCProviderConfig(
        issuer="http://127.0.0.1:8180/realms/reportflow-test",
        client_id="reportflow-desktop-test",
        redirect_uri="http://127.0.0.1:49152/oauth/callback",
        group_claim="groups",
        allow_insecure_loopback_for_testing=True,
    )
    client = NativeOIDCClient(config)
    with LoopbackCallbackReceiver(config.redirect_uri) as receiver:
        login = client.start_login()
        submit_keycloak_login(login.authorization_url, username, password)
        callback = receiver.wait_for_callback(timeout_seconds=10)
    result = client.complete(callback, {"Finance Analysts": "report_author"})
    if result.roles != ["report_author"]:
        raise ReportFlowError("Keycloak group claim was not mapped to the expected ReportFlow role.")
    RESULT_PATH.write_text(json.dumps({
        "status": "passed",
        "issuer": result.issuer,
        "subject_present": bool(result.subject),
        "email": result.email,
        "groups": result.groups,
        "roles": result.roles,
        "token_validated_via_jwks": True,
        "flow": "authorization_code_pkce_s256",
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

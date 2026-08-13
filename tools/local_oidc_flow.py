"""Run a local Keycloak OIDC Authorization Code + PKCE test for ReportFlow.

This helper is for localhost test environments only. It writes no credential or
access token to disk; the result contains only non-secret identity metadata.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reportflow_app.identity import LoopbackCallbackReceiver, NativeOIDCClient, OIDCProviderConfig

RESULT_PATH = ROOT / ".local-keycloak" / "oidc-flow-result.json"
LOGIN_URL_PATH = ROOT / ".local-keycloak" / "oidc-login-url.txt"


def main() -> None:
    issuer = "http://127.0.0.1:8180/realms/reportflow-test"
    redirect_uri = "http://127.0.0.1:49152/oauth/callback"
    client = NativeOIDCClient(OIDCProviderConfig(
        issuer=issuer,
        client_id="reportflow-desktop-test",
        redirect_uri=redirect_uri,
        group_claim="groups",
        allow_insecure_loopback_for_testing=True,
    ))
    with LoopbackCallbackReceiver(redirect_uri) as receiver:
        login = client.start_login()
        LOGIN_URL_PATH.write_text(login.authorization_url, encoding="utf-8")
        callback = receiver.wait_for_callback(timeout_seconds=240)
    session = client.complete(callback, {"Finance Analysts": "report_author"})
    RESULT_PATH.write_text(json.dumps({
        "status": "authenticated",
        "subject": session.subject,
        "issuer": session.issuer,
        "email": session.email,
        "display_name": session.display_name,
        "groups": session.groups,
        "roles": session.roles,
        "expires_at": session.expires_at,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

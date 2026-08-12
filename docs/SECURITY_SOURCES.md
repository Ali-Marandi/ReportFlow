# منابع و یافته‌های امنیتی v2.0

| حوزه | یافتهٔ مورد استفاده | منبع |
|---|---|---|
| SSO دسکتاپ | OIDC لایهٔ identity بر OAuth 2.0 است و ID Token claimهای authentication را منتقل می‌کند. | [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html) |
| Native OAuth | برنامهٔ native باید authorization را در external browser اجرا کند؛ public native client باید PKCE پیاده‌سازی کند. | [RFC 8252](https://www.rfc-editor.org/info/rfc8252/) |
| PKCE | `S256` باید در صورت امکان استفاده شود؛ code verifier برای هر authorization request تصادفی و مستقل است. | [RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636) |
| SCIM | SCIM یک پروتکل HTTP/JSON برای provisioning و مدیریت User/Group در محیط‌های cross-domain است؛ TLS و نگاشت هویت به policy لازم است. | [RFC 7644](https://datatracker.ietf.org/doc/html/rfc7644) |
| HashiCorp Vault | AppRole برای machine/service workflow است؛ role_id و secret_id token محدود به policy صادر می‌کنند و KV v2 secret versioning دارد. | [Vault AppRole](https://developer.hashicorp.com/vault/docs/auth/approle) · [Vault KV v2 API](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2) |
| Azure Key Vault | `DefaultAzureCredential` از هویت محلی در توسعه و managed identity در deployment پشتیبانی می‌کند؛ secret نباید در code نگهداری شود. | [Azure Key Vault Python](https://learn.microsoft.com/en-us/azure/key-vault/secrets/quick-create-python) |
| Code signing | SignTool برای sign، timestamp و verify استفاده می‌شود؛ SHA-256 برای `/fd` و `/td` توصیه شده است. | [Microsoft SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool) |
| Supply chain | GitHub attestation provenance artifact را به workflow، repository، commit و event پیوند می‌دهد؛ attestation باید توسط مصرف‌کننده verify شود. | [GitHub Artifact Attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations) |
| Workflow hardening | secrets باید least-privilege، review و rotate شوند؛ actionهای ثالث بهتر است به commit SHA pin شوند؛ OIDC برای token کوتاه‌عمر cloud توصیه می‌شود. | [GitHub Secure Use Reference](https://docs.github.com/en/actions/reference/security/secure-use) |
| Connector pentest | API Top 10 شامل BOLA، authentication، resource consumption، function authorization، SSRF، inventory و unsafe consumption است. | [OWASP API Security Top 10](https://owasp.org/API-Security/editions/2023/en/0x11-t10/) |
| Desktop pentest | ریسک‌های اصلی desktop شامل injection، authentication/session، sensitive data، authorization، transport، code signing، vulnerable components و monitoring است. | [OWASP Desktop App Security Top 10](https://owasp.org/www-project-desktop-app-security-top-10/) |
| تست مجاز | WSTG حوزه‌های identity، authentication، authorization، session، input validation، crypto، business logic و API را برای test plan فهرست می‌کند. | [OWASP WSTG](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/05-Authorization_Testing/README) |

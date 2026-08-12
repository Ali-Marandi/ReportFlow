# معماری امنیت و هویت ReportFlow v2.0

## تصمیم معماری

ReportFlow Desktop یک **native public client** است؛ بنابراین هر login باید با browser خارجی، Authorization Code Flow و PKCE-S256 انجام شود. برنامه هیچ `client_secret`ای ندارد و فقط tokenهای کوتاه‌عمر را در credential vault سیستم‌عامل نگهداری می‌کند. RFC 8252 استفاده از browser خارجی و PKCE را برای native app توصیه می‌کند و RFC 7636 استفاده از `S256` را در صورت امکان الزام می‌داند.[1] [2]

SCIM یک قابلیت **control plane** است، نه endpointی در فایل اجرایی کاربر. ماژول `identity_service.py` یک adapter اختیاری FastAPI برای سرویس سازمانی فراهم می‌کند؛ این adapter باید پشت gateway سازمانی، TLS، WAF، log مرکزی و network allowlist مستقر شود. SCIM از HTTP/JSON برای مدیریت User و Group استفاده می‌کند و باید subject احراز‌شده را به policy دسترسی نگاشت کند.[3]

| لایه | مسئولیت | کنترل‌های الزام‌آور |
|---|---|---|
| Desktop client | ورود کاربر، دریافت Authorization Code، نگهداری session محلی | browser خارجی، PKCE-S256، state و nonce تک‌بارمصرف، validate `iss/aud/exp/nonce`، logout و حذف token |
| Identity control plane | provisioning از IdP و تبدیل group به role | SCIM bearer/mTLS، tenant isolation، schema validation، idempotency، audit، disable فوری کاربر |
| Authorization | مجوز عملیات داخلی | role-to-permission، deny-by-default، check در سطح object و function |
| Central secrets | بازیابی فقط-خواندنی credential connector | Vault KV v2 / Azure Key Vault / AWS Secrets Manager، هویت workload، path allowlist، TTL، rotation، audit |
| Connector runtime | اتصال حداقل‌دسترسی به داده و API | credential reference، read-only query، TLS، timeout، size limit، host/CIDR allowlist، منع redirect |
| Release supply chain | ساخت، امضا، attestation و انتشار | protected environment، review، SignTool SHA-256 + RFC 3161 timestamp، signature verification، SHA-256 manifest، SBOM و provenance |

## جریان SSO

1. Administrator یک OIDC provider با issuer HTTPS، client ID، redirect URI و scopeهای حداقلی تعریف می‌کند.
2. ReportFlow برای هر login یک `state`، `nonce` و `code_verifier` با entropy کافی می‌سازد و browser سیستم را باز می‌کند.
3. پس از loopback/claimed-HTTPS redirect، برنامه `state` و سپس token response را validate می‌کند.
4. ID Token با JWKS provider و claimهای `iss`، `aud`، `exp` و `nonce` اعتبارسنجی می‌شود. roleها تنها از group claimهای allowlisted یا state SCIM دریافت می‌گردند.
5. logout tokenهای محلی را حذف و audit event ثبت می‌کند؛ هر تصمیم مجوز در زمان عمل نیز بازبینی می‌شود.

> **قاعدهٔ محصول:** Claims دریافتی از IdP هویت را اثبات می‌کنند؛ اما گزارش، connector، burst و semantic asset فقط پس از authorization محلی و tenant-scoped قابل دسترسی‌اند.

## جریان SCIM و RBAC

| SCIM resource | رفتار ReportFlow | امنیت |
|---|---|---|
| `User` | upsert با `externalId`/`userName` پایدار، email و `active` | schema allowlist، PII-minimization، deactivate به‌جای حذف destructive |
| `Group` | نگاشت صریح گروه IdP به roleهای ثابت ReportFlow | هیچ role دلخواهی از payload پذیرفته نمی‌شود |
| `PATCH` | فقط pathهای allowlisted: `active`، `displayName`، `emails` و group membership | منع mass assignment و محافظت در برابر privilege escalation |
| `ServiceProviderConfig` | اعلام capabilityهای واقعی | عدم اعلام Bulk/Filter تا زمان پیاده‌سازی کامل |

roleهای پایه عبارت‌اند از `report_viewer`، `report_author`، `burst_operator`، `connector_admin`، `semantic_steward` و `tenant_admin`. هر نقش کمترین permission لازم را دارد و هر operation حساس به audit log اضافه می‌شود.

## الگوی Central Secret Manager

`credential_reference` هرگز secret نیست. شکل توصیه‌شدهٔ reference عبارت است از `vault://reportflow/prod/connectors/salesforce#token` یا `azurekv://reportflow-prod-salesforce-token`. adapterها فقط read انجام می‌دهند و مسیر را به prefix مصوب tenant محدود می‌کنند. Vault AppRole برای workloadها policy و TTL صدور token را کنترل می‌کند و KV v2 نسخه‌بندی secret دارد.[4] Azure Key Vault نیز از passwordless `DefaultAzureCredential` و managed identity در deployment پشتیبانی می‌کند.[5]

| محیط | روش bootstrap مجاز | روش ممنوع |
|---|---|---|
| توسعهٔ محلی | OS credential vault یا login توسعه‌دهنده به cloud CLI | ذخیرهٔ secret در `.env`، source code یا connector profile |
| desktop سازمانی | certificate/device identity یا short-lived wrapped bootstrap از MDM | AppRole SecretID بلندعمر در binary یا registry |
| control plane/worker | workload identity، managed identity یا OIDC federated identity | cloud access key یا Vault root token در GitHub Secret |
| GitHub release | OIDC به signing/secrets service و protected environment | PFX/password بدون review یا publish از PR workflow |

## Network و connector controls

Connectorهای REST فقط HTTPS، hostname allowlist، CIDR allowlist صریح برای private endpoint، timeout، response-size cap و **redirect ممنوع** را می‌پذیرند. Connectorهای SQL فقط query تک‌دستوری read-only، TLS verification، credential از resolver و connection/statement timeout دارند. این کنترل‌ها مستقیماً ریسک SSRF و unsafe consumption را که OWASP برای APIها فهرست می‌کند کاهش می‌دهند.[6]

## امضای کد و انتشار

workflow release فقط tagهای `v2.*` را می‌پذیرد و باید به GitHub Environment محافظت‌شده متصل باشد. پس از test و dependency audit، executable امضا، timestamp و verify می‌شود؛ سپس archive، hash manifest، SBOM و GitHub artifact attestation ایجاد می‌شوند. SignTool برای sign، timestamp و verify به‌کار می‌رود و `/fd SHA256` و `/td SHA256` را نیاز دارد.[7] Artifact attestation provenance را به repository، commit و workflow پیوند می‌دهد، اما جای security review را نمی‌گیرد.[8]

## منابع

[1]: https://www.rfc-editor.org/info/rfc8252/ "RFC 8252 — OAuth 2.0 for Native Apps"
[2]: https://datatracker.ietf.org/doc/html/rfc7636 "RFC 7636 — PKCE"
[3]: https://datatracker.ietf.org/doc/html/rfc7644 "RFC 7644 — SCIM Protocol"
[4]: https://developer.hashicorp.com/vault/docs/auth/approle "HashiCorp Vault — AppRole"
[5]: https://learn.microsoft.com/en-us/azure/key-vault/secrets/quick-create-python "Microsoft Learn — Azure Key Vault Python"
[6]: https://owasp.org/API-Security/editions/2023/en/0x11-t10/ "OWASP API Security Top 10 2023"
[7]: https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool "Microsoft SignTool"
[8]: https://docs.github.com/en/actions/concepts/security/artifact-attestations "GitHub Artifact Attestations"

# راهنمای مدیریت سازمانی ReportFlow v2.0

## 1. مسئولیت‌ها و مرزهای عملیاتی

ReportFlow v2.0 برای استقرار سازمانی به تفکیک نقش نیاز دارد. مدیر سازمان ownership تنظیمات tenant و policy را دارد؛ مدیر هویت IdP و SCIM را اداره می‌کند؛ مدیر connector فقط endpoint و reference را ایجاد می‌کند؛ و release manager بدون دسترسی به دادهٔ واقعی، انتشار امضاشده را مدیریت می‌کند. تفکیک وظایف برای جلوگیری از privilege accumulation الزامی است.

| نقش ReportFlow | مسئولیت | دسترسی ممنوع پیش‌فرض |
|---|---|---|
| `tenant_admin` | policy، role mapping، audit و lifecycle tenant | استفادهٔ روزمره از connector credential یا signing key |
| `connector_admin` | تعریف endpoint، allowlist و credential reference | خواندن secret value یا تغییر RBAC tenant |
| `semantic_steward` | metric، lineage و policy semantic layer | delivery گزارش به مخاطبان گسترده |
| `burst_operator` | تعریف و اجرای burst approval شده | ایجاد/ویرایش connector یا role mapping |
| `report_author` | ساخت و اجرای گزارش‌های مجاز | مدیریت users/groups یا secret providers |
| `report_viewer` | مشاهدهٔ output دارای مجوز | تغییر report، connector یا schedule |

> **اصل کمینه‌سازی:** هیچ نقش فردی نباید هم IdP/SCIM، secret provider، recipient list و signing key production را کنترل کند.

## 2. راه‌اندازی اولیه tenant

ابتدا administrator باید محیط‌های `development`، `staging` و `production` را جدا کند. هر محیط IdP، secrets namespace، connector profile و audit retention مستقل دارد. دادهٔ production هرگز برای آزمون UI یا OIDC استفاده نمی‌شود.

| گام | اقدام | شاهد لازم |
|---:|---|---|
| 1 | tenant و ownerهای business/security را ثبت کنید | ticket و data classification |
| 2 | role-to-permission و group-to-role mapping را تأیید کنید | جدول approval شدهٔ RBAC |
| 3 | IdP و client Desktop را در staging ثبت کنید | discovery URL و redirect URI approved |
| 4 | Secret Manager و policy path را ایجاد کنید | policy least-privilege و rotation plan |
| 5 | connector را ابتدا با `dry_run` و دادهٔ synthetic اعتبارسنجی کنید | audit event و test evidence |
| 6 | report burst را با recipient test تأیید و سپس change approval بگیرید | recipient mapping و owner sign-off |

## 3. پیکربندی SSO با OIDC

### 3.1 تنظیم client تولیدی

ReportFlow Desktop یک **public native client** است و client secret نمی‌پذیرد. در IdP خود، Authorization Code flow را فعال و Implicit و Resource Owner Password flow را غیرفعال کنید. redirect URI باید دقیق باشد؛ wildcard، scheme سفارشی بدون policy و redirect خارجی مجاز نیست.

| تنظیم IdP | مقدار production |
|---|---|
| Client type | Public native/OpenID Connect |
| Flow | Authorization Code + PKCE-S256 |
| Redirect URI | `http://127.0.0.1:<approved-port>/oauth/callback` یا claimed HTTPS URI مصوب |
| Scopes | `openid profile email` و scope سازمانی حداقلی |
| ID token signing | RS256 یا ES256 و JWKS قابل‌دسترسی HTTPS |
| Group claim | `groups` با allowlist mapping در ReportFlow |
| Direct grant / password flow | غیرفعال |
| Implicit flow | غیرفعال |
| Token lifetime | کوتاه، مطابق policy سازمان؛ refresh lifecycle کنترل‌شده |

Keycloak برای native application از Authorization Code flow استفاده می‌کند و discovery endpoint را در `/realms/{realm}/.well-known/openid-configuration` ارائه می‌دهد.[1] Keycloak همچنین دربارهٔ ریسک Implicit و Direct Grant هشدار می‌دهد؛ ReportFlow هیچ‌کدام را به کار نمی‌گیرد.[2]

### 3.2 نگاشت گروه و نقش

فقط گروه‌هایی که در جدول مصوب وجود دارند به role تبدیل می‌شوند. claim ناشناخته role اضافه نمی‌کند.

| IdP group نمونه | نقش ReportFlow | تأییدکننده |
|---|---|---|
| `Finance Analysts` | `report_author` | Finance Data Owner |
| `ReportFlow Burst Operators` | `burst_operator` | Distribution Owner |
| `ReportFlow Connector Admins` | `connector_admin` | Platform Security |
| `ReportFlow Tenant Admins` | `tenant_admin` | CISO Delegate |

هر تغییر mapping یک change record، آزمون staging و بازبینی audit بعد از اجرا لازم دارد. برای offboarding، IdP باید `active=false` را از طریق SCIM provision کند یا access را revoke کند؛ حذف مستقیم historical audit ممنوع است.

## 4. پیکربندی SCIM

SCIM control plane را فقط روی server-side و پشت TLS/gateway منتشر کنید. برای هر IdP یک token یا mTLS identity مجزا و tenant-scoped تعریف کنید. Endpointهای فعال در v2.0 در مرجع API توضیح داده شده‌اند؛ Bulk و filter تا زمان hardening کامل غیرفعال‌اند.

```text
Base URL: https://reportflow-control.example/scim/v2
Authentication: Bearer token from central secret manager
Users: GET/POST/PATCH /Users
Groups: POST /Groups
Capabilities: GET /ServiceProviderConfig
```

| کنترل | تنظیم مدیر |
|---|---|
| Network | IdP egress IP/mTLS gateway را allowlist کنید |
| Token | TTL کوتاه، rotation، دسترسی فقط به namespace SCIM همان tenant |
| Schema | PATCH فقط `active`، `displayName` و `emails` |
| Logs | identity eventها را به SIEM ارسال و PII را minimize کنید |
| Deprovision | پیش از قطع حساب، evidence و owner را ثبت کنید |

SCIM برای مدیریت HTTP-based identity resourceها تعریف شده است؛ باید user/group identifiers پایدار و idempotent نگه‌داری شوند.[3]

## 5. Secret Manager مرکزی

Secret value هرگز در connector profile، export، SQLite catalog، screenshot یا log قرار نمی‌گیرد. مدیر فقط reference ثبت می‌کند و workload identity/secret provider در runtime مقدار را resolve می‌کند.

| Provider | آماده‌سازی مدیر | الگوی reference |
|---|---|---|
| HashiCorp Vault | policy path، AppRole یا workload identity، TTL، audit device | `vault:///reportflow/prod/connectors/crm#password` |
| Azure Key Vault | managed identity، RBAC `get` فقط، private endpoint | `azurekv:///reportflow-prod-crm-password` |
| AWS Secrets Manager | IAM role با `GetSecretValue` محدود به ARN tenant | `awssecrets:///arn:aws:...#password` |
| Local OS vault | فقط development/test کنترل‌شده | `local://development/crm-token` |

برای Vault، `role_id` شناسه است ولی `secret_id` نباید داخل executable یا profile باشد. Vault AppRole policy و TTL را برای workload کنترل می‌کند؛ namespace production و staging نباید مشترک باشند.[4]

### Rotation drill

ماهانه یک rotation test روی credential synthetic اجرا کنید: secret جدید ایجاد، connector staging اجرا، version قبلی revoke، audit بررسی و rollback سندگذاری شود. تست موفق فقط زمانی است که profile بدون تغییر به credential جدید resolve شود و هیچ secret در log دیده نشود.

## 6. مدیریت connectorها و Report Bursting

هر connector باید مالک داده، classification، retention، endpoint allowlist، service account read-only و timeout/resource policy داشته باشد. REST connectorهای private تنها با CIDR explicit و egress policy مجازند؛ DNS/redirect آزاد ممنوع است. SQL validation در client جایگزین read-only role روی database نیست.

| نوع | حداقل policy |
|---|---|
| PostgreSQL | TLS، `default_transaction_read_only=on`، principal read-only، statement/connection timeout |
| SQL Server | Encrypt، certificate verification، `ApplicationIntent=ReadOnly`، login read-only |
| REST JSON | HTTPS، host/CIDR allowlist، redirect ممنوع، response-size cap و timeout |
| File/Excel | source root allowlist، مالک و classification، parser update cadence |
| SMTP burst | approved delivery، sender domain مصوب، DLP/secure portal برای دادهٔ حساس |

Report bursting ابتدا با `dry_run=True`، recipient synthetic و filter قابل‌بررسی اجرا می‌شود. اجرای واقعی نیازمند `approved=True` و sign-off distribution owner است. هر artifact باید per-recipient باشد؛ هرگونه row outside filter incident امنیتی است.

## 7. Audit، monitoring و incident response

| رویداد | حداقل metadata audit | هشدار پیشنهادی |
|---|---|---|
| OIDC login | issuer، subject hash، outcome، roleها، timestamp | failure burst، issuer mismatch، nonce/state failure |
| SCIM | actor، resource type/id، change type، tenant، outcome | role update attempt، bulk failure، deactivate spike |
| Secret resolve | provider، reference hash/path class، outcome، latency | reference خارج از prefix، repeated denial، rotation failure |
| Connector | profile id، endpoint class، row count bucket، outcome | host/CIDR rejection، TLS failure، resource cap |
| Burst | template id، recipient hash/count، dry-run/approved، artifact hash | non-approved attempt، recipient anomaly، cross-filter result |
| Release | tag، commit SHA، signer thumbprint، hash، attestation | signature invalid، unprotected tag، provenance mismatch |

در incident مشکوک به secret exposure، connector مربوطه را disable، token/secret را rotate، audit window را preserve، data owner را مطلع و root cause را ثبت کنید. حذف log یا artifact پیش از legal/security direction ممنوع است.

## 8. Checklist Go-Live

| کنترل | owner | وضعیت لازم |
|---|---|---|
| OIDC PKCE، redirect و JWKS test staging | Identity Admin | Pass |
| SCIM deprovision و privilege test | Identity + Security | Pass |
| Secret rotation و path isolation | Platform Security | Pass |
| Connector SSRF/TLS/read-only tests | Data Platform | Pass |
| Burst dry-run و DLP validation | Distribution Owner | Pass |
| Pentest blocker remediation | Security Engineering | No Critical/High open |
| Signed release/SBOM/attestation verify | Release Manager | Pass |
| Runbook، on-call و rollback test | Operations | Pass |

## منابع

[1]: https://www.keycloak.org/securing-apps/oidc-layers "Keycloak — OIDC Layers"
[2]: https://www.keycloak.org/securing-apps/oidc-layers "Keycloak — Supported Grant Types and Recommendations"
[3]: https://datatracker.ietf.org/doc/html/rfc7644 "RFC 7644 — SCIM Protocol"
[4]: https://developer.hashicorp.com/vault/docs/auth/approle "HashiCorp Vault — AppRole"

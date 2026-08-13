# مرجع API و قراردادهای Enterprise — ReportFlow v2.0

## دامنه و قرارداد استقرار

ReportFlow Desktop یک client محلی است و API عمومیِ پیش‌فرضی روی دستگاه کاربر باز نمی‌کند. APIهای SCIM در `reportflow_app.identity_service` یک **control plane اختیاری و server-side** هستند؛ آن‌ها باید پشت HTTPS، API gateway، محدودیت شبکه، احراز هویت و logging سازمانی مستقر شوند. Endpointها با SCIM 2.0 هم‌راستا هستند و برای provisioning سرویس‌های IdP استفاده می‌شوند.[1]

> **مرز امنیتی:** Desktop فقط OIDC Authorization Code با PKCE را آغاز و callback loopback را می‌پذیرد. SCIM، secret retrieval و delivery سازمانی در desktop بدون پیکربندی/approval صریح server-side فعال نمی‌شوند.

| محیط | Base URL نمونه | احراز هویت | دادهٔ مجاز |
|---|---|---|---|
| Local test | `http://127.0.0.1:8180` فقط برای IdP آزمایشی | حساب disposable | دادهٔ synthetic |
| Staging | `https://reportflow-control.staging.example/scim/v2` | Bearer token موقت از Secret Manager | test tenant |
| Production | `https://reportflow-control.example/scim/v2` | Bearer/mTLS پشت gateway | tenant-scoped production data |

## 1. API کنترل‌پلین SCIM

### 1.1 احراز هویت و headerها

همهٔ endpointهای SCIM نیازمند header زیر هستند. token باید در زمان request از Secret Manager مرکزی resolve شود؛ قرار دادن token در repository، فایل پیکربندی desktop یا installer ممنوع است.

```http
Authorization: Bearer <scim-provisioning-token>
Accept: application/scim+json
Content-Type: application/scim+json
```

عدم وجود یا نامعتبر بودن token با `401` و `WWW-Authenticate: Bearer` پاسخ داده می‌شود. خطاهای validation با بدنهٔ SCIM Error بازمی‌گردند. token در log ثبت نمی‌شود.

### 1.2 Discovery قابلیت‌ها

`GET /scim/v2/ServiceProviderConfig`

این endpoint capabilityهای واقعی implementation را گزارش می‌دهد. در v2.0، `PATCH` پشتیبانی می‌شود اما Bulk، filter و change-password عمداً غیرفعال هستند تا سطح حمله تا زمان پیاده‌سازی کامل آن‌ها افزایش نیابد.

```json
{
  "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
  "patch": {"supported": true},
  "bulk": {"supported": false},
  "filter": {"supported": false},
  "changePassword": {"supported": false},
  "sort": {"supported": false}
}
```

### 1.3 Users

| عملیات | مسیر | پاسخ موفق | رفتار امنیتی |
|---|---|---:|---|
| فهرست کاربران | `GET /scim/v2/Users?startIndex=1&count=100` | 200 | pagination حداکثر ۱۰۰؛ tenant gateway باید scope را enforce کند |
| دریافت یک کاربر | `GET /scim/v2/Users/{id}` | 200 | شناسهٔ ناموجود بدون افشای object دیگر با 404 پاسخ می‌گیرد |
| ایجاد/همگام‌سازی | `POST /scim/v2/Users` | 201 | upsert با `externalId` و validate schema |
| تغییر محدود | `PATCH /scim/v2/Users/{id}` | 200 | فقط `active`، `displayName` و `emails` allowlist هستند |

نمونهٔ ایجاد کاربر:

```json
{
  "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
  "externalId": "idp:alice-001",
  "userName": "alice@example.com",
  "displayName": "Alice Example",
  "active": true,
  "emails": [{"value": "alice@example.com", "primary": true}],
  "groups": [{"display": "Finance Analysts"}]
}
```

نمونهٔ patch مجاز برای deprovisioning:

```json
{
  "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
  "Operations": [{"op": "replace", "path": "active", "value": false}]
}
```

تغییر مستقیم `roles`، `id`، `externalId` و سایر فیلدهای محافظت‌شده با خطای `invalidValue` رد می‌شود. نقش‌ها فقط از نگاشت ثابت گروه IdP به role ReportFlow به‌دست می‌آیند.

### 1.4 Groups

`POST /scim/v2/Groups` یک گروه و memberهای آن را provision می‌کند. هر member باید به user شناخته‌شده تعلق داشته باشد. payload نامعتبر یا member خارج از tenant رد می‌شود.

```json
{
  "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
  "externalId": "idp:finance-analysts",
  "displayName": "Finance Analysts",
  "members": [{"value": "idp:alice-001"}]
}
```

### 1.5 مدل خطا

```json
{
  "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
  "status": "400",
  "scimType": "invalidValue",
  "detail": "SCIM PATCH attempted to update a protected field."
}
```

خطاها نباید حاوی access token، credential reference کامل، secret value یا PII غیرضروری باشند.

## 2. قرارداد هویت Desktop

### 2.1 `OIDCProviderConfig`

| فیلد | اجباری | توضیح |
|---|---:|---|
| `issuer` | بله | URL HTTPS issuer؛ فقط در آزمایش opt-in loopback HTTP مجاز است |
| `client_id` | بله | شناسهٔ public native client؛ secret ندارد |
| `redirect_uri` | بله | HTTPS یا `http://127.0.0.1:<port>/<path>` دقیقاً ثبت‌شده |
| `scopes` | بله | حداقل `openid`؛ به‌طور پیش‌فرض `openid profile email` |
| `group_claim` | خیر | نام claim گروه‌ها، پیش‌فرض `groups` |
| `allowed_algorithms` | خیر | فقط RS/ES algorithmهای allowlisted |
| `allow_insecure_loopback_for_testing` | خیر | پیش‌فرض `false`؛ فقط تست محلی disposable |

`NativeOIDCClient.start_login()` یک `state`، `nonce` و `code_verifier` تصادفی تولید و URL Authorization Code + PKCE-S256 را بازمی‌گرداند. `LoopbackCallbackReceiver` فقط یک callback روی host، port و path ثبت‌شده می‌پذیرد و پاسخ را با `Cache-Control: no-store` برمی‌گرداند. `NativeOIDCClient.complete()` code را exchange، ID Token را از JWKS validate و groups را به roleهای allowlisted تبدیل می‌کند.[2] [3]

```python
config = OIDCProviderConfig(
    issuer="https://id.example.com/realms/reportflow",
    client_id="reportflow-desktop",
    redirect_uri="http://127.0.0.1:49152/oauth/callback",
)
client = NativeOIDCClient(config)
with LoopbackCallbackReceiver(config.redirect_uri) as callback:
    login = client.start_login()
    # Open login.authorization_url with the operating-system browser.
    session = client.complete(callback.wait_for_callback(), {
        "Finance Analysts": "report_author"
    })
```

## 3. قرارداد Secret Manager

Connector profile فقط `credential_reference` دارد و هرگز secret value ندارد. `SecretResolver` scheme را به providerهای approved map می‌کند و providerها read-only هستند.

| Scheme | شکل reference | کاربرد |
|---|---|---|
| `local://` | `local://namespace/name` | توسعهٔ محلی با OS credential vault؛ production default نیست |
| `vault://` | `vault:///reportflow/prod/connectors/crm#password` | HashiCorp Vault KV v2 با AppRole کوتاه‌عمر |
| `azurekv://` | `azurekv:///reportflow-prod-crm-password` | Azure Key Vault با workload/managed identity |
| `awssecrets://` | `awssecrets:///arn:aws:...#password` | AWS Secrets Manager با IAM credential chain |

برای Vault، path باید زیر `allowed_path_prefix` باشد، segmentهای `.` و `..` رد می‌شوند و redirect ممنوع است. bootstrap secret AppRole باید کوتاه‌عمر و خارج از config desktop باشد.[4]

## 4. قرارداد Connector و Report Bursting

`ConnectorRegistry(secret_provider=resolver)` connectorهای approved را برمی‌سازد. REST فقط HTTPS، host allowlist، CIDR خصوصی مصوب، response cap، timeout و no-redirect را می‌پذیرد. SQL فقط query تک‌دستوری، comment-free و read-only را می‌پذیرد؛ DB principal باید مستقل از validation client صرفاً read داشته باشد.

`ReportBurstService.execute()` برای هر recipient یک artifact جدا می‌سازد. `dry_run=True` حالت پیش‌فرض است. تحویل SMTP فقط زمانی مجاز است که caller `approved=True` ارسال کند و secret SMTP از resolver approved آمده باشد. تمام executionها باید audit event تولید کنند.

## 5. Versioning و سازگاری

API در مسیر `/scim/v2` versioned است. حذف یا تغییر ناسازگار fieldها نیازمند version جدید endpoint، migration note، آزمون IdP staging و بازبینی Security است. افزودن provider/connector جدید نیز باید security review، threat model، test منفی و entry در Enterprise Admin Guide داشته باشد.

## منابع

[1]: https://datatracker.ietf.org/doc/html/rfc7644 "RFC 7644 — SCIM Protocol"
[2]: https://www.rfc-editor.org/info/rfc8252/ "RFC 8252 — OAuth 2.0 for Native Apps"
[3]: https://datatracker.ietf.org/doc/html/rfc7636 "RFC 7636 — PKCE"
[4]: https://developer.hashicorp.com/vault/docs/auth/approle "HashiCorp Vault — AppRole"

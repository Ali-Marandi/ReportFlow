# راهنمای آزمون یکپارچه‌سازی OIDC محلی با Keycloak

## هدف و محدوده

این runbook برای اعتبارسنجی **Authorization Code Flow با PKCE-S256** در محیط disposable محلی نوشته شده است. آزمون از Keycloak روی `127.0.0.1`، realm آزمایشی، public native client و user synthetic استفاده می‌کند. HTTP در این سند فقط به دلیل محدود بودن به loopback مجاز است؛ هیچ‌یک از این تنظیمات برای staging یا production قابل‌استفاده نیست.

Keycloak در development mode برای آزمایش سریع مناسب است، اما راهنمای رسمی آن صریحاً استفاده از این حالت را در production منع می‌کند.[1]

## پیش‌نیاز

| مورد | نیاز |
|---|---|
| Java | runtime سازگار با نسخهٔ انتخاب‌شدهٔ Keycloak |
| Keycloak | local-only، bind به `127.0.0.1`، realm disposable |
| Python | وابستگی‌های `requirements-enterprise.txt` شامل `PyJWT[crypto]` و `requests` |
| شبکه | فقط loopback؛ هیچ tunnel، public bind یا credential مشتری مجاز نیست |
| داده | user، group و password کاملاً آزمایشی |

## پیکربندی IdP انجام‌شده برای ReportFlow

| آیتم | مقدار آزمایشی | علت |
|---|---|---|
| Server | `http://127.0.0.1:8180` | محدود به loopback sandbox |
| Realm | `reportflow-test` | جداسازی از `master` |
| Client ID | `reportflow-desktop-test` | public native client، بدون client secret |
| Standard Flow | فعال | Authorization Code flow |
| Direct Access Grants | غیرفعال | password grant در ReportFlow استفاده نمی‌شود |
| PKCE | `S256` اجباری | جلوگیری از code interception |
| Redirect URI | `http://127.0.0.1:49152/oauth/callback` | loopback callback دقیق |
| Group mapper | `groups` | نگاشت `Finance Analysts` به `report_author` |

Keycloak discovery endpoint را در مسیر `/realms/{realm}/.well-known/openid-configuration` منتشر می‌کند؛ ReportFlow endpointهای authorization، token و JWKS را از همین سند discovery می‌خواند.[2]

## اجرای آزمون

1. Keycloak را با یک administrator test و binding loopback اجرا کنید. administrator test باید صرفاً در file/env محلی با permission محدود نگه‌داری شود.
2. realm، public client، redirect URI دقیق، PKCE-S256، user synthetic و group mapper را با Admin Console یا `kcadm` ایجاد کنید.
3. وابستگی‌ها را نصب کنید: `pip install -r requirements-enterprise.txt`.
4. فقط در session محلی، username/password synthetic را به environment process آزمون بدهید. آن‌ها را در source یا history shell قرار ندهید.
5. اسکریپت `tools/keycloak_oidc_integration_test.py` را اجرا کنید.
6. فایل `.local-keycloak/oidc-integration-result.json` را بررسی کنید. این فایل فقط metadata غیرحساس ثبت می‌کند و شامل token نیست.

خروجی موفق مورد انتظار:

```json
{
  "status": "passed",
  "groups": ["Finance Analysts"],
  "roles": ["report_author"],
  "token_validated_via_jwks": true,
  "flow": "authorization_code_pkce_s256"
}
```

## کنترل‌های منفی لازم

| سناریو | نتیجهٔ صحیح |
|---|---|
| issuer HTTP بدون `allow_insecure_loopback_for_testing=True` | ReportFlow configuration را رد می‌کند |
| host غیر-loopback یا redirect URI نامنطبق | receiver/configuration آن را رد می‌کند |
| callback با path متفاوت | 404 بدون قرارگرفتن callback در queue |
| state یا nonce نامنطبق/منقضی | session ایجاد نمی‌شود |
| token با `iss`، `aud`، `exp` یا JWKS نامعتبر | ID token validation fail می‌شود |
| code بدون PKCE verifier | Keycloak با PKCE-S256 enforcement آن را رد می‌کند |
| گروه ناشناخته | role جدیدی در ReportFlow ایجاد نمی‌کند |

## انتقال به staging و production

| محل | تفاوت الزامی با local test |
|---|---|
| Staging | HTTPS IdP، tenant مستقل، test certificate/JWKS، no production data |
| Production | HTTPS/TLS، IdP HA، lifecycle token مصوب، SIEM، real group approval و change record |
| Desktop | `allow_insecure_loopback_for_testing=False`، redirect URI و issuer approved |
| Secret Manager | credentialهای IdP/SCIM فقط با workload identity و secret reference؛ نه env یا source |

Authorization Code flow برای native appها همراه با browser خارجی و PKCE توصیه می‌شود.[3] نگه‌داشتن password در desktop یا استفاده از Direct Grant، این مرز امنیتی را نقض می‌کند.

## پاک‌سازی

پس از آزمون، Keycloak test process را متوقف کنید، directory runtime و فایل‌های local credential/output را حذف کنید و هیچ‌کدام را commit نکنید. اگر test server به‌طور تصادفی فراتر از loopback bind شد، آن را فوراً متوقف و binding را بازبینی کنید.

## منابع

[1]: https://www.keycloak.org/server/configuration "Keycloak Server Configuration"
[2]: https://www.keycloak.org/securing-apps/oidc-layers "Keycloak OIDC Layers"
[3]: https://www.rfc-editor.org/info/rfc8252/ "RFC 8252 — OAuth 2.0 for Native Apps"

# ReportFlow Desktop

> **Enterprise reporting, without the reporting friction.**

ReportFlow Desktop یک نرم‌افزار تحت ویندوز برای تبدیل داده‌های CSV و Excel به گزارش‌های مدیریتی HTML، PDF و Excel است. این نسخه با تمرکز بر اجرای محلی، کیفیت داده، قابلیت تکرار، ردپای ممیزی و خروجی قابل ارائه به مدیران بازطراحی شده است.

![ReportFlow](assets/reportflow.ico)

## قابلیت‌های نسخهٔ 1.0.0

| قابلیت | شرح |
|---|---|
| Report Builder | ساخت تعریف قابل‌استفادهٔ مجدد با نام، عنوان، قالب، فیلدهای انتخابی و فرمت‌های خروجی |
| Data Intelligence | preview داده، تشخیص شمار سطر/ستون، معیارهای عددی، سلول خالی و رکورد تکراری |
| Multi-format rendering | تولید هم‌زمان **HTML، PDF و XLSX** با جدول، KPI و نمودار |
| Report Library | فهرست محلی تعریف‌ها با قابلیت ویرایش، اجرای مجدد و حذف کنترل‌شده |
| Local Scheduling | زمان‌بندی روزانهٔ محلی و ثبت نتایج اجرای خودکار |
| Evidence trail | ثبت ایجاد/ویرایش/حذف تعریف‌ها، اجرای گزارش و نتیجهٔ آن |
| Credential isolation | نگهداری credential در vault سیستم‌عامل، نه در کد، CSV یا پایگاه تعریف گزارش |
| Windows delivery pipeline | آزمون، ساخت EXE ویندوز، هش SHA-256 و artifact در GitHub Actions |

## شروع سریع برای توسعه

```bash
git clone https://github.com/Ali-Marandi/ReportFlow.git
cd ReportFlow
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python reportflow.py
```

در Linux یا macOS، روش فعال‌سازی venv متفاوت است؛ سپس همان فرمان `python reportflow.py` را اجرا کنید. برنامه برای ساخت فایل‌های اجرایی ویندوز طراحی شده، اما هسته و رابط کاربری به‌صورت cross-platform اجرا می‌شوند.

## استفاده از برنامه

ابتدا از **Report builder** یک CSV یا Excel را انتخاب کنید، یا با **Use sample** نمونهٔ امن داخلی را بارگذاری کنید. برنامه کیفیت پایهٔ داده را نمایش می‌دهد و همهٔ فیلدها را به‌طور پیش‌فرض برای گزارش انتخاب می‌کند. تعریف را ذخیره کرده و سپس **Generate report** را بزنید تا artifactها در پوشهٔ محلی زیر تولید شوند:

```text
~/.reportflow/exports
```

داده‌های محلی، catalog و audit trail نیز در مسیر `~/.reportflow` نگهداری می‌شوند. برای گزارش‌های سازمانی حاوی دادهٔ حساس، policy نگهداشت و رمزگذاری دستگاه مشتری باید توسط تیم IT تعیین شود.

## ساخت فایل اجرایی ویندوز در توسعهٔ محلی

PyInstaller باید در همان سیستم‌عامل هدف اجرا شود. بنابراین، برای تولید Windows EXE در یک ویندوز توسعه‌دهنده می‌توانید فرمان زیر را اجرا کنید:

```powershell
pyinstaller --noconfirm --clean --windowed --name ReportFlow --icon assets/reportflow.ico --add-data "assets;assets" reportflow.py
```

فایل اجرایی ایجادشده در مسیر زیر خواهد بود:

```text
dist\ReportFlow\ReportFlow.exe
```

برای تولید قابل‌تکرار، مخزن دارای workflow ویندوزی است که روی push، pull request یا اجرای دستی فعال می‌شود. خروجی build به‌عنوان GitHub Actions artifact نگهداری می‌شود. GitHub توصیه می‌کند artifactها با `upload-artifact` نگهداری شوند و digest خروجی برای اعتبارسنجی در اختیار workflow قرار می‌گیرد.[1]

## کیفیت و آزمون

```bash
pytest -q
pip-audit -r requirements.txt
```

آزمون‌ها کیفیت‌سنجی داده، round-trip تعریف گزارش، تولید HTML/PDF/XLSX و ثبت نتیجهٔ اجرا را پوشش می‌دهند.

## موضع امنیتی

این release، credentialها را از تعریف‌های گزارش جدا می‌کند و در vault سیستم‌عامل نگه می‌دارد؛ با این حال، نسخهٔ تک‌کاربره **جایگزین** کنترل هویت سازمانی نیست. برای استقرار Enterprise، SSO، RBAC/ABAC، رمزنگاری در حال سکون و حین انتقال، sign کردن باینری، central audit و policy نگهداشت ضروری است. OWASP برای برنامه‌های دسکتاپ به‌طور مشخص افشای دادهٔ حساس، مجوزدهی نادرست، ارتباط ناامن، وابستگی آسیب‌پذیر و logging ناکافی را در زمرهٔ ریسک‌های کلیدی قرار می‌دهد.[2]

> هرگونه token که در گفتگو یا فایل توسعه استفاده شده باشد باید پس از پایان کار **rotate/revoke** شود. هیچ tokenای نباید در مخزن، issue، release note یا فایل خروجی commit شود.

## نقشهٔ راه تجاری

سند [Commercial Roadmap](docs/COMMERCIAL_ROADMAP.md) شکاف با ابزارهای Enterprise، قابلیت‌های اولویت‌دار، معماری هدف، مدل تجاری و معیارهای پذیرش release را شرح می‌دهد. قابلیت‌های آینده شامل connectorهای سازمانی، report bursting، SSO/SCIM، worker مرکزی، semantic layer، workflow تأیید، embedded analytics، AI copilot با حاکمیت و supply-chain hardening هستند.

## پایه‌های Enterprise v2.0

شاخهٔ توسعهٔ v2.0 قراردادهای قابل‌آزمون برای semantic metrics، connectorهای سازمانی، Report Bursting و AI Copilot حاکمیت‌شده را اضافه می‌کند. این قابلیت‌ها هنوز به‌معنای آماده‌بودن کامل برای محیط production چندمستاجری نیستند؛ SSO/SCIM، database RLS، secrets manager مرکزی، security review و کانال‌های تحویل سازمانی باید پیش از rollout فعال شوند.

| قابلیت | وضعیت پایهٔ کد | کنترل کلیدی |
|---|---|---|
| Semantic Layer | مدل versioned برای dimension، metric، synonym، owner و lineage | aggregation قطعی و filterهای allowlisted |
| Connector Registry | CSV/Excel، SQLite، REST JSON و adapter اختیاری PostgreSQL/SQL Server | read-only query، HTTPS/host allowlist، timeout و credential reference |
| Report Bursting | mapping گیرنده به filter، dry-run پیش‌فرض و secure-folder delivery | approval صریح برای تحویل خارجی و audit هر اجرا |
| AI Copilot | grounding بر مبنای semantic metadata و metric result | عدم دسترسی LLM به raw data/secret، citation اجباری و human review |

وابستگی‌های Enterprise در فایل جداگانه قرار گرفته‌اند تا deployment تنها connectorهای مورد تأیید خود را نصب کند:

```bash
pip install -r requirements-enterprise.txt
```

برای نمونهٔ برنامه‌نویسی، ابتدا یک `ProjectStore` و سپس `EnterpriseCatalog` بسازید؛ `ConnectorProfile` تنها settings غیرحساس و `credential_reference` را نگهداری می‌کند. هر password یا token باید از طریق `CredentialVault` ذخیره و فقط در runtime resolve شود. برای اجرای burst، ابتدا `dry_run=True` را اجرا کنید؛ ارسال SMTP صرفاً با `approved=True` و credential موجود در vault مجاز است.

```python
from pathlib import Path
from reportflow_app.core import ProjectStore
from reportflow_app.enterprise import EnterpriseCatalog, ReportBurstService, SecureFolderDestination

store = ProjectStore(Path.home() / ".reportflow" / "reportflow.db")
catalog = EnterpriseCatalog(store)
service = ReportBurstService(catalog, store, Path.home() / ".reportflow" / "exports")
# service.execute(burst_definition, data, SecureFolderDestination(Path("approved-delivery")), dry_run=True)
```

جزئیات طراحی در [V2 Enterprise Architecture](docs/V2_ENTERPRISE_ARCHITECTURE.md) و برنامهٔ کسب‌وکار در [Enterprise GTM Strategy](docs/ENTERPRISE_GTM_STRATEGY.md) موجود است.

### مستندات عملیاتی v2.0

| سند | کاربرد |
|---|---|
| [API Reference v2.0](docs/API_REFERENCE_v2.md) | قراردادهای SCIM control plane، OIDC Desktop، Secret Manager و connectorها |
| [OpenAPI SCIM v2.0](docs/openapi/scim-control-plane-v2.yaml) | مشخصات ماشین‌خوان endpointهای SCIM برای gateway و IdP |
| [Enterprise Admin Guide](docs/ENTERPRISE_ADMIN_GUIDE_v2.md) | راه‌اندازی tenant، SSO/SCIM، secrets، connectors، bursting، audit و Go-Live |
| [Security Architecture](docs/V2_SECURITY_ARCHITECTURE.md) | مرزهای اعتماد، identity، secrets و supply-chain controls |
| [Pentest & Connector Security Plan](docs/PENTEST_AND_CONNECTOR_SECURITY_PLAN.md) | دامنه، سناریوها و gateهای آزمون امنیت |
| [Local Keycloak OIDC Test](docs/LOCAL_OIDC_INTEGRATION_TEST.md) | بازتولید سناریوی Keycloak loopback و Authorization Code + PKCE |
| [Release Runbook](docs/V2_RELEASE_RUNBOOK.md) | امضای کد، HSM، protected environment و انتشار کنترل‌شده |

## مجوز

**Proprietary — All rights reserved.** استفاده، توزیع یا بهره‌برداری تجاری از این کد نیازمند مجوز کتبی مالک مخزن است.

## منابع

[1]: https://docs.github.com/en/actions/tutorials/store-and-share-data "GitHub Docs — Store and Share Data with Workflow Artifacts"
[2]: https://owasp.org/www-project-desktop-app-security-top-10/ "OWASP — Desktop Application Security Top 10"

# ReportFlow v2.5.1 — بازبینی فنی Usage Metering و Feature Gating

**دامنهٔ بازبینی:** `reportflow_app/commercial_v25.py` و آزمون‌های `tests/test_commercial_v25.py`  
**وضعیت:** patch آمادهٔ merge؛ اجرای محلی 50 آزمون پاس، `pip-audit` بدون آسیب‌پذیری شناخته‌شده، Bandit و `git diff --check` پاس.  
**مدل تهدید:** tenant بدخواه، worker retryکننده، خطای duplicate delivery، admin اشتباه‌کار و export مالی غیرقابل‌توضیح.

## خلاصهٔ مدیریتی

ماژول v2.5 یک لایهٔ **entitlement و measurement** است و عمداً payment processor، invoice، tax، card data و PII recipient را مدیریت نمی‌کند. به‌همین دلیل، مرز حمله و انطباق آن کوچک‌تر از یک billing system کامل باقی می‌ماند. این بازبینی دو اصلاح مستقیم اعمال می‌کند: usage event اکنون snapshot plan/version و زمان اثر entitlement را نگه می‌دارد؛ و deny-list کلیدهای metadata برای variantهای رایج identity/credential گسترش یافته است.

> **نتیجهٔ بازبینی:** هستهٔ local/control-plane برای pilot و feature gating مناسب است، اما پیش از صدور invoice، اجرای multi-node یا پردازش payment باید با API authorization، metering service مرکزی و reconciliation رسمی تکمیل شود.

## جریان فنی

```text
Admin creates immutable CommercialPlan (plan_id + version)
  ↓
TenantEntitlement assigns active plan and approved overrides
  ↓
Feature check answers whether a capability may be used
  ↓
CommercialDistributionGate preflights quota before queue enrollment
  ↓
Distribution worker succeeds
  ↓
record_success(job_id) creates idempotent UsageEvent
  ↓
UsageSummary informs alerting / future billing export
```

| کنترل | پیاده‌سازی | ارزیابی |
|---|---|---|
| Plan immutability | primary key `(id, version)` و reject برای تغییر همان نسخه | مناسب؛ upgrade با version جدید انجام می‌شود |
| Tenant isolation | هر entitlement و event با `tenant_id` ذخیره می‌شود | مناسب در datastore؛ API layer هنوز باید tenant claim را enforce کند |
| Feature gate | `check_feature()` status plan و allow-list feature را بررسی می‌کند | مناسب برای gate service-side؛ نباید فقط UI gate باشد |
| Meter idempotency | `idempotency_key` یکتا و invariant event payload | مناسب برای retry worker و webhook تکراری |
| Quota consistency | `BEGIN IMMEDIATE` پیش از aggregate و insert usage | مناسب برای SQLite single-writer؛ service مرکزی برای scale لازم است |
| Overage | `deny` یا `allow` و `overage_units` incremental | مناسب برای policy؛ charge هنوز خارج از scope است |
| Audit evidence | `ProjectStore.audit()` برای plan, assignment, usage و denial | مناسب برای trace اولیه؛ export immutable بیرونی در roadmap است |
| Metadata minimization | JSON canonical، حد 16KiB و deny-list PII/credential key | بهترشده؛ هیچ value-level DLP کامل ادعا نمی‌شود |

## اصلاح‌های v2.5.1

| یافته | ریسک پیشین | اصلاح | آزمون regression |
|---|---|---|---|
| Usage فاقد plan snapshot بود | بعد از upgrade/downgrade، export مالی نمی‌توانست plan حاکم بر رخداد تاریخی را با قطعیت نشان دهد | ستون‌های `plan_id`، `plan_version` و `entitlement_effective_from` با migration backward-compatible افزوده شد | ثبت رخداد قبل/بعد از upgrade و کنترل هر دو snapshot |
| deny-list metadata محدود بود | کلیدهای متغیر مانند `recipient_id`، `contactPhone` یا `apiToken` می‌توانستند وارد event شوند | match مبتنی بر fragment برای identity و credential keyهای رایج | سه variant nested/direct آزمون شد |

## API و authorization لازم پیش از production control plane

| operation | actor مجاز پیشنهادی | کنترل ضروری |
|---|---|---|
| create/retire plan | `billing_admin` با separation of duties | OIDC role، 4-eyes approval، immutable audit event |
| assign/upgrade tenant | `commercial_admin` | tenant scope، effective date، change ticket correlation |
| check feature | workload یا tenant-scoped service | signed tenant claim و deny by default |
| record usage | فقط workload identity worker | mTLS/OIDC workload token، queue job correlation و rate limit |
| read usage | tenant admin یا finance role | tenant isolation، period bounds و export audit |

Authorization داخل ماژول قرار نگرفته است، زیرا module باید از desktop، FastAPI control plane و worker قابل‌استفاده بماند. این یک **مرز معماری عمدی** است: caller production باید OIDC/SSO، SCIM role mapping و workload identity را قبل از فراخوانی اعمال کند.

## محدودیت‌های باقی‌مانده و اقدام پیشنهادی

| اولویت | محدودیت | دلیل | اقدام v2.6 |
|---|---|---|---|
| P0 پیش از invoice | preflight و enqueue یک reservation اتمیک مشترک نیستند | چند job می‌تواند quota باقی‌مانده را preflight کند و فقط در success metering شود | reservation ledger با TTL و release/consume transaction |
| P0 پیش از multi-worker | SQLite برای single-writer control plane محدود است | HA و scale worker به store مرکزی نیاز دارد | PostgreSQL + transactional outbox + leader/lease policy |
| P1 | billing-period بر مبنای string caller است | timezone/boundary باید توسط service policy تعیین شود | calendar service با timezone و close lock |
| P1 | metadata deny-list value-level DLP نیست | کلید سالم می‌تواند value PII داشته باشد | allow-list schema per meter + hash/correlation only |
| P1 | audit trail local است | نیاز enterprise به immutable export و SIEM وجود دارد | signed audit batch + OpenTelemetry/SIEM sink |
| P2 | price-book region/currency runtime ندارد | قیمت در SKU جداسازی شده ولی quote engine نیست | versioned price book و contract entitlement bridge |

## توصیهٔ اجرایی

برای pilot فعلی، `overage_behavior="deny"`، usage alert دستی در آستانهٔ 70/90 درصد و یک billing admin محدود استفاده شود. برای Enterprise contract، usage باید ابتدا به‌صورت monthly review و invoice draft export شود، نه auto-charge. auto-charge تنها پس از تکمیل reservation، access control، reconciliation و review حقوقی/مالیاتی قابل‌طرح است.

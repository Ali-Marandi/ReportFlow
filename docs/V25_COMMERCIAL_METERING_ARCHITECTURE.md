# ReportFlow v2.5 — Commercial Entitlements و Usage Metering

**وضعیت:** پیاده‌سازی و آزمون‌شده در `reportflow_app/commercial_v25.py`  
**هدف:** تبدیل price hypothesisهای Team/Growth/Enterprise به کنترل محصول قابل‌آزمون، بدون ذخیرهٔ دادهٔ پرداخت، کارت، invoice یا recipient PII.

## مسئله

مدل platform subscription به‌تنهایی value متفاوت مشتریان را پوشش نمی‌دهد. یک tenant که صدها report را با destination governed تحویل می‌دهد، هزینه و ارزش متفاوتی از یک workspace کم‌مصرف ایجاد می‌کند. در عین حال، billing بر مبنای failure یا attemptهای ناشی از platform اعتماد مشتری را کاهش می‌دهد. بنابراین v2.5 متر اصلی را **`successful_delivery`** تعریف می‌کند و آن را فقط پس از completion موفق worker ثبت می‌کند.

## اجزای پیاده‌سازی

| جزء | مسئولیت | کنترل امنیتی |
|---|---|---|
| `CommercialPlan` | feature flagها، meter limitها، SKU و overage behavior نسخه‌دار | plan immutable است؛ تغییر نیازمند version جدید است |
| `TenantEntitlement` | انتساب tenant به plan و override مجاز | tenant-scoped، status-aware و audit‌شده |
| `CommercialCatalog` | persistence plan، subscription، usage و summary | SQLite transaction، idempotency key یکتا و audit trail |
| `UsageEvent` | رخداد مصرف قابل‌انتساب به یک tenant و period | metadata محدود به 16KiB؛ credential و email رد می‌شود |
| `CommercialDistributionGate` | gate پیش از queue enrollment و ثبت usage پس از success | entitlement + quota preflight پیش از enqueue؛ usage فقط در success |

## flow عملیاتی

```text
Tenant entitlement
        ↓
Feature check: distribution_queue
        ↓
Quota preflight: successful_delivery
        ↓
DistributionQueue.enqueue()
        ↓
Worker completes job successfully
        ↓
record_success(job_id) → idempotent UsageEvent
        ↓
Usage summary / future billing export
```

`preflight_usage()` رخداد billable نمی‌سازد؛ فقط بررسی می‌کند که tenant active است و hard cap نقض نمی‌شود. `record_success()` کلید idempotency determinisitic از job ID می‌سازد، بنابراین retry worker یا webhook تکراری دوبار usage ثبت نمی‌کند.

## Plan snapshot و migration

هر tenant به `plan_id` و `plan_version` مشخص متصل است. تغییر تعریف یک plan version موجود رد می‌شود، زیرا invoice explanation و entitlement dispute بدون snapshot immutable قابل‌دفاع نیست. ارتقا یا downgrade باید با ساخت plan version جدید و assign مجدد tenant انجام شود؛ پس از آن summaryهای period قبلی همچنان به limit همان plan snapshot قابل ردیابی‌اند.

## Overage policy

| رفتار | کاربرد | عملکرد |
|---|---|---|
| `deny` | pilot، Team و مشتری با budget سخت | preflight و record از عبور quota جلوگیری می‌کنند؛ admin باید quota یا plan را تغییر دهد |
| `allow` | Enterprise با قرارداد usage | رخداد ثبت می‌شود و `overage_units` incremental نگه‌داری می‌شود |

Auto-charge، payment method، invoice و tax calculation در محدودهٔ این ماژول نیستند. اتصال به provider پرداخت تنها پس از انتخاب seller-of-record، region، tax nexus، DPA و customer contract انجام می‌شود.

## API پیشنهادی برای control plane بعدی

| endpoint | رفتار |
|---|---|
| `GET /v1/tenants/{tenant}/entitlements` | feature و plan snapshot بدون data پرداخت |
| `GET /v1/tenants/{tenant}/usage?period=YYYY-MM` | usage، quota، remaining و overage بر حسب meter |
| `POST /v1/admin/plans` | ایجاد plan immutable با authorization admin |
| `POST /v1/admin/tenants/{tenant}/assignment` | assign/downgrade/upgrade plan با audit event |
| `POST /v1/workers/usage/delivery-success` | ثبت success از worker با workload identity و job correlation |

هر endpoint باید tenant isolation، SSO/SCIM role، request idempotency و rate limit داشته باشد. هیچ endpointی نباید raw payment credential یا recipient detail را بازگرداند.

## ارتباط با pricing strategy

این زیرساخت مدل hybrid را ممکن می‌کند: platform fee برای feature pack، allowance برای value قابل‌پیش‌بینی و usage overage فقط برای scale واقعی. قیمت واقعی قبل از سه pilot نباید hard-code شود. `commercial_sku` یک شناسهٔ محصولی است، نه مبلغ؛ این جداسازی امکان region-based price book و قرارداد enterprise بدون تغییر runtime entitlement را می‌دهد.

## آزمون و کنترل کیفیت

| کنترل | نتیجه |
|---|---|
| plan immutability | پوشش داده‌شده |
| tenant feature isolation و override | پوشش داده‌شده |
| idempotent metering و hard quota | پوشش داده‌شده |
| overage incremental | پوشش داده‌شده |
| distribution entitlement gate | پوشش داده‌شده |
| منع PII و credential در usage metadata | پوشش داده‌شده |
| regression کامل | `46 passed` |
| dependency audit | `No known vulnerabilities found` |
| Bandit / syntax / diff check | پاس |

## مرزهای بعدی

v2.6 باید export billable usage به data warehouse، usage alertهای 70/90/100 درصد، price-book منطقه‌ای، feature-policy GitOps و dashboard cohort را اضافه کند. تا آن زمان، entitlement و usage باید برای pilot و sales-assist استفاده شوند، نه صدور invoice خودکار.

# طرح محصول، معماری و GTM ReportFlow v2.1

## هدف v2.1

v2.1 ReportFlow باید از یک ابزار ساخت و توزیع گزارش محلی به یک **control plane گزارش‌گری سازمانیِ حاکمیت‌شده** تکامل یابد. تمایز اصلی محصول نه «تولید یک فایل PDF»، بلکه تولید یک گزارش قابل‌ردیابی، شخصی‌سازی‌شده و مبتنی بر تعریف مشترک KPI است؛ به‌گونه‌ای که هر عدد، مخاطب، filter، منبع داده و delivery تصمیم قابل‌ممیزی داشته باشد.

> **اصل محصول:** محاسبه و policy به‌صورت deterministic اجرا می‌شوند؛ AI تنها بر روی evidence حاکمیت‌شده روایت، توضیح و پیشنهاد تولید می‌کند.

## 1. معماری Report Bursting v2.1

### 1.1 جریان اجرا

```text
Recipient Mapping Dataset
        │ validate schema / domain / policy
        ▼
Recipient Resolver ──► Recipient × Filter Manifest
        │                         │
        │                         ▼
        │                  Semantic/Data Policy
        ▼                         │
Report Renderer ◄──── scoped DataFrame (per recipient)
        │
        ▼
Delivery Adapter (dry-run → approval → destination)
        │
        ▼
Signed/hashed Delivery Manifest + Audit Event
```

مدل `recipient mapping` از data set گزارش جداست و فقط شامل شناسهٔ مخاطب، آدرس delivery، فیلترهای مجاز، optional subject/context و classification است. این الگو با dynamic per-recipient subscription هم‌راستاست؛ در آن، mapping مخاطب و filterها جدا از محتوای گزارش نگه‌داری می‌شوند و جدیدترین mapping هنگام اجرا تعیین‌کننده است.[1]

| کنترل v2.1 | پیاده‌سازی | اثر تجاری/امنیتی |
|---|---|---|
| Mapping data-driven | تبدیل dataframe mapping به recipientهای deterministic | حذف CSVهای دستی و کاهش خطای عملیاتی |
| Filterهای چندبعدی allowlisted | تنها filter fieldهای ثبت‌شده و operatorهای مجاز | کاهش نشت cross-tenant/region |
| Delivery policy | domain allowlist، max recipients، max rows و classification | کنترل توزیع خارج از policy |
| Dry-run و approval | پیش‌فرض dry-run؛ external delivery نیازمند approval | کاهش ارسال ناخواسته |
| Manifest hash | هش artifact، filter fingerprint و outcome در manifest | قابل‌ردیابی، non-repudiation عملیاتی |
| Retry/queue قراردادمحور | result idempotency و status قابل‌گسترش | آماده‌سازی برای worker مرکزی v2.2 |

### 1.2 مقصدهای v2.1 و v2.2

v2.1 destinationهای `secure_folder` و SMTP کنترل‌شده را نگه‌می‌دارد و manifest delivery می‌سازد. برای channelهای بیرونی، v2.2 باید queue و idempotency key داشته باشد؛ هر connector ارسال باید allowlist، secret reference، TLS و policy مستقل داشته باشد. اتصال webhook یا Slack/Teams نباید پیش از بررسی رسمی قابلیت webhook سرویس و review امنیت فعال شود.

## 2. connectorهای پایگاه دادهٔ پیشرفته

v2.1 یک `ConnectionPolicy` مشترک معرفی می‌کند. این policy شامل host allowlist، private CIDR صریح، TLS verification، timeout، max rows، statement timeout و query tag است. Validation client فقط defense-in-depth است؛ database principal همچنان باید read-only و tenant-scoped باشد.

| Connector | قابلیت v2.1 | policy پیش‌فرض production |
|---|---|---|
| PostgreSQL | read-only transaction، statement timeout، bounded result، SSL | `sslmode=verify-full`، root CA، role کمینه و در صورت نیاز RLS |
| SQL Server | ODBC 18+، Encrypt، certificate validation، ApplicationIntent=ReadOnly | `TrustServerCertificate=no`، login read-only، allowlisted host |
| MySQL | TLS verify، read-only query، bounded result | account SELECT-only، CA verification |
| Snowflake | optional `snowflake-connector-python`، warehouse/database/schema allowlist | role کمینه، network policy و key/token از Secret Manager |
| Databricks SQL | optional `databricks-sql-connector`، HTTP path و warehouse allowlist | personal token در Secret Manager، egress policy و result cap |

PostgreSQL در محیط حساس `sslmode=verify-full` را برای تأیید chain و hostname توصیه می‌کند؛ default `prefer` امنیت کافی ندارد. همچنین RLS تنها وقتی policyهای مناسب فعال‌اند مؤثر است و نقش‌های owner/superuser می‌توانند آن را دور بزنند.[2] [3]

## 3. Semantic Layer v2.1

Semantic Layer باید به‌جای نگه‌داری صرف metricها، یک **semantic contract versioned** باشد: metric definition، dimension، grain، lineage، owner، certification، sensitivity، quality checks، freshness SLA و deprecation policy. مدل منتشرشده immutable است؛ تغییر معنی KPI نسخهٔ جدید می‌سازد، نه overwrite silent.

| جزء | رفتار v2.1 | معیار پذیرش |
|---|---|---|
| Metric contract | aggregation، format، owner، sensitivity، certification و synonym | هر metric published دارای owner و lineage است |
| Filter policy | `eq`، `in`، `between` و `is_null` فقط روی dimension allowlisted | LLM و burst نمی‌توانند field آزاد ارسال کنند |
| Lineage | dataset/connector، source field، model version، freshness و quality state | هر insight و artifact به definition قابل‌ردیابی است |
| Certification workflow | draft → review → published → deprecated | Copilot production فقط metric published/certified را می‌بیند |
| Semantic tests | expected metric result روی dataset نمونه | CI مانع drift definition می‌شود |

Looker و Microsoft هر دو بر این اصل تأکید دارند که AI برای تحلیل قابل اعتماد باید به semantic model آماده‌شده و business definitionهای حاکمیت‌شده متصل باشد، نه schema خام یا SQL آزاد.[4] [5]

## 4. AI Copilot v2.1

Copilot یک agent SQL-generator نیست. این قابلیت از چهار لایه تشکیل می‌شود:

1. **Intent routing:** سؤال کاربر به intent محدود مانند summary، variance، outlier explanation یا metric glossary نگاشت می‌شود.
2. **Deterministic evidence:** Semantic Engine metricها و filterهای مجاز را محاسبه می‌کند؛ در این مرحله LLM به database/connector/secret دسترسی ندارد.
3. **Narrative generation:** provider فقط evidence cardهای ساختاریافته، glossary، quality/freshness و policy را می‌بیند و JSON schema تحویل می‌دهد.
4. **Verification and approval:** citation metric، model version، assumption، confidence و `needs_review` validate می‌شوند؛ پاسخ با missing evidence یا sensitivity غیرمجاز منتشر نمی‌شود.

### پاسخ ساختاریافتهٔ هدف

```json
{
  "summary": "…",
  "evidence": [{"metric_id": "net_revenue", "value": 125000, "semantic_version": "2.1.0"}],
  "drivers": ["…"],
  "assumptions": ["…"],
  "recommended_actions": [{"action": "…", "rationale_metric_ids": ["net_revenue"]}],
  "confidence": "medium",
  "needs_review": true
}
```

Copilot باید به‌صورت پیش‌فرض از contextهای دارای `restricted`/`confidential` عبور کند مگر policy نقش و deployment اجازه دهد. prompt، token، raw PII و credential در audit یا response ذخیره نمی‌شوند. حریم Copilot Power BI نیز بر استفاده از semantic model و prompt تأکید دارد؛ ReportFlow باید همین boundary را با policy محلی enforce کند.[5]

## 5. قابلیت‌های تجاری بعدی

| اولویت | قابلیت | ارزش | زمان پیشنهادی |
|---:|---|---|---|
| P0 | Delivery manifest، multi-filter bursting، DB policy و result caps | امنیت و enterprise readiness | v2.1 |
| P0 | Certification/freshness/quality semantic contract و Copilot evidence card | اعتماد به AI و KPI | v2.1 |
| P1 | Approval workflow چهارچشمی، immutable audit export و retention policy | انطباق و فروش regulated | v2.2 |
| P1 | Worker مرکزی، job queue، retry/idempotency و rate limit | مقیاس delivery | v2.2 |
| P1 | SharePoint/S3/Azure Blob destination با customer-managed key | delivery سازمانی | v2.2 |
| P1 | Observability dashboard: SLA، freshness، burst success، cost/token | عملیات و expansion | v2.2 |
| P2 | Metric marketplace، semantic GitOps و promotion pipeline | platform adoption | v2.3 |
| P2 | Anomaly detection deterministic + narrative Copilot | insight proactive | v2.3 |
| P2 | Embedded portal، white-label و external-client tenancy | OEM/channel revenue | v2.4 |

## 6. Enterprise GTM Strategy

### 6.1 ICP و wedge

نقطهٔ ورود، تیم‌های Finance Operations، Sales Operations و Client Reporting در سازمان‌های 200 تا 2,000 نفره هستند که گزارش‌های recurring، دستی و حساس به محرمانگی تولید می‌کنند. پیام اصلی: **«گزارش شخصی‌سازی‌شده و قابل‌ممیزی، بدون تکثیر spreadsheet و بدون سپردن KPI به AI غیرقابل‌کنترل.»**

| ICP | pain قابل‌سنجش | use case wedge | buyer group |
|---|---|---|---|
| Finance/FP&A | بستن دوره و distribution تکراری | regional/cost-center performance packs | CFO، FP&A lead، IT security |
| Sales Ops | pipeline و territory updates متعدد | manager/territory burst | CRO Ops، RevOps، CRM owner |
| B2B Client Ops | گزارش مشتری و SLA | client-specific operational packs | COO، CS leader، data platform |
| Regulated mid-market | کنترل distribution و audit نیازمند | governed KPI + secure delivery | Compliance، CISO، business owner |

### 6.2 offer و packaging

| offer | هدف | محدوده | معیار خروج |
|---|---|---|---|
| Discovery workshop | qualification | 2 ساعت، map داده/recipient/risk | ارزش use case و sponsor مشخص |
| Paid Proof of Value | اثبات ارزش | 10 روز، 1 connector، 1 semantic model، 1 burst | دقت KPI، delivery success و time saved سنجیده شود |
| Enterprise Foundation | land | SSO/SCIM، central secrets، 3 connector، 3 burst | security review و production sign-off |
| Enterprise Scale | expand | worker، destinations، observability، premium support | adoption در business unit دوم |

قیمت‌گذاری دقیق باید بعد از مصاحبه و willingness-to-pay محلی تعیین شود؛ model پیشنهادی، platform fee + connector/worker capacity + distribution volume است و نه قیمت‌گذاری صرفاً بر مبنای صندلی. راهنمای GTM Stripe بر پیوند ICP، value proposition، pricing، sales/distribution، launch، KPI و governance در یک برنامهٔ مشترک تأکید دارد.[6]

### 6.3 برنامهٔ 180 روزه

| بازه | محصول | GTM | KPI leading |
|---|---|---|---|
| روز 0–30 | v2.1 RC و security evidence | 20 discovery interview در دو vertical | interview→qualified ratio، sponsor rate |
| روز 31–60 | POV kit و demo dataset | 5 POV پولی هدف‌گذاری شود | time-to-first-burst، POV activation |
| روز 61–90 | approval/worker beta | case study با دادهٔ anonymized | POV→production conversion |
| روز 91–120 | Enterprise Foundation GA | ABM برای accountهای مشابه | pipeline coverage، security review pass rate |
| روز 121–180 | scale destinations و observability | partner motion با integratorها | expansion rate، retention، gross margin proxy |

### 6.4 enablement فروش

Demo باید سه لحظه را نشان دهد: اتصال read-only به داده، تعریف KPI certified، و delivery شخصی‌سازی‌شده با manifest/audit. Sales engineer نباید secret مشتری، دادهٔ واقعی یا قابلیت AI بدون evidence را در demo عمومی استفاده کند. هر فرصت Enterprise به یک mutual action plan با business sponsor، security owner، data owner و procurement milestone نیاز دارد.

## منابع

[1]: https://learn.microsoft.com/en-us/power-bi/collaborate-share/power-bi-dynamic-report-subscriptions "Microsoft Learn — Dynamic per-recipient subscriptions"
[2]: https://www.postgresql.org/docs/current/libpq-ssl.html "PostgreSQL — SSL Support"
[3]: https://www.postgresql.org/docs/current/ddl-rowsecurity.html "PostgreSQL — Row Security Policies"
[4]: https://cloud.google.com/blog/products/business-intelligence/how-lookers-semantic-layer-enhances-gen-ai-trustworthiness "Google Cloud — Looker semantic layer and trusted AI"
[5]: https://learn.microsoft.com/en-us/fabric/fundamentals/copilot-power-bi-privacy-security "Microsoft Learn — Copilot privacy, security, and responsible use"
[6]: https://stripe.com/resources/more/what-is-a-go-to-market-strategy-a-quick-gtm-guide-for-startups "Stripe — GTM Strategy Guide"

## Cover

# ReportFlow Enterprise
### دستاوردهای v2.2 تا v2.4 و نقشه‌راه رشد سازمانی
#### وضعیت محصول، حاکمیت داده و مسیر انتشار امن — اوت ۲۰۲۶

## Slide 1

# از Desktop Reporting تا Control Plane سازمانی

- **v2.2:** تحویل قابل‌اعتماد، portal چندمستاجری و تشخیص ناهنجاری
- **v2.3:** approval policy، جداسازی وظایف و ledger قابل‌ممیزی
- **v2.4:** lineage و impact graph از field تا destination
- نتیجه: گزارش از یک فایل خروجی به یک دارایی governed تبدیل شده است

## Slide 2

# v2.2 تحویل را پایدار و مقیاس‌پذیر کرد

- صف توزیع با idempotency، lease، retry نمایی و dead-letter queue
- مقصدهای S3 و Azure Blob با checksum، conditional create و metadata طبقه‌بندی
- White-label portal با tenant isolation، session امضاشده و report grants
- MAD rolling برای anomaly detection، deduplication و human review

## Slide 3

# v2.3 کنترل چهارچشمی را وارد جریان توزیع کرد

- approval مبتنی بر policy و role coverage برای داده‌های حساس
- requester نمی‌تواند گزارش خود را تأیید کند؛ هر approver یک تصمیم دارد
- fingerprint artifact و destination، تغییر پس از approval را مسدود می‌کند
- ledger هش‌زنجیره‌ای/HMAC، ترتیب و تمامیت رویدادهای governance را قابل‌بررسی می‌سازد

## Slide 4

# v2.4 اثر هر تغییر را قابل‌مشاهده می‌سازد

- graph پایدار: Dataset → Field → Metric/Dimension → Semantic Model → Report → Burst → Destination
- impact analysis downstream برای تغییر schema، stale data و metric deprecation
- traversal upstream برای بررسی منبع یک مقصد یا artifact حساس
- cycle prevention، metadata canonical و منع credential در graph

## Slide 5

# کیفیت و اعتماد در یک evidence chain جمع می‌شوند

- Semantic Contract v2.1: grain، owner، certification، freshness و quality rule
- Evidence Card: metric، filter، lineage، sensitivity و freshness در یک شاهد قابل‌مصرف
- v2.2 anomaly registry: تشخیص، deduplication و چرخهٔ بررسی انسانی
- گام بعد: انتقال data-quality label و anomaly به consumerهای downstream

## Slide 6

# CI و release به‌صورت امنیتی تفکیک شده‌اند

- Windows CI v2.2: 33 آزمون پاس، SBOM، audit وابستگی و artifact unsigned
- پس از v2.4: 41 آزمون کامل پاس، `pip-audit` و Bandit بدون finding
- build روی runner میزبانی‌شده؛ signing فقط روی Windows runner اختصاصی و HSM/KSP
- release رسمی منتظر Environment محافظت‌شده و گواهی Authenticode معتبر است

## Slide 7

# GitOps policy، کنترل را تکرارپذیر می‌کند

- desired state به‌صورت YAML versioned و immutable در Git
- pipeline: lint → simulation → CODEOWNERS review → attestation → promotion → reconciliation
- Environment production: required reviewer، منع self-review، tag rule و secret پس از approval
- drift detection و rollback با commit قبلی، نه تغییر دستی production

## Slide 8

# CMK/BYOK حاکمیت کلید مشتری را حفظ می‌کند

- Envelope encryption: DEK برای artifact و KEK مشتری‌مالک برای wrap
- فقط key reference و version در metadata؛ raw key و token هرگز ذخیره نمی‌شوند
- Azure Key Vault/Managed HSM، AWS KMS یا HSM محلی پشت یک KeyProvider واحد
- rotation با dual-read و rewrap؛ revoke/destroy تنها با approval و retention check

## Slide 9

# نقشه‌راه: از visibility به autonomous governance

- **v2.5:** KeyProvider واقعی، policy schema validator، drift detection و SIEM/OpenTelemetry
- **v2.6:** data-quality labels، sensitivity propagation و lineage UI در portal
- **v2.7:** semantic GitOps promotion، CMK/BYOK production و retention automation
- **v2.8:** Governance Copilot مبتنی بر evidence و پرسش‌های audit-ready

## Slide 10

# معیار موفقیت: اعتمادپذیری، کنترل‌پذیری، مقیاس

- هر artifact حساس: lineage، classification، approval و integrity evidence دارد
- هر تغییر داده: impact analysis و owner notification پیش از promotion دارد
- هر انتشار: SBOM، provenance، امضای معتبر و checksum قابل‌تأیید دارد
- هر tenant: policy و key scope مستقل با visibility متمرکز دارد

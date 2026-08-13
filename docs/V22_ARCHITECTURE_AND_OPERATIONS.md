# معماری و عملیات ReportFlow v2.2

## هدف و مرز اجرا

v2.2 مسیر distribution را از desktop client جدا می‌کند. Desktop یا control plane فقط job تأییدشده را ثبت می‌کند؛ **worker سروری** artifact را از مسیر امن می‌گیرد، destination مورد تأیید را resolve می‌کند و نتیجه را در audit ثبت می‌نماید. هیچ credential، service connection string یا token در payload صف، manifest یا executable ذخیره نمی‌شود.

```text
Desktop / Admin Control Plane
       │ approved job + idempotency key
       ▼
Persistent DistributionQueue ──► Worker lease ──► Destination Registry
       │                                  │                ├─ S3 (KMS + SHA-256)
       ├─ Retry/backoff                    │                └─ Azure Blob (Entra + checksum)
       └─ DLQ + audit                      ▼
                              Delivery outcome + artifact integrity record
```

> **قانون عملیاتی:** یک job ممکن است بیش از یک بار اجرا شود؛ artifact نباید بیش از یک بار منتشر شود. idempotency key، conditional create و metadata hash باید با هم این تضمین را بسازند.

## 1. صف توزیع و Retry

`DistributionQueue` در v2.2 یک صف SQLite قابل‌استقرار برای single-node/small-cluster control plane است. enqueue بر اساس `idempotency_key` یکتا است؛ worker با lease کوتاه job را claim می‌کند؛ خطای transient با exponential backoff به حالت `retry` می‌رود و خطای policy/authorization یا exhaustion به `dead_letter` تبدیل می‌شود. lease منقضی نیز به‌صورت کنترل‌شده recover می‌شود.

| وضعیت | معنا | اقدام مجاز |
|---|---|---|
| `queued` | job آمادهٔ claim است | cancel یا claim |
| `running` | worker دارای lease معتبر است | complete یا fail با همان lease token |
| `retry` | خطای transient با زمان اجرای بعدی | انتظار تا `available_at` |
| `succeeded` | delivery ثبت‌شده و immutable | فقط مشاهده/audit |
| `dead_letter` | تلاش تمام شده یا خطای non-retryable | بررسی human و ایجاد job جدید با key جدید |
| `cancelled` | پیش از claim لغو شده | فقط مشاهده/audit |

SQLite در v2.2 برای foundation و یک worker استفاده می‌شود. برای scale چند-زون یا throughput بالا، queue backend باید به managed broker/database با transaction/lease semantics معادل منتقل شود و payload schema، idempotency policy و audit API بدون تغییر باقی بمانند.

## 2. destinationهای S3 و Azure Blob

### S3

`S3ArtifactDestination` از object key immutable، `If-None-Match: *`، SHA-256، metadata شامل idempotency key و SHA-256 و encryption KMS اختیاری استفاده می‌کند. در صورت وجود object، فقط وقتی موفقیت idempotent پذیرفته می‌شود که hash و key موجود دقیقاً با job برابر باشند. S3 از checksumهای upload پشتیبانی می‌کند و conditional write روی تعارض باید با retry کنترل‌شده انجام شود.[1] [2]

### Azure Blob

`AzureBlobArtifactDestination` با `DefaultAzureCredential` برای workload identity و `overwrite=False`/`if_none_match="*"` نوشته شده است. metadata، digest و key را ثبت می‌کند و duplicate تنها وقتی پذیرفته می‌شود که metadata object موجود دقیقاً مطابق job باشد. Azure Blob برای write همزمان strategy کنترل concurrency لازم دارد و transfer validation/checksum بخشی از integrity upload است.[3]

| کنترل | S3 | Azure Blob |
|---|---|---|
| هویت production | IAM workload role با privilege کمینه | Microsoft Entra workload identity با Storage Blob Data Contributor محدود به container |
| جلوگیری از overwrite | `If-None-Match: *` | `overwrite=False` و conditional create |
| integrity | SHA-256 request/metadata | validate content و SHA-256 metadata |
| encryption | SSE-KMS با key policy محدود | encryption-at-rest و scope/key policy سازمانی |
| retry | فقط خطای transient؛ policy failure به DLQ | فقط خطای transient؛ conflict/idempotency بررسی شود |

## 3. Embedded White-label Portal

Portal یک server-side adapter است، نه یک view محلی در exe. هویت اصلی از OIDC/SSO موجود می‌آید؛ پس از احراز هویت، backend membership tenant را validate و session امضاشدهٔ حداکثر ۱۵ دقیقه‌ای صادر می‌کند. browser هرگز tenant ID، report ID یا theme را authority تلقی نمی‌کند.

| لایه | کنترل |
|---|---|
| Tenant | ID محدود، status فعال/معلق و brand profile validated |
| Brand | فقط display name، hex color و HTTPS URL؛ CSS/JavaScript دلخواه پذیرفته نمی‌شود |
| Session | HMAC با secret مرکزی، short TTL، nonce و grant snapshot |
| Report | grant per tenant، classification و بررسی دوباره در هر access |
| Revocation | حذف/غیرفعال‌سازی grant sessionهای پیشین را نامعتبر می‌کند |
| HTTP | TLS در reverse proxy، `no-store`، CSP، `nosniff` و عدم نمایش stack trace |

RLS، OLS و isolation بر مبنای workspace/data model از الگوهای استاندارد embedded analytics هستند؛ ReportFlow باید tenant isolation را هم در portal grant و هم در semantic/database policy enforce کند، نه فقط در UI.[4]

## 4. Anomaly Detection

`RobustAnomalyDetector` به جای black-box مدل غیرقابل‌توضیح، median/MAD rolling را اجرا می‌کند. برای هر point، تنها history پیشین در baseline استفاده می‌شود و finding شامل observed value، baseline median، deviation، robust z-score، direction، severity و evidence نسخهٔ semantic/freshness/quality است. هر finding به‌طور پیش‌فرض نیازمند بازبینی انسانی است و `AnomalyRegistry` با idempotency key از alert تکراری جلوگیری می‌کند.

| گام | رفتار |
|---|---|
| ورودی | timestamp یکتا و value عددی در grain ثابت، به‌همراه metric/semantic version |
| baseline | rolling median و MAD از data history؛ حداقل ۸ observation |
| gate | minimum deviation و robust z-score allowlisted |
| finding | statement قابل‌توضیح، evidence و severity؛ بدون ادعای علت |
| review | analyst وضعیت `acknowledged`، `investigating`، `dismissed` یا `resolved` و rationale ثبت می‌کند |
| Copilot | فقط finding + metric evidence را برای narrative دریافت می‌کند؛ علت قطعی نمی‌سازد |

## 5. دو مسیر استقرار پیشنهادی

| رویکرد | مناسب برای | trade-off | هزینه | پیچیدگی setup |
|---|---|---|---|---|
| **سرویس مدیریت‌شده با worker دائم** | اغلب مشتریان Enterprise با یک worker، portal و jobهای recurring | مدیریت‌شده و سریع‌تر؛ محدودیت منابع سرویس باید با حجم burst سنجیده شود | شروع کم‌هزینه و usage-based | متوسط |
| **سرویس خصوصی اختصاصی با worker/scheduler** | نیاز به driver سفارشی، ابزار OS، شبکهٔ خصوصی سخت‌گیرانه یا بار فراتر از worker کوچک | کنترل کامل‌تر؛ مسئولیت patch، monitoring، backup و هزینهٔ زیرساخت بیشتر | هزینهٔ زیرساخت مستقل | زیاد |

برای شروع production، مسیر اول مناسب است اگر runtime managed بتواند connectorها و حجم موردنیاز را پشتیبانی کند. مسیر دوم تنها زمانی انتخاب شود که نیاز قطعی به OS-level integration، private network یا منابع بیشتر وجود دارد. در هر دو حالت، worker باید مستقل از desktop client باقی بماند.

## 6. Runbook اجرای یک artifact job

1. Distribution owner artifact و recipient/tenant policy را approve می‌کند.
2. Control plane با `artifact_delivery_payload` payload بدون secret و key یکتا می‌سازد.
3. `DistributionQueue.enqueue` job را ثبت می‌کند؛ درخواست تکراری همان job را بازمی‌گرداند.
4. worker job را claim می‌کند، destination ID را در registry server-side resolve و upload را با conditional create اجرا می‌کند.
5. در موفقیت، audit شامل URI، SHA-256 و destination ID ثبت می‌شود. در خطای transient، worker retry می‌کند؛ در خطای policy یا بعد از تلاش‌های مجاز، job وارد DLQ می‌شود.
6. DLQ توسط operator بررسی می‌شود؛ پس از اصلاح policy/credential/path، job جدید با idempotency key جدید ساخته می‌شود.

## 7. پیش‌نیازهای انتشار v2.1

Release v2.1 باید چهار commit foundation (`e46a2ea` تا `a8d9f45`) را به `main` fast-forward کند و tag annotated `v2.1.0` بسازد. workflow موجود سپس آزمون Windows، SBOM، artifact signing، Authenticode verify، attestation و GitHub Release را در محیط protected اجرا می‌کند. اجرای واقعی منوط به signer خصوصی، environment approval و credential دارای write permission است.

## References

[1]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html "AWS — Checking object integrity in Amazon S3"
[2]: https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html "AWS — PutObject API"
[3]: https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-upload "Microsoft Learn — Upload a blob"
[4]: https://learn.microsoft.com/en-us/power-bi/developer/embedded/embedded-row-level-security "Microsoft Learn — Security features in embedded analytics"

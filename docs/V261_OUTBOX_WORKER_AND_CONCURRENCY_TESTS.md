# ReportFlow v2.6.1 — بازبینی Outbox Worker و آزمون‌های هم‌زمانی

**وضعیت:** نمونهٔ server-side برای control plane.  
**تاریخ اعتبارسنجی محلی:** ۱۴ اوت ۲۰۲۶.  
**دامنه:** انتشار رویدادهای transactional outbox و admission سهمیه در PostgreSQL؛ خارج از دامنهٔ این سند payment، invoice، tax و نگه‌داری payment credential است.

## 1. مدل اجرای worker

`TransactionalOutboxWorker` یک worker **one-pass** و deterministic است. این کلاس نه loop بی‌پایان، نه sleep و نه connection بلندمدت دارد؛ یک supervisor/runtime بیرونی cadence را تعیین می‌کند. هر invocation ابتدا یک batch محدود را claim می‌کند، سپس هر event را با `event_id` به‌عنوان idempotency key به broker adapter می‌فرستد و فقط بعد از بازگشت موفق adapter، acknowledgement دیتابیس را انجام می‌دهد.

> این الگو **at-least-once** است، نه exactly-once. اگر publisher پس از publish و پیش از acknowledgement crash کند، event دوباره قابل‌انتشار می‌شود؛ consumer باید `event_id` را deduplicate کند.

| جزء | پیاده‌سازی | کنترل شکست |
|---|---|---|
| Claim | CTE با `FOR UPDATE SKIP LOCKED` روی eventهای `published_at IS NULL` و `available_at <= now()` | publisherهای هم‌زمان ردیف‌های قفل‌شده را skip می‌کنند، نه این‌که پشت یک ردیف منتظر بمانند |
| Lease | `lease_token`، `lease_owner` و `lease_expires_at` در همان transaction claim ثبت می‌شود | crash publisher پس از انقضای lease قابل recovery است |
| Publish | `sink.publish(event_type, payload, idempotency_key=event_id)` | adapter failure در ledger ثبت می‌شود؛ event حذف نمی‌شود |
| Ack | `mark_outbox_published` token، owner و زمان انقضای lease را کنترل می‌کند | publisher منقضی یا نادرست نمی‌تواند event را publish‌شده علامت بزند |
| Retry | `defer_outbox` lease را پاک و `available_at` را با delay محدود به آینده منتقل می‌کند | retry بعدی به‌جای busy-loop اجرا می‌شود |
| Isolation | `publisher_id` جزئی از lease state است | ack یا defer توسط publisher دیگر رد می‌شود |

طبق مستند رسمی PostgreSQL، `SKIP LOCKED` ردیف‌هایی را که فوراً lock نمی‌شوند رد می‌کند و برای وضعیت‌هایی مانند queue مناسب است، در حالی که برای view عمومی سازگار طراحی نشده است. همچنین `FOR UPDATE` ردیف انتخاب‌شده را تا پایان transaction در برابر update و lock متعارض محافظت می‌کند. [1] [2]

## 2. مسیر کد

| فایل | مسئولیت |
|---|---|
| `reportflow_app/postgres_quota_v26.py` | `claim_outbox`، `mark_outbox_published`، `defer_outbox` و `TransactionalOutboxWorker` |
| `migrations/postgres/002_v261_outbox_worker_leases.sql` | `available_at`، `lease_owner` و index claim برای eventهای publish‌نشده |
| `tests/test_outbox_worker_v261.py` | publish موفق، failure/retry و lease-race بدون توقف کل batch |
| `tests/integration/test_postgres_quota_v261_concurrency.py` | آزمون واقعی PostgreSQL با threadهای هم‌زمان |

query claim به‌صورت مفهومی چنین عمل می‌کند:

```sql
WITH candidates AS (
  SELECT id
  FROM rf_outbox_events
  WHERE published_at IS NULL
    AND available_at <= now()
    AND (lease_expires_at IS NULL OR lease_expires_at < now())
  ORDER BY available_at, occurred_at
  LIMIT :batch_size
  FOR UPDATE SKIP LOCKED
)
UPDATE rf_outbox_events
SET lease_token = gen_random_uuid(),
    lease_owner = :publisher_id,
    lease_expires_at = now() + :lease_interval,
    publish_attempts = publish_attempts + 1
FROM candidates
WHERE rf_outbox_events.id = candidates.id;
```

transaction claim کوتاه است: event ابتدا claim می‌شود، transaction commit می‌شود و سپس publish شبکه‌ای بیرون از transaction رخ می‌دهد. بنابراین latency broker، lock دیتابیس را نگه نمی‌دارد. در عوض، lease و idempotency consumer مسئول مدیریت failure window هستند.

## 3. سناریوهای concurrency اضافه‌شده

| سناریو | setup | invariant مورد انتظار | نتیجهٔ اجرای واقعی |
|---|---|---|---|
| High contention quota | ۲۰ thread هم‌زمان برای ۵ واحد quota با policy `deny` | دقیقاً ۵ admission موفق؛ `held_units=5` و reservationهای `held=5` | پاس |
| Retry storm idempotency | ۱۲ thread با یک `idempotency_key` مشترک | فقط یک job و یک reservation؛ فقط یک پاسخ `created=True` | پاس |
| Two-publisher outbox claim | ۲ publisher هم‌زمان برای ۱۲ event و batch=6 | دو مجموعهٔ lease ناپوشا؛ هر publisher فقط leaseهای خودش را می‌بیند | پاس |
| Worker publish failure | sink اول fail و event بعدی success | event fail‌شده defer؛ event بعدی ack؛ batch متوقف نشود | پاس در unit test |
| Lease race | defer با lease نامعتبر بازگردد | worker batch را متوقف نکند؛ event durable باقی بماند | پاس در unit test |
| Clock-stable v2.2 queue regression | صف SQLite با زمان واقعی test harness | test وابسته به تاریخ ثابت تاریخی نباشد | پاس |

اجرای محلی شامل **۶۱ آزمون عادی pass، ۳ آزمون integration skip بدون DSN، و سپس ۳ آزمون PostgreSQL واقعی pass** روی PostgreSQL 16.14 ایزوله بود. `pip-audit` هیچ آسیب‌پذیری شناخته‌شده و Bandit هیچ finding برای ماژول PostgreSQL گزارش نکرد.

## 4. اجرای آزمون‌ها

```bash
# حالت عادی: integration testها بدون DSN skip می‌شوند
pytest -q

# فقط روی دیتابیس disposable و بدون دادهٔ مشتری
export REPORTFLOW_TEST_POSTGRES_DSN='postgresql://<isolated-test-user>@<test-host>/<test-db>?sslmode=verify-full'
pytest -q tests/integration/test_postgres_quota_v261_concurrency.py -m postgres_integration
```

fixture آزمون، schema را اعمال و جدول‌های test را `TRUNCATE` می‌کند. DSN هرگز نباید به production، staging مشترک، یا دیتابیسی شامل دادهٔ مشتری اشاره کند.

## 5. کنترل‌های باقی‌مانده پیش از production

| کنترل | دلیل | اقدام بعدی |
|---|---|---|
| Retry policy پویا | delay ثابت در نمونه برای جلوگیری از storm کافی نیست | exponential backoff با jitter و سقف attempt، سپس DLQ outbox |
| Publisher authorization | `publisher_id` باید به workload identity واقعی متصل شود | OIDC/mTLS و RBAC برای publisher role |
| Delivery idempotency | outbox فقط event را حفاظت می‌کند، نه side effect مقصد | broker consumer و destination adapter باید `event_id` را deduplicate کنند |
| Metrics و alert | lease expiry و outbox lag باید دیده شوند | metrics برای claim/publish/defer/expiry و alert lag |
| Resilience | serialization failure و deadlock ممکن است رخ دهند | retry محدود transaction با correlation ID و telemetry |
| Data retention | event payload ممکن است metadata تجاری داشته باشد | schema review، PII minimization و lifecycle retention تحت CMK/BYOK |

## References

[1]: https://www.postgresql.org/docs/current/sql-select.html "PostgreSQL Documentation — SELECT"
[2]: https://www.postgresql.org/docs/current/explicit-locking.html "PostgreSQL Documentation — Explicit Locking"

# ReportFlow v2.6 — نمونهٔ PostgreSQL Atomic Quota Reservation و Transactional Outbox

## هدف نمونه

فایل `reportflow_app/postgres_quota_v26.py` یک reference implementation سرور-محور برای admission اتمیک distribution job فراهم می‌کند. در هر admission موفق، یک bucket قفل می‌شود، یک reservation در حالت `held` ایجاد می‌شود، job ساخته می‌شود و یک outbox event در همان transaction ثبت می‌گردد. بنابراین commit موفق هیچ‌گاه hold بدون job یا job بدون hold باقی نمی‌گذارد.

این نمونه **payment service نیست**. کارت پرداخت، invoice، tax، پرداخت خودکار و PII recipient را نگه‌داری نمی‌کند. commercial grant باید از entitlement service معتبر بیاید، نه از desktop client یا body کنترل‌نشدهٔ API.

## فایل‌ها

| فایل | مسئولیت |
|---|---|
| `migrations/postgres/001_v26_atomic_quota_reservation.sql` | schema PostgreSQL، constraint، quota bucket، reservation ledger، immutable usage event و outbox |
| `reportflow_app/postgres_quota_v26.py` | admission، consume-success، terminal-release، outbox lease و acknowledgement |
| `tests/test_postgres_quota_v26.py` | validation input، idempotency invariant و guardrailهای transactional primitive |
| `docs/V26_ATOMIC_QUOTA_RESERVATION_ARCHITECTURE.md` | state machine، migration، observability و تصمیم‌های باز production |

## پیش‌نیاز و اعمال migration

وابستگی `psycopg[binary]>=3.1` در `requirements-enterprise.txt` تعریف شده است. DSN باید فقط در secret manager/control plane باشد. هیچ DSN، password یا connection string در desktop executable، repository، log یا metadata usage قرار نگیرد.

```bash
export REPORTFLOW_CONTROL_PLANE_DSN='postgresql://<workload-identity-or-secret>@<host>/<database>?sslmode=verify-full'
psql "$REPORTFLOW_CONTROL_PLANE_DSN" -v ON_ERROR_STOP=1 \
  -f migrations/postgres/001_v26_atomic_quota_reservation.sql
```

اجرای production باید از حساب migration جدا از حساب runtime استفاده کند. runtime role فقط به `SELECT/INSERT/UPDATE` جدول‌های لازم نیاز دارد و نباید permission `DROP`, `ALTER`, `CREATE EXTENSION` یا access به schemaهای نامرتبط داشته باشد.

## جریان server-side

```python
from datetime import UTC, date, datetime
from reportflow_app.postgres_quota_v26 import (
    AdmissionRequest, PostgresQuotaReservationService, QuotaGrant,
)

# Values shown here are issued by authenticated entitlement/calendar services,
# not accepted as untrusted fields from a desktop client.
grant = QuotaGrant(
    tenant_id="tenant-alpha",
    meter="successful_delivery",
    billing_period=date(2026, 8, 1),
    quota_scope_id="growth-v2-2026-08",  # immutable subscription-period grant
    plan_id="growth-v2",
    plan_version=2,
    entitlement_effective_from=datetime(2026, 8, 1, tzinfo=UTC),
    overage_behavior="deny",
    included_units=1_000,
)
service = PostgresQuotaReservationService(os.environ["REPORTFLOW_CONTROL_PLANE_DSN"])
result = service.admit(AdmissionRequest(
    grant=grant,
    idempotency_key="distribution:tenant-alpha:request-42",
    kind="report-delivery",
    payload={"report_id": "monthly-summary"},
    quantity=1,
    reservation_ttl_seconds=300,
    actor_subject="workload:control-plane-api",
))
```

`quota_scope_id` باید به یک grant تغییرناپذیر entitlement+period اشاره کند. اگر یک tenant در میانهٔ period upgrade شود، grant جدید scope جدید می‌گیرد؛ usage و reservationهای قبلی همچنان با snapshot اولیه قابل reconciliation می‌مانند.

## Outbox publisher

`claim_outbox()` eventها را با `FOR UPDATE SKIP LOCKED` lease می‌کند. publisher باید event را به broker منتخب منتشر کند و **پس از دریافت acknowledgement broker**، `mark_outbox_published()` را صدا بزند. این مدل at-least-once است؛ consumer broker باید با `event_id` یا `dedupe_key` idempotent باشد.

```text
loop:
  events = service.claim_outbox(publisher_id="outbox-publisher-1")
  for event in events:
      broker.publish(event.event_type, event.payload, idempotency_key=event.event_id)
      service.mark_outbox_published(event.event_id, event.lease_token)
```

اگر publisher بعد از publish و قبل از acknowledgement crash کند، event دوباره publish می‌شود؛ consumer duplicate را با event ID رد می‌کند. حذف یا exactly-once ادعایی در outbox صحیح نیست.

## lifecycle reservation

| رخداد | اثر اتمیک |
|---|---|
| admission | `held_units += quantity`، reservation=`held`، job+outbox درج می‌شوند |
| success با lease معتبر | `held_units -= quantity`، `consumed_units += quantity`، usage event immutable و `quota.consumed` ساخته می‌شود |
| cancel / terminal failure | `held_units -= quantity`، reservation=`released` و `quota.released` ساخته می‌شود |
| worker heartbeat | expiry hold متناسب با job lease تمدید می‌شود؛ این extension باید در implementation control-plane بعدی افزوده شود |
| TTL recovery | فقط hold منقضی با job غیرrunning آزاد می‌شود؛ sweeper نباید job با lease معتبر را آزاد کند |

## مرزهای نمونه و کار باقیمانده قبل از production

1. نمونه `claim_outbox` و lifecycle core را پیاده می‌کند، اما HTTP/FastAPI endpoints، OIDC middleware، heartbeat endpoint و sweeper job را عمداً به application control plane واگذار می‌کند.
2. Migration واقعی tenantها باید با backfill، shadow admission، canary feature flag و reconciliation انجام شود؛ نه با switch یک‌مرحله‌ای.
3. برای PostgreSQL production، backup/restore drill، SSL verification، workload identity، rotation credential، row-level tenant isolation و monitoring `outbox_lag_seconds` باید به runbook اضافه شوند.
4. quota adjustment دستی فقط با approval چهارچشمی، immutable ledger و reason code اجرا شود.

## اعتبارسنجی نمونه

```bash
pytest -q tests/test_postgres_quota_v26.py
python3 -m compileall -q reportflow_app/postgres_quota_v26.py
bandit -q -r reportflow_app/postgres_quota_v26.py
```

آزمون‌های فعلی بدون PostgreSQL server اجرا می‌شوند و invariantهای ورودی و primitiveهای لازم را کنترل می‌کنند. پیش از production، یک integration suite با PostgreSQL ephemeral باید concurrency admission، crash/retry outbox، lease loss، TTL sweep و permission isolation را در CI اجرا کند.

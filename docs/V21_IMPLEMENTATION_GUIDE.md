# راهنمای پیاده‌سازی و عملیات v2.1

## 1. نصب و مرز استقرار

v2.1 به‌صورت progressive deployment طراحی شده است. Runtime پایه فقط قابلیت‌های محلی را دارد؛ هر connector، IdP، Secret Manager و provider AI باید جداگانه approval و نصب شود. نصب همهٔ driverها در endpoint کاربر توصیه نمی‌شود.

```bash
pip install -r requirements-enterprise.txt
```

برای Windows، driver ODBC SQL Server باید توسط IT با بستهٔ رسمی و سیاست patch سازمانی نصب شود. Connectorهای Snowflake و Databricks فقط در صورت approval network/security فعال می‌شوند.

## 2. policy connectorهای advanced

`AdvancedConnectorProfile` به یک `ConnectionPolicy` نیاز دارد. profile هیچ password/token ندارد؛ فقط `credential_reference` دارد و resolve شدن آن تنها با `SecretProvider` مرکزی انجام می‌شود.

```python
from reportflow_app.enterprise_v21 import AdvancedConnectorProfile, ConnectionPolicy

policy = ConnectionPolicy(
    allowed_hosts=frozenset({"analytics.corp.example"}),
    allowed_databases=frozenset({"finance_warehouse"}),
    allowed_private_cidrs=("10.20.0.0/16",),
    max_result_rows=250_000,
)
profile = AdvancedConnectorProfile(
    id="finance-postgres",
    name="Finance warehouse",
    kind="postgresql",
    settings={
        "host": "analytics.corp.example",
        "database": "finance_warehouse",
        "username": "reportflow_reader",
        "query": "SELECT region, period, revenue FROM mart.sales",
        "sslmode": "verify-full",
        "sslrootcert": "C:/ProgramData/ReportFlow/trust/corp-root.pem",
    },
    credential_reference="vault:///reportflow/prod/finance#password",
    policy=policy,
)
```

| connector | policy غیرقابل‌مذاکره |
|---|---|
| PostgreSQL | `verify-full`، CA قابل اعتماد، transaction read-only، timeout، role محدود و RLS در صورت نیاز |
| SQL Server | ODBC Driver 18/19، `Encrypt=Yes`، `TrustServerCertificate=No`، hostname certificate و ApplicationIntent=ReadOnly |
| MySQL | TLS certificate verification، account صرفاً SELECT و CA مصوب |
| Snowflake/Databricks | secret مرکزی، network/warehouse allowlist، query result cap و role کمینه |

## 3. recipient mapping و Report Bursting

هر burst به mapping data-driven نیاز دارد. data set mapping باید از report data جدا باشد و مالک business آن مشخص باشد.

| ستون | الزامی | مثال |
|---|---:|---|
| `recipient_id` | بله | `east-q1-manager` |
| `display_name` | بله | `East Q1 Manager` |
| `delivery_address` | بله | `east.manager@corp.example` |
| `Region` | بسته به policy | `East` |
| `Period` | بسته به policy | `Q1` |

```python
import pandas as pd
from reportflow_app.enterprise_v21 import BurstPolicy, recipients_from_mapping

mapping = pd.read_csv("approved-recipient-mapping.csv")
policy = BurstPolicy(
    allowed_filter_fields=frozenset({"Region", "Period"}),
    allowed_delivery_domains=frozenset({"corp.example"}),
    max_rows_per_recipient=250_000,
)
recipients = recipients_from_mapping(mapping, ["Region", "Period"], policy)
```

اجرای واقعی به `approved=True` نیاز دارد. ابتدا dry-run را اجرا کنید، manifest و recipient count را بازبینی کنید و سپس approval distribution owner را ثبت نمایید. Manifest شامل hash آدرس مخاطب، filterها، row count، hash artifact و outcome است؛ secret یا raw PII در آن ثبت نمی‌شود.

## 4. Semantic Contract و AI Copilot

Copilot تنها وقتی فعال شود که `SemanticContract.status="published"` باشد. هر metric منتشرشده owner و certification لازم دارد. data quality و freshness پیش از تشکیل evidence card ارزیابی می‌شوند و evidence stale/unknown پاسخ را به human review سوق می‌دهد.

```python
from reportflow_app.semantic_v21 import SemanticContract, SemanticEngineV21, SemanticFilter
from reportflow_app.copilot_v21 import CopilotNarrativeService

results, cards = SemanticEngineV21().evaluate(
    contract,
    data,
    metric_ids=["net_revenue", "order_count"],
    filters=[SemanticFilter("region", "eq", "East")],
)
request = CopilotNarrativeService(store).prepare(
    actor="analyst@corp.example",
    intent="variance_explanation",
    question="Why did East revenue change?",
    contract=contract,
    cards=cards,
)
```

Copilot نباید به raw row، SQL، connector، Secret Manager یا free-form action دسترسی داشته باشد. provider فقط `prompt_payload` ساختاریافته را دریافت می‌کند و خروجی JSON با citation metric و recommendation rationale validate می‌شود.

## 5. checklist آماده‌سازی production

| کنترل | owner | evidence |
|---|---|---|
| Connector profile و network policy | Data Platform | allowlist، CA/driver، read-only role test |
| Secret reference و rotation | Security | path policy، workload identity، rotation drill |
| Recipient mapping | Business owner | sample dry-run، dedupe و domain policy |
| Semantic contract | Data steward | owner، certification، quality/freshness result |
| Copilot provider | AI governance | model approval، data boundary و JSON schema test |
| Burst execution | Distribution owner | approved change، delivery manifest و audit event |
| Release | Release manager | signed artifact، SBOM، attestation و rollback plan |

## 6. عملیاتی‌سازی مرحله بعد

v2.1 کد contractهای scaling را فراهم می‌کند اما runner worker مرکزی نیست. برای recurring burstهای production، v2.2 باید queue persistent، idempotency key، retry policy، dead-letter queue، rate limit، observability و destination adapterهای server-side داشته باشد. این تفکیک، اجرای زمان‌بندی‌شده را از desktop client خارج و کنترل عملیاتی را به سرویس سازمانی می‌برد.

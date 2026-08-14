# ReportFlow v2.3 — Enterprise Governance Plane

**وضعیت:** طراحی تأییدشده برای پیاده‌سازی در شاخهٔ `feature/v2.3-governance-ledger`  
**هدف:** تبدیل ReportFlow از یک ابزار تولید و توزیع گزارش به یک control plane قابل‌ممیزی برای انتشار محتوای حساس.

## مسئلهٔ تجاری

مشتری سازمانی فقط نمی‌پرسد که «آیا گزارش تحویل شد؟»؛ او باید بتواند ثابت کند چه کسی یک گزارش حساس را درخواست، تأیید، تغییر، توزیع یا لغو کرده است. این نیاز به‌ویژه در گزارش‌های مالی، منابع انسانی، سلامت، داده‌های مشتری و عملیات regulated اهمیت دارد. ابزارهای BI پیشرو، lineage، impact analysis، certification و هشدار کیفیت داده را به‌عنوان بخشی از اعتماد به داده ارائه می‌کنند. Tableau Catalog مثلاً lineage، impact analysis، data dictionary و هشدار کیفیت را در تجربهٔ محصول یکپارچه می‌کند. [1]

همچنین طبقه‌بندی حساسیت باید تا export ادامه یابد؛ Power BI از الگوی label inheritance و حفاظت از خروجی‌هایی مانند Excel، PDF و PowerPoint استفاده می‌کند. [2] بنابراین مسیر رقابتی ReportFlow باید کنترل‌های governance را پیش از صف توزیع، در دادهٔ semantic و در artifact نهایی اعمال کند.

## پیشنهادهای توسعهٔ تجاری

| قابلیت | ارزش سازمانی | اولویت |
|---|---|---|
| **Policy-as-Code Approval Gates** | جداسازی وظایف، two-person control و توقف ارسال artifact حساس تا approval معتبر | اکنون — v2.3 |
| **Tamper-evident Audit Ledger** | قابلیت اثبات ترتیب رویدادها، کشف دستکاری و evidence قابل‌صادرات | اکنون — v2.3 |
| **Content-fingerprint Binding** | جلوگیری از استفادهٔ approval قبلی برای artifact یا مقصد تغییرکرده | اکنون — v2.3 |
| **Data Quality & Freshness Labels** | نمایش هشدار stale/failed و انتقال هشدار به مصرف‌کنندهٔ downstream | v2.4 |
| **End-to-end Lineage & Impact Graph** | trace از source column تا metric، report، burst و destination و تشخیص افراد متاثر از تغییر | v2.4 |
| **Sensitivity Label Propagation** | برچسب‌های Public/Internal/Confidential/Restricted در semantic model، portal و export | v2.4 |
| **Central Policy GitOps** | نسخه‌بندی policy، review، dry-run، promotion و drift detection | v2.5 |
| **BYOK/CMK و crypto-erasure** | کنترل کلید مشتری و حذف قابل‌اثبات دادهٔ tenant | v2.5 |
| **SIEM / OpenTelemetry Integration** | ارسال رخدادهای audit، queue، anomaly و policy decision به SOC | v2.5 |
| **Natural-language Governance Copilot** | پاسخ مبتنی بر evidence به «چه گزارش‌های restricted در ۳۰ روز اخیر به خارج ارسال شدند؟» | v2.6 |

## محدودهٔ پیاده‌سازی v2.3

پیاده‌سازی نخست روی سه کنترل مکمل تمرکز دارد:

| کنترل | رفتار مورد انتظار |
|---|---|
| Approval request | درخواست توزیع با payload canonical، fingerprint، requester، classification، destinations و policy snapshot ساخته می‌شود. |
| Separation of duties | requester نمی‌تواند request خود را approve کند؛ هر approver فقط یک تصمیم دارد؛ نقش‌های موردنیاز policy باید پوشش داده شوند. |
| Content integrity | approval فقط برای fingerprint اولیه معتبر است؛ تغییر artifact، classification یا destination باعث رد authorization می‌شود. |
| Tamper-evident ledger | هر رویداد با hash رویداد قبلی زنجیر می‌شود؛ `verify()` هرگونه حذف، reorder یا تغییر payload را تشخیص می‌دهد. |
| Delivery gate | worker باید درست پیش از upload، وضعیت approved و fingerprint کنونی را بررسی کند. |
| Audit correlation | تصمیم‌های governance هم در ledger اختصاصی و هم در audit trail استاندارد ProjectStore ثبت می‌شوند. |

> **مرز امنیتی:** hash chain به‌تنهایی دستکاری توسط مهاجمی با دسترسی کامل به database و key را غیرممکن نمی‌کند. v2.3 tamper-evident detection فراهم می‌کند؛ production باید checkpointهای ledger را به یک مقصد WORM/immutable مستقل یا سرویس امضاشدهٔ مرکزی anchor کند. این کار در v2.5 با audit-export و SIEM integration تکمیل می‌شود.

## الگوی policy پیشنهادی

```python
ApprovalPolicy(
    policy_id="restricted-external",
    minimum_approvals=2,
    required_roles=("data_owner", "security_officer"),
    governed_classifications=("confidential", "restricted"),
)
```

در این نمونه، درخواست `restricted` تا زمانی که دو شخص متمایز با نقش‌های `data_owner` و `security_officer` آن را approve نکنند، برای worker قابل‌ارسال نیست. approve شدن یک گزارش دیگر، یک hash دیگر یا حتی همان گزارش با مقصد متفاوت مجوز توزیع ایجاد نمی‌کند.

## تعامل با قابلیت‌های موجود

`DistributionQueue` در v2.2 همچنان مسئول idempotency، lease، retry و DLQ است. v2.3 صف را جایگزین نمی‌کند؛ آن را از طریق gate پیش از destination upload ایمن می‌کند. `SemanticContract` در نسخه‌های بعد به این policy engine منبع classification، owner و lineage edge می‌دهد. `White-label Portal` فقط grantهایی را نشان می‌دهد که governance state آن‌ها اجازه می‌دهد.

## معیارهای پذیرش v2.3

* خود-تأییدی requester رد شود.
* duplicate decision و role جعلی رد شود.
* approval برای fingerprint نامنطبق یا policy ناقص مجوز ارسال ندهد.
* تغییر یک byte در رویداد ledger یا زنجیرهٔ قبلی توسط `verify()` کشف شود.
* رویدادهای submit، approve، reject، cancel و authorize در audit trail استاندارد ثبت شوند.
* آزمون‌های unit و regression روی Windows CI اجرا و SBOM/artifact تولید شوند.

## منابع

[1]: https://help.tableau.com/current/server/en-us/dm_catalog_overview.htm "Tableau — About Tableau Catalog"
[2]: https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/service-security-sensitivity-label-overview "Microsoft — Sensitivity labels in Power BI"
[3]: https://help.tableau.com/current/online/en-us/dm_dqw.htm "Tableau — Set a Data Quality Warning"

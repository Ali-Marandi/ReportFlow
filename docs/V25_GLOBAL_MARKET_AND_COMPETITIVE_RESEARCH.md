# ReportFlow v2.5 — تحلیل بازار جهانی و نقشهٔ رقابتی

**تاریخ مرجع:** ۱۴ اوت ۲۰۲۶  
**وضعیت ReportFlow:** محصول خصوصی، پیش از اثبات کامل Product-Market Fit؛ هیچ درآمد یا تعداد مشتری در این تحلیل فرض نشده است.  
**هدف:** انتخاب یک beachhead قابل‌آزمون برای فروش ReportFlow بدون ادعای نادرست دربارهٔ اندازهٔ بازار یا سهم احتمالی.

## جمع‌بندی مدیریتی

فرصت ReportFlow در جایگزینی تمام پلتفرم‌های BI نیست. بازار عمومی BI با بازیگران جاافتاده، مدل‌های قیمت‌گذاری متفاوت و بودجه‌های فروش سنگین رقابتی است. Power BI روی مدل per-user و ظرفیت، Tableau روی نقش‌ها و ظرفیت/compute، Qlik روی ظرفیت data و Metabase روی استقرار، کاربر و قابلیت‌های مصرفی تکیه دارند. [1] [2] [3] [4]

بهترین نقطهٔ ورود، **Operational Reporting قابل‌اعتماد و governed برای تولیدکنندگان نرم‌افزار B2B و تیم‌های عملیاتی داده‌محور** است؛ یعنی سازمان‌هایی که باید به‌جای دادن دسترسی صرف به dashboard، PDF/XLSX/HTML شخصی‌سازی‌شده را به مشتری یا ذی‌نفع بیرونی تحویل دهند و بتوانند مسیر data → report → recipient → destination را برای audit توضیح دهند. این انتخاب یک **فرضیهٔ تجاری** است که باید با ۱۲ تا ۱۵ مصاحبهٔ buyer و سه pilot پولی یا design-partner اعتبارسنجی شود.

> **موضع‌گیری پیشنهادی:** «ReportFlow لایهٔ production reporting برای تحویل governed و قابل‌ممیزیِ گزارش‌های شخصی‌سازی‌شده است؛ نه dashboard دیگری برای ساختن.»

## تعریف بازار و مرزها

| مورد | تعریف پیشنهادی |
|---|---|
| Category | Governed operational reporting و embedded report delivery برای B2B |
| Buyer اولیه | Head of Data/Analytics، VP Product، COO یا Engineering Lead در software vendor داده‌محور؛ یا مدیر Finance/Operations در شرکت mid-market regulated |
| کاربر | analyst/report owner، administrator و recipient خارجی یا داخلی |
| مسئلهٔ حاد | تولید/ارسال تکراری reportهای شخصی‌سازی‌شده، کنترل مقصد، auditability، retry، approval و security بدون توسعهٔ سفارشی پرهزینه |
| خارج از محدودهٔ beachhead | جایگزینی کامل BI self-service، data warehouse، ETL/ELT، یا ساخت data visualization عمومی |
| جغرافیای شروع | English-first، remote-first و cloud-neutral؛ انتخاب کشور فروش باید بعد از evidence از pipeline، legal review و payment readiness انجام شود |

## چرا اکنون؟

قابلیت report subscription و per-recipient delivery در محصولات بزرگ همچنان بخشی واقعی از نیاز بازار است. Power BI برای dynamic per-recipient subscription از semantic model جداگانه برای mapping recipient/parameter استفاده می‌کند و آن را مشابه data-driven subscription در SSRS توصیف می‌کند؛ این قابلیت به capacity، permissionهای workspace و semantic-model build permission وابسته است. [5] Tableau نیز subscriptionهای زمان‌بندی‌شده برای PDF/image دارد، اما برای view فیلترشده نیاز به custom view دارد و تغییرات بعدی membership گروه به‌صورت خودکار subscription را همگام نمی‌کند. [6]

این واقعیت‌ها نشان نمی‌دهند که رقیب «ضعیف» است؛ بلکه نشان می‌دهند delivery، parameterization، permission و governance یک problem domain مستقل و دائمی است. ReportFlow باید روی این domain، نه روی charting عمومی، متمرکز بماند.

## نقشهٔ رقابتی

| گروه | نمونه‌ها | نقطهٔ قوت بازار | شکاف یا فرصت ReportFlow |
|---|---|---|---|
| Suite BI enterprise | Power BI، Tableau، Qlik | ecosystem، governance گسترده، visualization و کانال فروش | لایهٔ مستقل و cloud-neutral برای governed bursting، destination controls و evidence قابل‌حمل |
| Open-core BI | Metabase | self-hosting، سرعت self-service و embedded analytics | production delivery، approval و audit trail برای workflowهای حساس |
| Legacy reporting | SSRS / Crystal Reports | قالب‌بندی paginated و جایگاه سازمانی قدیمی | modern cloud destinations، portal، policy-as-code، lineage و AI evidence |
| Build in-house | scripts، cron، email provider، cloud storage | انعطاف کامل و کنترل feature | هزینهٔ نگهداری، retry/idempotency، audit و security controls بر عهدهٔ مشتری |
| Manual process | Excel/PDF و email دستی | شروع سریع و بدون تغییر سیستم | خطای انسانی، نبود scale، نبود evidence و هزینهٔ زمان نیروی عملیاتی |

### نشانه‌های pricing و packaging رقبا

| vendor | مشاهدهٔ منبع رسمی | دلالت برای ReportFlow |
|---|---|---|
| Tableau | Standard از US$15 و Enterprise از US$35 به‌ازای کاربر در ماه با پرداخت سالانه؛ deployment به حداقل یک Creator نیاز دارد و ظرفیت Viewer/compute نیز ارائه می‌شود. [2] | برای مصرف‌کنندهٔ report قیمت per-user تنها مدل مناسب نیست؛ tier باید delivery/value را هم بسنجد. |
| Qlik | Starter US$300/mo برای 10 user/10GB، Standard US$825/mo برای 25GB و Premium US$2,750/mo برای 50GB؛ Premium شامل lineage connector است. [3] | capacity و governance می‌توانند ارزش enterprise ایجاد کنند، اما ReportFlow باید metric ساده‌تر و قابل‌پیش‌بینی‌تری برای delivery عرضه کند. |
| Metabase | cloud و self-hosted ارائه می‌کند؛ embedded analytics از US$575/mo معرفی شده و برخی capabilityها usage-based هستند. [4] | self-hosting و embedding دو lever مهم‌اند؛ ReportFlow باید مسیر self-managed/managed را از ابتدا معماری کند. |
| Power BI | صفحهٔ رسمی تأکید می‌کند قیمت نمایش‌داده‌شده با کشور/منطقه و محدودیت سرویس تغییر می‌کند و enterprise offer جداگانه دارد. [1] | قیمت‌گذاری منطقه‌ای و enterprise quote، بخش طبیعی بازار جهانی است؛ قیمت واحد جهانی نباید بدون آزمایش محلی طراحی شود. |

## White-space map

| محور | crowded | فضای سفید پیشنهادی |
|---|---|---|
| Visualization discovery | dashboard self-service و ad-hoc analysis | خارج از تمرکز اولیهٔ ReportFlow |
| Operational output | subscriptionهای محصول‌محور و scriptهای داخلی | report pipeline مستقل با retry، idempotency، DLQ و traceability |
| Personalization | parameter mapping در semantic model یا custom view | multi-filter manifest + immutable artifact fingerprint + approval binding |
| Governance | permissionهای BI platform | policy-as-code، separation of duties، tamper-evident ledger و delivery gate |
| Data trust | catalog و warningهای اختیاری | lineage/impact graph از field تا destination و propagation quality/anomaly |
| Product embedding | iframe dashboard | white-label portal با grants و report-centric experience |

## انتخاب beachhead

### گزینه‌های قابل‌اجرا

| گزینه | مسئلهٔ خریدار | چرخهٔ فروش | ریسک | امتیاز پیشنهادی |
|---|---|---|---|---|
| **B2B software vendor با گزارش مشتری‌محور** | ارسال گزارش شخصی‌سازی‌شده به صدها/هزاران tenant یا customer contact | متوسط؛ buyer فنی/محصولی روشن | نیاز به API/control plane production | **اولویت ۱** |
| Mid-market finance/operations در شرکت regulated | گزارش زمان‌بندی‌شده و قابل‌ممیزی برای ذی‌نفع داخلی/خارجی | طولانی‌تر؛ procurement و compliance | نیاز به trust proof و integration | اولویت ۲ |
| مشاوره و managed-service analytics | تولید report برای چند مشتری | کوتاه؛ ممکن است design partner خوبی باشد | ARPA محدود و churn agency | اولویت ۳ |
| SME self-service desktop | ساخت گزارش از CSV/Excel | کوتاه و PLG-friendly | willingness-to-pay و support cost نامعلوم | Maybe؛ نه beachhead |

**تصمیم پیشنهادی:** با ۳ design partner از گزینهٔ اول آغاز شود. معیار ورود هر partner این است که حداقل یکی از این شرایط را داشته باشد: گزارش recurring به مشتری خارجی، حداقل دو مقصد تحویل، حساسیت داده یا الزام audit، و یک owner اجرایی که بتواند ROI زمان/ریسک را اندازه‌گیری کند.

## ارزش پیشنهادی و پیام فروش

| مخاطب | پیام اصلی | proof موردنیاز |
|---|---|---|
| VP Product / Engineering | به‌جای ساخت subsystem گزارش، delivery governed و embed-ready را سریع‌تر به محصول وارد کنید. | API contract، multi-tenant isolation، queue reliability و white-label portal |
| Head of Data | lineage و policy برای reportهای بیرونی را بدون تبدیل همهٔ BI stack پیاده کنید. | semantic contract، impact graph و evidence cards |
| COO / Finance Ops | تحویل report را از process دستی به workflow کنترل‌شده با retry و audit تبدیل کنید. | delivery manifest، approval ledger و incident/retry dashboard |
| Security / Compliance | قبل از ارسال restricted output، ownership، policy، key scope و artifact integrity را کنترل کنید. | SSO/SCIM، SecretResolver، CMK roadmap، audit export و pentest evidence |

## فرضیه‌های قابل‌آزمایش ۹۰ روزه

| فرضیه | آزمون کم‌هزینه | معیار رد یا ادامه |
|---|---|---|
| درد delivery از dashboard مهم‌تر است | ۱۲–۱۵ discovery interview با buyer beachhead | حداقل ۸ نفر مسئله را high-priority و تکرارشونده بدانند |
| governance موجب willingness-to-pay است | prototype demo برای approval + lineage + delivery gate | حداقل ۳ شرکت design-partner حاضر به pilot پولی یا LOI شوند |
| مدل platform fee + delivery usage قابل‌قبول است | صفحهٔ قیمت و interview price-sensitivity | حداقل ۵ buyer یکی از tierها را قابل‌خرید بدانند؛ objectionها ثبت شوند |
| white-label portal مزیت محصولی است | demo portal با brand profile و grant | حداقل ۲ vendor آن را عامل تمایز customer-facing بدانند |

## عدم‌قطعیت‌ها و داده‌های لازم

این تحقیق به‌طور عمدی **TAM/SAM/SOM عددی** ارائه نمی‌کند؛ بدون تعریف بازار امضاشده، logo universe، geography، pricing و دادهٔ buyer، یک عدد TAM ظاهراً دقیق گمراه‌کننده خواهد بود. برای مدل مالی بعدی باید اطلاعات زیر گردآوری شود: تعداد customerهای target در هر geography، ACV واقعی competitor/substitute، زمان صرف‌شده برای build-in-house و حجم delivery ماهانه.

## منابع

[1]: https://www.microsoft.com/en-us/power-platform/products/power-bi/pricing "Microsoft — Power BI Pricing"
[2]: https://www.tableau.com/pricing "Tableau — Pricing"
[3]: https://www.qlik.com/us/pricing "Qlik — Qlik Cloud Analytics Plans and Pricing"
[4]: https://www.metabase.com/pricing/ "Metabase — Pricing"
[5]: https://learn.microsoft.com/en-us/power-bi/collaborate-share/dynamic-subscriptions "Microsoft Learn — Dynamic per recipient subscriptions"
[6]: https://help.tableau.com/current/online/en-us/subscribe_user.htm "Tableau — Create a Subscription to a View or Workbook"

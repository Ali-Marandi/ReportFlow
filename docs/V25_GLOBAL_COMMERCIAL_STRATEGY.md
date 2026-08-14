# ReportFlow v2.5 — برنامهٔ تجاری جهانی و GTM

**تاریخ مرجع:** ۱۴ اوت ۲۰۲۶  
**مرحلهٔ محصول:** پیش از اثبات کامل Product-Market Fit  
**موضع تحلیلی:** قیمت‌ها، conversionها و economicsهای این سند «فرضیهٔ قابل‌آزمون» هستند؛ نه درآمد محقق‌شده، ارزش‌گذاری یا پیش‌بینی تضمین‌شده.

## خلاصهٔ مدیریتی

ReportFlow باید به‌عنوان «لایهٔ production reporting governed» وارد بازار شود، نه یک جایگزین عمومی برای Power BI، Tableau یا Qlik. خریدار اولیه محصولی می‌خواهد که گزارش شخصی‌سازی‌شده را به‌صورت قابل‌اعتماد، امن و قابل‌ممیزی به recipient یا destination درست برساند. این نیاز در محصول‌های بزرگ نیز وجود دارد: Power BI برای dynamic subscription به capacity، semantic model و permissionهای مشخص متکی است و Tableau برای subscription با role/permission، custom view و مدیریت failure کار می‌کند. [1] [2]

مسیر تجاری پیشنهادی، **product-led discovery با فروش founder-led به design partnerهای B2B** است. هدف ۹۰ روز نخست، درآمد زیاد نیست؛ اثبات یک مسئلهٔ تکرارشونده، تعیین metric درست برای قیمت‌گذاری و تبدیل سه pilot به referenceable customer است. هر قابلیت جدید باید یا activation، retention، ARPA، gross margin یا زمان-to-value را بهبود دهد؛ در غیر این صورت در backlog «Later» قرار می‌گیرد.

## مسئله، مشتری و ارزش پیشنهادی

| مؤلفه | تعریف عملیاتی |
|---|---|
| مسئله | شرکت‌ها برای رساندن گزارش شخصی‌سازی‌شده به مشتریان یا ذی‌نفعان، ترکیبی از BI suite، script، storage، email و process دستی را نگه می‌دارند؛ evidence و کنترل خطا به‌صورت پراکنده است. |
| مشتری beachhead | B2B software vendorهای داده‌محور با report customer-facing و تیم 20–500 نفر؛ buyer اصلی VP Product، Engineering Lead یا Head of Data است. |
| کاربر | report owner، administrator، support/operations و recipient نهایی. |
| Job to be done | «در زمان مشخص، گزارش صحیح با filter درست را به مقصد مجاز تحویل بده و بتوانم بعداً توضیح دهم چه چیزی، برای چه کسی و تحت چه policy ارسال شد.» |
| ارزش پیشنهادی | queue resilient، destination controls، bursting، white-label delivery، lineage، approval و evidence در یک لایهٔ مستقل از BI suite. |
| وعدهٔ محصول | یکپارچگی تولید و governance گزارش، بدون مجبور کردن مشتری به جایگزینی warehouse یا BI stack فعلی. |

## مدل کسب‌وکار پیشنهادی

مدل مناسب، **hybrid B2B SaaS** است: platform subscription برای ارزش ثابت، usage allowance برای scale delivery و enterprise add-on برای governance/compliance. این ساختار با مدل‌های per-user، capacity و usage در بازار سازگار است، اما خریدار را مجبور نمی‌کند برای هر recipient یک license تحلیل‌گر بخرد. Tableau هم‌زمان نقش‌های user-based و capacity/compute pricing دارد، Qlik capacity data-based دارد و Metabase cloud/self-hosted و capability usage-based عرضه می‌کند. [3] [4] [5]

| جریان درآمد | منطق ارزش | مشتری مناسب | وضعیت |
|---|---|---|---|
| Platform subscription | workspace، administration، connectors و base support | تمام مشتریان پولی | **Now** |
| Delivery usage | volume موفق report delivery یا artifact package بالاتر از allowance | vendorهای با distribution بالا | **Now** |
| Governed destination / portal add-on | white-label portal، destination controls و tenant grants | SaaS vendorهای customer-facing | **Next** |
| Enterprise governance add-on | SSO/SCIM، audit export، approval policy، private deployment | regulated/mid-market | **Next** |
| Implementation / migration | setup، template conversion، security review | Enterprise | **Now، خدمات محدود** |
| Partner / OEM / white-label | reseller یا embedded license | SI/ISV | **Later، پس از اثبات repeatable onboarding** |
| Marketplace / connector ecosystem | connector یا destination third-party | developer ecosystem | **Later** |

> **قاعدهٔ درآمد:** Usage باید به یک metric قابل‌کنترل توسط مشتری متصل باشد. «delivery موفق» در برابر «attempt» برای مشتری قابل‌فهم‌تر و قابل‌اعتمادتر است؛ failureهای ناشی از platform نباید usage bill ایجاد کنند.

## بسته‌بندی و قیمت‌گذاری پیشنهادی برای آزمون

این قیمت‌ها **point estimate برای مصاحبه و pilot** هستند، نه price list نهایی. مبنای مقایسه، مدل‌های رسمی رقباست: Tableau Standard US$15 و Enterprise US$35 per-user/month با پرداخت سالانه دارد؛ Qlik از US$300/month برای 10 user/10GB شروع می‌کند؛ Metabase embedding را از US$575/month معرفی می‌کند. [3] [4] [5]

| tier پیشنهادی | قیمت آزمون | شامل | مرز مصرف | هدف یادگیری |
|---|---:|---|---|---|
| Community Desktop | US$0 | local report authoring، فایل‌های محلی، export پایه | بدون portal/central queue | activation و adoption فردی |
| Team | US$199/سازمان/ماه | 3 admin، 10 report definition، queue، 1 destination type | 1,000 delivery موفق/ماه | willingness-to-pay تیم کوچک |
| Growth | US$799/سازمان/ماه | 10 admin، advanced connectors، portal، 3 destination type، anomaly/lineage | 10,000 delivery موفق/ماه | buyer product/data در B2B vendor |
| Enterprise | از US$18,000/سال + usage | SSO/SCIM، approval, audit export، private deployment option، named success plan | قرارداد و SLA | procurement و compliance willingness-to-pay |

### قواعد قیمت‌گذاری

* تخفیف سالانه در pilot حداکثر 15% باشد تا ارزش اولیهٔ محصول تخریب نشود.
* usage overage باید به‌صورت pool ماهانه و با alertهای 70/90/100 درصد ارائه شود؛ auto-charge بدون approval در pilot فعال نشود.
* region-based pricing با multiplier آزمایشی انجام شود، نه تبدیل ارزی ساده: North America = 1.00، UK/Ireland/DACH = 0.90، GCC = 0.85، سایر بازارهای منتخب پس از تحقیق willingness-to-pay. این‌ها فرض اولیه‌اند و باید با quote win/loss تأیید شوند.
* Enterprise quote باید هزینهٔ onboarding، support، deployment model، residency و service-level را جدا از license شفاف کند.

## unit economics و مدل مالی قابل‌آزمون

بدون دادهٔ واقعی CAC، churn و delivery cost، ارائهٔ forecast عددی مسئولانه نیست. تیم باید از نخستین pilotها هر ماه این chain را اندازه بگیرد:

| شاخص | تعریف | کاربرد تصمیم |
|---|---|---|
| Activated workspace | tenantی که اولین report governed را با حداقل یک delivery موفق ساخته است | اندازه‌گیری activation واقعی |
| NSM | **Governed successful deliveries per active tenant** | ترکیب adoption، reliability و embedded value |
| ARPA | MRR ÷ مشتریان پرداخت‌کننده | pricing و upsell |
| Gross margin | (MRR − هزینهٔ مستقیم cloud/support/processing) ÷ MRR | امکان scale اقتصادی |
| CAC | هزینهٔ sales + marketing attributable ÷ logoهای جدید | سلامت کانال جذب |
| Payback | CAC ÷ gross profit monthly per customer | سرعت بازگشت سرمایهٔ فروش |
| Logo retention | مشتریان باقی‌مانده ÷ مشتریان ابتدای cohort | ارزش محصول و customer success |
| Net revenue retention | (MRR اول دوره + expansion − contraction − churn) ÷ MRR اول دوره | کارایی expansion و usage pricing |

سه سناریوی مالی باید فقط پس از دریافت دادهٔ pilot ساخته شوند. در سناریوی محافظه‌کار، win rate، activation و usage به‌صورت پایین‌تر و CAC بالاتر stress می‌شوند؛ در سناریوی پایه، inputها با median cohort واقعی؛ و در سناریوی جسورانه فقط با evidence از repeatable partner channel یا self-serve conversion. هیچ سناریو نباید بدون source یا assumption log به تصمیم سرمایه‌گذاری منتهی شود.

## GTM: مسیر ۹۰ روزه

| بازه | هدف | اقدام | KPI عبور |
|---|---|---|---|
| روز 0–30 | Problem discovery | 15 interview با VP Product، Head of Data و COO؛ تحلیل report workflow، delivery volume و compliance trigger | حداقل 8 نفر درد recurring/high-priority را تأیید کنند |
| روز 31–60 | Solution validation | demo قابل‌اجرا از v2.2–v2.4، design-partner proposal و price test سه-tier | 3 pilot با scope و sponsor مشخص؛ حداقل 1 pilot پولی یا LOI |
| روز 61–90 | Pilot activation | onboarding سریع، تعریف baseline، weekly evidence review و win/loss log | هر pilot یک governed delivery production-like و یک ROI story قابل‌اندازه‌گیری داشته باشد |

### کانال‌های اولویت‌دار

| کانال | نقش | Now / Next / Later |
|---|---|---|
| Founder-led outbound | یافتن 50 account مشابه، interview و pilot | **Now** |
| Design-partner referrals | تبدیل هر pilot موفق به دو introduction گرم | **Now** |
| Technical content | مقاله/نمونه دربارهٔ governed report delivery، lineage و code-signing trust | **Next** |
| SI / data consultancy | migration و implementation channel | **Next** |
| Cloud marketplace | procurement simplification | **Later** |
| Paid search/ads | فقط پس از اثبات conversion و ICP message | **Do not do اکنون** |

## customer journey و growth loops

| مرحله | مانع محتمل | intervention ReportFlow | KPI |
|---|---|---|---|
| Awareness | محصول با BI dashboard اشتباه گرفته می‌شود | message مبتنی بر «governed delivery»، نه visualization | qualified visit → demo |
| Consideration | build-vs-buy نامشخص است | ROI worksheet: build maintenance، incident و audit cost | demo → pilot |
| Activation | اولین delivery سخت یا کند است | template، sample connector، guided setup و dry run | time-to-first-governed-delivery |
| Habit | ارزش فقط هنگام failure دیده می‌شود | health digest، evidence card و anomaly notification | weekly active admin |
| Retention | usage/owner نامعلوم است | tenant usage، lineage impact و success review | renewal intent |
| Expansion | محصول فقط در یک تیم می‌ماند | destination/portal add-on و additional report domains | NRR / expansion MRR |
| Advocacy | proof قابل‌اشتراک وجود ندارد | case study و referral incentive پس از رضایت | introduction rate |

## Global-first, local-by-need

نقطهٔ شروع باید English-first و cloud-neutral باشد، اما localization بدون بازسازی معماری طراحی شود: resource bundle برای UI/message، timezone-aware scheduling، currency-neutral metering، regional data residency configuration، tenant-scoped key reference و policy bundle versioned. به‌جای launch هم‌زمان در چند کشور، هر بازار با یک **Global Expansion Score** از 100 رتبه‌بندی می‌شود.

| عامل | وزن | پرسش کنترل |
|---|---:|---|
| ICP density و pain evidence | 25 | آیا حداقل 10 account هم‌شکل و قابل‌دسترسی وجود دارد؟ |
| willingness-to-pay | 20 | آیا pilot quote در بازهٔ tier پیشنهادی قابل‌قبول است؟ |
| sales cycle / procurement | 15 | آیا sponsor می‌تواند pilot را بدون قرارداد سالانهٔ سنگین شروع کند؟ |
| data/privacy fit | 15 | آیا residency، DPA و security requirements قابل‌پاسخ‌اند؟ |
| payment and FX operability | 10 | آیا invoice، tax و collection قابل‌اجراست؟ |
| partner availability | 10 | آیا SI/cloud/consulting partner معتبر وجود دارد؟ |
| localization cost | 5 | آیا زبان، RTL، support-hours و legal adaptation مانع اقتصادی نیست؟ |

رتبه‌بندی کشورها نباید پیش از جمع‌آوری دادهٔ واقعی pipeline انجام شود. فرض شروع کم‌ریسک این است که design partnerهای English-speaking و remote-accessible بدون وابستگی به یک کشور انتخاب شوند؛ سپس دادهٔ quote/win/loss برای رتبه‌بندی کشورها استفاده شود.

## ریسک‌ها و کنترل‌ها

| ریسک | احتمال اولیه | اثر | mitigation |
|---|---|---|---|
| تبدیل‌شدن به BI عمومی | متوسط | زیاد | حفظ ICP، product message و roadmap حول governed delivery |
| زمان setup بالا | متوسط | زیاد | connector templates، onboarding telemetry و partner playbook |
| رقابت suiteهای بزرگ | زیاد | زیاد | تمرکز بر vendor-neutral layer، white-label و evidence chain |
| security/compliance gap | متوسط | بسیار زیاد | signing runner، SSO/SCIM، CMK roadmap، pentest و policy-as-code |
| usage cost غیرقابل‌پیش‌بینی | متوسط | متوسط | metering، threshold alert و quota policy |
| sales-led product بدون PMF | متوسط | زیاد | توقف scale GTM تا سه pilot و reference evidence |
| global expansion زودهنگام | متوسط | متوسط | expansion score و single-beachhead discipline |

## اولویت‌بندی سرمایه‌گذاری محصول

| Now | Next | Later | Do Not Do اکنون |
|---|---|---|---|
| Metering و entitlements، onboarding/dry run، delivery health، signing infrastructure، pilot templates | KeyProvider واقعی، portal lineage UI، SIEM export، policy GitOps validator | marketplace، connector SDK عمومی، partner/OEM program، governance copilot | بازسازی کامل BI dashboard، paid scale acquisition، ده‌ها connector کم‌تقاضا |

## Safe / Smart / Bold

| سطح | انتخاب | دلیل |
|---|---|---|
| Safe | فروش implementation همراه با Team/Growth subscription | یادگیری سریع و cash contribution، با ریسک product scale کمتر |
| Smart | entitlement + usage metering + design-partner GTM | قیمت، value metric و margin را هم‌زمان قابل‌آزمون می‌کند |
| Bold | OEM/embedded reporting control plane برای vertical SaaS | potential ARPA و switching cost بالاتر، اما نیازمند API reliability و partner motion است |
| Moonshot | شبکهٔ cross-tenant policy/connector marketplace با governance copilot | moat بالقوه از ecosystem و data، اما پیش از PMF باید انجام نشود |

## اقدامات فوری

۱. لیست 50 account beachhead و 15 interview target تهیه شود؛ هر مصاحبه با discovery script و قیمت‌سنجی ثبت شود.  
۲. مسیر «اولین governed delivery در کمتر از 30 دقیقه» با demo dataset و telemetry ساخته شود.  
۳. قابلیت entitlements و usage metering برای اجرای آزمایش tierهای Team/Growth پیاده‌سازی شود.  
۴. Windows signing runner و Environment `production-release` طبق runbook عملیاتی فعال شوند.  
۵. بعد از سه pilot، فقط metricهای واقعی cohort مبنای TAM/SAM/SOM و مدل مالی 5 ساله قرار گیرند.

## منابع

[1]: https://learn.microsoft.com/en-us/power-bi/collaborate-share/dynamic-subscriptions "Microsoft Learn — Dynamic per recipient subscriptions"
[2]: https://help.tableau.com/current/online/en-us/subscribe_user.htm "Tableau — Create a Subscription to a View or Workbook"
[3]: https://www.tableau.com/pricing "Tableau — Pricing"
[4]: https://www.qlik.com/us/pricing "Qlik — Qlik Cloud Analytics Plans and Pricing"
[5]: https://www.metabase.com/pricing/ "Metabase — Pricing"

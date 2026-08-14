# ReportFlow v2.5 — برنامهٔ اجرایی و Scriptهای Discovery Outreach برای Tier A

**تاریخ مرجع:** ۱۴ اوت ۲۰۲۶  
**دامنه:** ۱۵ account در Tier A از universe پژوهشی ۵۰ accountی؛ نه ۵۰ account «Tier A».  
**هدف:** اعتبارسنجی مسئله، workflow، sponsor، معیار موفقیت و willingness-to-pay برای governed production reporting. این برنامه برای ارسال خودکار یا ارسال پیام بدون مرور انسانی طراحی نشده است.

> **اصل عملیاتی:** هر پیام یک «فرضیهٔ مسئله» را آزمایش می‌کند، نه این‌که فهرست featureهای ReportFlow را بفروشد. هیچ شخص، intent خرید، integration موجود یا ROI بدون تأیید prospect ادعا نمی‌شود.

## 1. هدف کمی و معیارهای مرحله

| مرحله | هدف | خروجی قابل‌مشاهده | معیار عبور |
|---|---:|---|---|
| Research و personalization | ۱۵ account | یک account brief یک‌صفحه‌ای برای هر account | role، public trigger و فرضیهٔ workflow تأیید شده باشد |
| Outreach wave 1 | ۱۵ account | پیام اول با یک line شخصی‌سازی‌شده | ۱۵ ارسال پس از review دستی و رعایت سیاست کانال |
| Discovery call | ۶ تا ۹ گفت‌وگو | یادداشت ساخت‌یافتهٔ problem / process / impact | دست‌کم ۵ گفت‌وگو با owner واقعی workflow |
| Design-partner qualification | ۳ account | pilot brief با sponsor، scope و KPI | مسئله recurring، access به workflow و owner مشخص باشد |
| Commercial signal | ۱ تا ۳ account | LOI، paid pilot، یا commitment روشن برای قدم بعد | willingness-to-pay و decision process مستند شده باشد |

اعداد بالا **هدف اجرایی** هستند، نه پیش‌بینی conversion. نتیجه باید با دادهٔ واقعی campaign اصلاح شود.

## 2. نقش‌ها و cadence چهارده‌روزه

| روز | اقدام | owner پیشنهادی | خروجی |
|---:|---|---|---|
| ۰ | مرور website، release note، job posting و public content account؛ ثبت یک trigger معتبر | Researcher | Account brief و یک hypothesis |
| ۱ | ارسال پیام اول به role مناسب از کانال مجاز | Founder/PM | پیام شخصی‌سازی‌شده و ثبت timestamp |
| ۴ | follow-up اول با یک سؤال workflow مشخص | Founder/PM | پاسخ، referral یا no-response |
| ۹ | follow-up دوم با insight عمودی و دعوت کوتاه | Founder/PM | discovery invitation |
| ۱۴ | close-the-loop محترمانه؛ سپس توقف outreach مستقیم | Founder/PM | وضعیت final: replied / referred / nurture / no contact |

هر account فقط یک owner outreach دارد. قبل از ارسال، پیام باید توسط نفر دوم از نظر accuracy، tone و نبود claim تأییدنشده مرور شود. از خرید contact list، scraping اطلاعات شخصی یا ارسال انبوه خودکار استفاده نشود. کانال انتخابی باید با شرایط استفاده و قوانین بازار مقصد سازگار باشد؛ این playbook جایگزین مشاورهٔ حقوقی نیست.

## 3. Scriptهای پایهٔ انگلیسی برای accountهای Tier A

### 3.1 پیام اول — discovery، نه demo

**Subject A:** `Question on governed reporting at [Company]`  
**Subject B:** `30-minute research question on [vertical] reporting delivery`

```text
Hi [First name],

I’m researching how B2B software teams run recurring, customer-facing and operational reports after the dashboard—especially per-recipient output, retries when delivery fails, and evidence for audit.

[Personalized hypothesis from the table below.]

I’m building ReportFlow, but this is a research conversation rather than a product demo. Would you be open to a 30-minute call to compare notes on how your team handles this workflow today? No preparation is needed; I can share an anonymized summary of patterns we learn.

If this sits with another product, data, platform, or operations leader, could you point me in the right direction?

Best,
[Name]
[Role] · ReportFlow
```

### 3.2 Follow-up 1 — یک سؤال مشخص

```text
Hi [First name],

Following up with one narrow research question: when [workflow-specific phrase], does the owning team have a reliable way to see the recipient, policy, delivery status and retry history in one place?

If this is not a current priority, a simple “not now” is helpful. If it is, would a 30-minute research call next week be reasonable?

Best,
[Name]
```

### 3.3 Follow-up 2 — insight عمودی، بدون social proof ساختگی

```text
Hi [First name],

We are testing a hypothesis that [vertical] teams often keep the “last mile” of report delivery split across BI, scripts, storage and email. That can make per-recipient controls and audit evidence expensive to maintain.

Is that hypothesis directionally wrong for [Company], or worth a short research conversation?

Regards,
[Name]
```

### 3.4 Close-the-loop

```text
Hi [First name],

I’ll close the loop after this note. If governed reporting delivery becomes relevant—especially burst logic, retry/queue reliability, destination controls or delivery evidence—I would value the chance to compare notes.

Thank you for considering the research request.

Best,
[Name]
```

### 3.5 درخواست اتصال کوتاه در شبکهٔ حرفه‌ای

```text
Hi [First name] — I’m researching how [vertical] software teams govern recurring report delivery beyond the dashboard. Your work at [Company] looks relevant to that question. Would be glad to connect; no pitch attached.
```

## 4. Script تماس discovery

### 4.1 شروع تماس — ۹۰ ثانیه

```text
Thank you for making time. This is a research call, not a product demo. I’d like to understand one reporting or delivery workflow, where it breaks down, who owns it, and what evidence is needed when something fails. If it becomes clear there is no fit, we can stop early.
```

### 4.2 پنج سؤال اصلی

1. Which recurring or customer-facing report is hardest to deliver reliably today?
2. Who defines the report, who operates delivery, and who is accountable when a recipient does not receive it?
3. Where do per-recipient filters, destinations, retries and approval rules live today?
4. What evidence would you need for an audit, escalation or customer dispute?
5. What would make a limited pilot valuable: setup time, failed delivery rate, audit time, delivery volume or expansion revenue?

### 4.3 سؤال‌های qualification برای design partner

```text
If we could run one scoped workflow end-to-end, would you have:
1) an executive or functional sponsor,
2) a safe non-production or low-risk report workflow,
3) an owner who can measure the before/after KPI, and
4) a decision path for a paid continuation if the pilot works?
```

### 4.4 پایان تماس

```text
Let me reflect back what I heard: [problem], [current workaround], [impact], and [success metric]. I will send a one-page summary for correction. If the workflow is a candidate, the next step would be a narrow pilot brief—not a broad platform evaluation.
```

## 5. Personalization matrix برای پانزده account Tier A

| Account | Role اولیه | فرضیهٔ شخصی‌سازی‌شده برای پیام اول | سؤال follow-up اختصاصی |
|---|---|---|---|
| ServiceTitan | VP Product / Head of Data | «در field-service، owner یا manager ممکن است گزارش‌های عملیاتی با scope متفاوت دریافت کند؛ می‌خواهم بدانم delivery و failure ownership چگونه مدیریت می‌شود.» | «آیا template، filter و destination برای business unitها در یک control plane دیده می‌شود؟» |
| Vanta | VP Product / Head of Customer Trust | «برای evidence و compliance reporting، اثبات اینکه artifact صحیح با policy صحیح تحویل شده چه شکلی دارد؟» | «در escalation یا audit، lineage و delivery history را چگونه یکجا بازسازی می‌کنید؟» |
| Planful | VP Product / Finance Platform Lead | «در financial close، distribution خروجی‌های حساس به stakeholderهای مختلف چه کنترل approval و retry دارد؟» | «آیا report delivery از consolidation workflow جداست یا بخشی از همان control plane؟» |
| Maxio | VP Product / Head of Data | «برای SaaS metrics و خروجی‌های finance/customer-facing، delivery recurring و segmentation recipientها چگونه قابل‌توضیح می‌ماند؟» | «وقتی یک delivery مالی fail می‌شود، owner و evidence چه کسی است؟» |
| Procore | VP Product / Analytics Lead | «گزارش‌های project/financial برای ذی‌نفعان بیرونی ممکن است destination و access متفاوت داشته باشند؛ می‌خواهم workflow آن را بفهمم.» | «آیا project-level recipient rules و delivery retry در یک سیستم قابل‌مشاهده‌اند؟» |
| AppFolio | VP Product / Data Products Lead | «در property management، owner/property reportها چه زمانی به bursting یا per-portfolio delivery نیاز پیدا می‌کنند؟» | «آیا destination و filter هر recipient قابل audit است؟» |
| Buildium | VP Product / Product Analytics | «برای property manager/owner workflow، کدام report recurring بیشترین عملیات دستی در delivery ایجاد می‌کند؟» | «اگر recipientی گزارش نگرفت، تیم چگونه علت، retry و evidence را دنبال می‌کند؟» |
| Entrata | VP Product / Engineering Lead | «در portfolio/tenant operations، delivery role-aware و portal-facing چطور از report generation جدا می‌شود؟» | «آیا data-to-destination lineage برای reportهای حساس یک نیاز واقعی است؟» |
| Jobber | VP Product / Data Lead | «برای service businessها، کدام report/summary نیازمند delivery شخصی‌سازی‌شده برای owner یا client است؟» | «آیا export و scheduling امروز خارج از محصول اصلی نگه‌داری می‌شود؟» |
| Housecall Pro | VP Product / Platform Engineering | «در customer operation reporting، reliability لایهٔ delivery چه زمانی به مسئلهٔ platform تبدیل می‌شود؟» | «چه metricی نشان می‌دهد یک report delivery قابل‌اعتماد است؟» |
| WorkWave | VP Product / GM Product | «چند vertical service ممکن است template و recipient logic متفاوت بخواهند؛ این variation امروز چگونه مدیریت می‌شود؟» | «آیا برای هر vertical یک delivery workflow مستقل ایجاد می‌کنید؟» |
| JobNimbus | VP Product / Head of Data | «برای contractor workflowها، گزارش project و performance چطور به recipientهای مختلف tailored می‌شود؟» | «کجا بیشترین friction بین data model، report definition و delivery رخ می‌دهد؟» |
| BuildOps | VP Product / CTO | «در commercial contractor operations، آیا policy، approval و delivery reliability بخشی از تجربهٔ reporting محسوب می‌شود؟» | «آیا یک queue مرکزی و audit-safe برای outputهای عملیاتی ارزش آزمایش دارد؟» |
| Zenoti | VP Product / Data Products Lead | «در franchise/multi-location reporting، واحدها ممکن است scope و destination متفاوت داشته باشند؛ این delivery segmentation چگونه enforce می‌شود؟» | «آیا franchise operatorها به evidence یا retry visibility نیاز دارند؟» |
| Mindbody | VP Product / Analytics Lead | «در business analytics برای partner/locationها، control دسترسی و destination reportها چگونه با رشد مخاطب scale می‌کند؟» | «آیا portal، export و scheduled delivery در یک ownership مشترک قرار دارند؟» |

## 6. Account brief یک‌صفحه‌ای پیش از هر ارسال

| بخش | محتوای لازم | منع صریح |
|---|---|---|
| Public signal | یک URL رسمی یا public statement و تاریخ مشاهده | برداشت از اطلاعات خصوصی یا حدس دربارهٔ فناوری داخلی |
| Hypothesis | یک workflow قابل falsify با عبارت «ممکن است» | بیان مشکل به‌عنوان واقعیت قطعی |
| Role | عنوان نقش، نه نام شخص بدون منبع مجاز | contact detail یا دادهٔ شخصی در document محصول |
| Ask | درخواست 30 دقیقه گفتگو | درخواست demo، procurement یا contract در پیام اول |
| Exit criterion | reply، referral، decline یا no-response پس از روز 14 | follow-up نامحدود یا pressure tactic |

## 7. گزارش‌گیری هفته‌ای

| شاخص | تعریف | تصمیمی که پشتیبانی می‌کند |
|---|---|---|
| Reply rate | پاسخ‌های معنادار ÷ پیام‌های اول | کیفیت targeting و message |
| Meeting rate | discovery call ÷ accountهای contacted | relevance مسئله و CTA |
| Problem confirmation | callهایی که مشکل recurring/high-priority را تأیید می‌کنند ÷ calls | اعتبار ICP |
| Sponsor rate | accountهایی با owner و sponsor ÷ qualified accounts | امکان pilot |
| Commercial signal | LOI/paid pilot/defined budget signal ÷ pilot candidates | readiness برای GTM scale |

## 8. مرزبندی اخلاقی و اجرایی

این برنامه یک playbook برای research گفت‌وگومحور است. پیش از outreach باید آدرس، channel و قوانین مرتبط با بازار مقصد (مانند قواعد پیام تجاری و privacy) با مشاور حقوقی یا سیاست داخلی بررسی شوند. همهٔ پیام‌ها باید امکان decline محترمانه داشته باشند و پس از close-the-loop، account وارد nurture غیرمستقیم شود؛ نه follow-up مستقیم نامحدود.

## Cover

**ReportFlow Enterprise v2.5**

استراتژی تجاری، discovery pipeline و commercial controls

۱۴ اوت ۲۰۲۶

## Slide 1

### مسئله: تحویل گزارش، صرفاً dashboard نیست

- گزارش recurring و customer-facing معمولاً میان BI، script، storage و email پراکنده است.
- خریدار باید بتواند پاسخ دهد چه artifactی، با چه policy و برای کدام مقصد تحویل شده است.
- ReportFlow روی production reporting governed متمرکز است؛ نه رقابت عمومی در charting.

**پیام:** ارزش متمایز در تحویل قابل‌اعتماد، قابل‌ممیزی و شخصی‌سازی‌شده است.

## Slide 2

### Beachhead: B2B SaaS با گزارش مشتری‌محور

- ICP: vendor داده‌محور با گزارش recurring، چند recipient/destination و حساسیت audit یا compliance.
- Buyer: VP Product، Head of Data، COO یا Engineering Lead.
- User: report owner، admin و recipient نهایی.
- 50 account research universe ایجاد شد؛ 15 account در Tier A برای discovery عمیق اولویت دارند.

**پیام:** یک vertical مشخص را validate کنیم، نه اینکه کل بازار BI را هدف بگیریم.

## Slide 3

### فرصت رقابتی: governing the last mile

- Power BI، Tableau و Qlik نیاز به subscription، capacity و reporting را تأیید می‌کنند.
- ReportFlow روی multi-filter bursting، destination controls، retry/DLQ و evidence تمرکز دارد.
- v2.3 approval ledger و v2.4 lineage graph اعتماد را از data تا destination امتداد می‌دهند.

**پیام:** نقطهٔ تمایز، کنترل و evidence در «آخرین مایل» delivery است.

## Slide 4

### مدل تجاری: platform + successful delivery

- Platform subscription برای workspace، connector و admin value.
- allowance و usage بر مبنای **successful delivery**؛ نه failure یا retry platform.
- add-onهای آینده: white-label portal، governance enterprise و private deployment.
- Community، Team، Growth و Enterprise به‌عنوان price-test طراحی شده‌اند؛ نه price list قطعی.

**پیام:** value metric باید شفاف، قابل‌کنترل و هم‌جهت با ارزش مشتری باشد.

## Slide 5

### v2.5: packaging به کنترل محصول تبدیل شد

- plan immutable و versioned با SKU، feature flag و meter limit.
- entitlement tenant-scoped با status و overrideهای ثبت‌شده در audit.
- feature gate service-side برای distribution queue، portal و capabilityهای آینده.
- usage event idempotent با billing period و summary quota.

**پیام:** فروش و محصول اکنون زبان مشترک قابل‌اجرا دارند.

## Slide 6

### اعتماد در metering: فقط success، با evidence

- CommercialDistributionGate پیش از enqueue entitlement و quota را بررسی می‌کند.
- worker پس از completion موفق usage را با job-correlated idempotency key ثبت می‌کند.
- v2.5.1 snapshot plan/version و زمان اثر entitlement را به هر usage event افزود.
- metadata با size limit و فیلتر identity/credential key کنترل می‌شود.

**پیام:** usage قابل‌توضیح است؛ نه یک counter مبهم برای invoice.

## Slide 7

### وضعیت کیفیت و release

- 50 آزمون regression پس از hardening v2.5.1 پاس شده‌اند.
- dependency audit بدون آسیب‌پذیری شناخته‌شده و Bandit بدون finding تکمیل شده‌اند.
- CI v2.5 روی main پیش‌تر با build، SBOM و Windows package موفق بوده است.
- انتشار signed همچنان به runner Windows اختصاصی، certificate/HSM و `production-release` نیاز دارد.

**پیام:** کیفیت محصول green است؛ production signing یک وابستگی عملیاتی مستقل است.

## Slide 8

### 90 روز آینده: یادگیری سریع، نه scale زودهنگام

- روز 0–30: 15 discovery interview با Tier A و ثبت pain, workflow و willingness-to-pay.
- روز 31–60: سه design-partner proposal و demo governed delivery.
- روز 61–90: pilot، baseline metric و یک ROI story قابل‌اندازه‌گیری برای هر partner.
- معیار ادامه: حداقل سه pilot با sponsor مشخص و دست‌کم یک commitment پولی یا LOI.

**پیام:** evidence مشتری باید تصمیم roadmap و قیمت را هدایت کند.

## Slide 9

### اولویت اجرایی: تمرکز روی برنده‌ها

- **Now:** onboarding کمتر از 30 دقیقه، delivery health، signing runner و pilot templates.
- **Next:** quota reservation، metering service مرکزی، SIEM export، price book منطقه‌ای و GitOps policy.
- **Later:** OEM/partner program، marketplace و Governance Copilot.
- **Do not do اکنون:** جایگزینی کامل BI dashboard یا paid acquisition در مقیاس.

**پیام:** تمرکز، value proof و repeatable onboarding پیش‌نیاز scale جهانی‌اند.

## Slide 10

### تصمیم موردنیاز

**تمرکز اولیه: سه design partner از Tier A**

یک workflow واقعی را governed، قابل‌ممیزی و قابل‌اندازه‌گیری کنید؛ سپس GTM و price book را با دادهٔ واقعی گسترش دهید.

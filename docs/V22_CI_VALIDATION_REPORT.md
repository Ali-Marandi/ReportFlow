# گزارش اعتبارسنجی CI برای ReportFlow v2.2

**تاریخ گزارش:** ۱۴ اوت ۲۰۲۶  
**commit خط اصلی:** `75257fcd2df7a16e60a98588e68ae5bf683bf9bd`  
**اجرای مرجع:** [GitHub Actions run 31756289964](https://github.com/Ali-Marandi/ReportFlow/actions/runs/31756289964)  
**نتیجهٔ کلی:** **موفق**

## خلاصهٔ مدیریتی

تغییرات v2.2 پس از ادغام Pull Request شمارهٔ ۱ در `main` روی Windows CI اعتبارسنجی شدند. این اجرا مسیر کامل candidate unsigned را با موفقیت طی کرد: نصب وابستگی‌های آزموده‌شده، test suite، audit وابستگی‌ها، تولید SBOM، ساخت PyInstaller، کنترل وجود EXE/SBOM و archive artifact. Job امضای production برای اجرای push روی `main` به‌درستی **skipped** شد، زیرا workflow فقط روی tagهای `v2.*` وارد مسیر امضا و انتشار می‌شود. [1]

> این گزارش تأیید می‌کند که candidate ویندوزی v2.2 قابل‌ساخت و قابل‌آرشیو است؛ تأییدیهٔ امضای Authenticode یا GitHub Release تولیدی محسوب نمی‌شود. آن دو مرحله به runner امضای اختصاصی و Environment محافظت‌شده نیاز دارند.

## دامنهٔ CI

| کنترل | نتیجه | شاهد |
|---|---|---|
| اجرای workflow | موفق | `Build, sign, and publish ReportFlow for Windows` |
| زمان job اصلی | موفق | شروع `00:07:40Z`، پایان `00:12:47Z`؛ حدود ۵ دقیقه و ۷ ثانیه |
| واحد آزمون | موفق | `33 passed in 12.45s` |
| Audit وابستگی | موفق | `No known vulnerabilities found` با `pip-audit -r requirements.txt` |
| SBOM | موفق | `cyclonedx-py environment --output-file dist/sbom.json` اجرا و وجود `dist/sbom.json` کنترل شد |
| ساخت Windows EXE | موفق | PyInstaller `dist/ReportFlow/ReportFlow.exe` را تولید کرد و workflow وجود فایل را کنترل نمود |
| archive candidate | موفق | artifact immutable ساخته و نهایی شد |
| Signing/attestation/release | skipped (مورد انتظار) | trigger اجرای مرجع push روی `main` بود، نه tag `v2.*` |

## artifact و قابلیت بازتولید

artifact حاصل از CI برای commit خط اصلی نام SHA-based دارد؛ این نام‌گذاری ارتباط artifact با commit را در زنجیرهٔ انتشار حفظ می‌کند.

| ویژگی | مقدار |
|---|---|
| نام artifact | `reportflow-unsigned-75257fcd2df7a16e60a98588e68ae5bf683bf9bd` |
| شناسهٔ artifact | `9202923735` |
| اندازهٔ نهایی | `119,620,571` بایت |
| SHA-256 zip artifact | `ef5a794568eac041e7f27284df16bd74e964e673c423e454f7d8cb03e058925f` |
| دسترسی | [artifact در GitHub Actions](https://github.com/Ali-Marandi/ReportFlow/actions/runs/31756289964/artifacts/9202923735) |
| retention workflow | ۳ روز |

محتوای archive شامل پوشهٔ `dist/ReportFlow` و `dist/sbom.json` است. pipeline در مرحلهٔ verify، نبود `ReportFlow.exe` یا SBOM را failure محسوب می‌کند. [1]

## مسیر کنترل‌شدهٔ انتشار

workflow انتشار ReportFlow به‌صورت عمدی build unsigned را از امضا جدا می‌کند. job ساخت روی runner میزبانی‌شدهٔ GitHub اجرا می‌شود و job امضا تنها با dependency بر آن job، روی runner دارای برچسب `reportflow-signing` و Environment `production-release` اجرا خواهد شد. این جداسازی از نگهداری کلید code-signing در محیط build جلوگیری می‌کند. [1]

| وضعیت انتشار | نتیجه |
|---|---|
| v2.2 روی `main` | CI candidate موفق؛ هنوز tag/release تولیدی ندارد |
| v2.1.1 | job build و archive موفق؛ job `Sign, attest, and publish protected v2 release` در اجرای [`31753669804`](https://github.com/Ali-Marandi/ReportFlow/actions/runs/31753669804) همچنان queued است |
| علت توقف v2.1.1 | runner خصوصی Windows با label لازم و تنظیمات Environment/گواهی معتبر در دسترس نیست |
| اقدام لازم | اجرای راهنمای [Windows Signing Runner Operations](WINDOWS_SIGNING_RUNNER_OPERATIONS.md)، سپس approval production و ادامهٔ workflow موجود |

## یافتهٔ عملیاتی

یک warning غیرمسدودکننده از GitHub Actions ثبت شد: action archive فعلی بر Node.js 20 هدف‌گذاری شده است، اما runner آن را به‌صورت سازگار با Node.js 24 اجرا کرده است. این مورد مانع موفقیت build نشد، ولی باید در چرخهٔ نگهداری وابستگی‌های CI با ارتقای action pin‌شده و اجرای مجدد pipeline بررسی شود.

## کنترل‌های پس از دریافت artifact

پیش از انتشار رسمی، Release Engineer باید checksum archive را با مقدار این گزارش مقایسه کند، SBOM را با vulnerability scanner سازمانی بررسی کند، و پس از امضا `signtool verify /pa /all /tw /v` را روی فایل دانلودشده از Release اجرا کند. فقط پس از عبور از این کنترل‌ها باید release به مشتریان اعلام شود. [2]

## منابع

[1]: https://github.com/Ali-Marandi/ReportFlow/blob/main/.github/workflows/windows-build.yml "ReportFlow Windows CI workflow"
[2]: https://learn.microsoft.com/en-us/dotnet/framework/tools/signtool-exe "Microsoft Learn — SignTool.exe"

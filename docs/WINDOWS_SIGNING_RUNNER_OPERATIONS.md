# راهنمای عملیاتی runner اختصاصی Windows برای امضای دیجیتال ReportFlow

**مالک سند:** تیم Platform Security  
**دامنه:** امضای Authenticode، attestation و انتشار GitHub Release برای ReportFlow  
**وضعیت:** آمادهٔ اجرا؛ وابسته به تهیهٔ گواهی code-signing و میزبان Windows اختصاصی

> این runner یک **مرز امنیتی تولید** است، نه یک ماشین عمومی CI. تنها artifact تأییدشدهٔ ساخته‌شده روی runner میزبانی‌شدهٔ GitHub باید به این محیط برسد؛ هیچ Pull Request، آزمون توسعه یا workflow غیرتولیدی نباید مجاز به اجرا روی آن باشد.

## 1. معماری هدف

خط انتشار فعلی در [workflow ویندوزی پروژه](../.github/workflows/windows-build.yml) دو مرز مجزا دارد. Job نخست روی `windows-latest` آزمون‌ها، audit، SBOM و بستهٔ unsigned را می‌سازد. Job دوم فقط برای tagهای `v2.*` روی runner با برچسب `self-hosted`, `windows`, `reportflow-signing` اجرا می‌شود، artifact تغییرناپذیر را دریافت می‌کند، امضا و تأیید Authenticode را انجام می‌دهد و سپس attestation و GitHub Release را ایجاد می‌کند.

| مؤلفه | مسئولیت | کنترل الزامی |
|---|---|---|
| Runner ساخت | آزمون، `pip-audit`، CycloneDX SBOM و PyInstaller | میزبانی‌شده، ephemeral و بدون کلید امضا |
| Artifact unsigned | مرز انتقال build به امضا | نام مبتنی بر SHA commit، retention کوتاه و checksum |
| Runner امضا | امضا، verification، archive و انتشار | Windows اختصاصی، runner-group محدود، بدون اجرای کد PR |
| HSM/KSP و گواهی | نگهداری کلید خصوصی non-exportable | ACL محدود به هویت سرویس امضا؛ عدم export و عدم نگهداری PFX production |
| GitHub Environment | حفاظت از variables و secrets انتشار | required reviewer، دسترسی محدود به tagهای release و ثبت audit |

GitHub تصریح می‌کند که self-hosted runnerها مانند VMهای ephemeral ایزوله نیستند و اجرای کد غیرقابل اعتماد می‌تواند آن‌ها را به‌طور پایدار آلوده کند. بنابراین runner امضا باید اختصاصی، محدود به repository مورد اعتماد و جدا از مسیر Pull Request باشد. [1]

## 2. دو الگوی قابل‌استفاده

| رویکرد | مناسب برای | مزیت | ملاحظه |
|---|---|---|---|
| **Windows Server/VM اختصاصی + HSM/KSP محلی** | انتشارهای سازمانی با کنترل کامل | کلید هرگز از محل امضا خارج نمی‌شود؛ با workflow فعلی سازگار است | نگهداری VM، patching و HSM بر عهدهٔ سازمان است |
| **سرویس امضای مدیریت‌شدهٔ سازمانی** | سازمانی که HSM عملیاتی ندارد | کاهش نگهداری دستگاه و قابلیت‌پذیری بالاتر | نیازمند اتصال vendor-specific و بازطراحی محدود job امضا است |

برای وضعیت فعلی ReportFlow، الگوی اول توصیه می‌شود؛ زیرا `tools/sign-release.ps1` برای `certificate-store` طراحی شده و تولید production PFX را صراحتاً مسیر نامناسب می‌داند.

## 3. پیش‌نیازهای اجرایی

یک Windows Server یا Windows 11 Enterprise x64 اختصاصی فراهم کنید که عضو domain تولید یا network segment کم‌اعتماد نباشد. برای runner یک حساب سرویس مستقل، بدون interactive logon و بدون local administrator دائمی بسازید. فقط تیم Release Engineering و Platform Security باید حق مدیریت آن حساب را داشته باشند.

گواهی سازمانی **OV/EV Code Signing** را از CA معتبر تهیه و کلید خصوصی را در HSM یا KSP غیرقابل export ایجاد کنید. گواهی باید دارای EKU «Code Signing» باشد. به‌جای نگهداری رمز یا PFX در GitHub، تنها thumbprint گواهی در GitHub نگهداری می‌شود؛ کلید خصوصی باید در دستگاه امضا باقی بماند. SignTool از امضا، timestamp و verification پشتیبانی می‌کند و برای signing/timestamping استفاده از SHA-256 برای digestها توصیه شده است. [2]

| دسته | حداقل نیاز |
|---|---|
| سیستم‌عامل | Windows به‌روز و پشتیبانی‌شده، x64، Patch سطح سازمانی |
| ابزارها | GitHub Actions runner، Windows SDK شامل `signtool.exe`، driver/middleware HSM و PowerShell 7 |
| هویت | حساب سرویس اختصاصی مانند `svc-reportflow-signing` با حداقل دسترسی |
| شبکهٔ خروجی | GitHub Actions، endpoint timestamp HTTPS، OCSP/CRL و endpoint لازم HSM/vendor |
| شبکهٔ ورودی | هیچ inbound عمومی؛ RDP فقط از jump host دارای MFA و زمان‌بندی‌شده |
| کلید | non-exportable، HSM/KSP-backed، ACL فقط برای حساب سرویس امضا |

## 4. آماده‌سازی و سخت‌سازی میزبان

ابتدا image پایه را مطابق baseline سازمان patch کنید، Windows Defender/EDR را فعال نگه دارید و BitLocker را برای volume سیستم و volume runner اعمال کنید. سرویس‌های غیرضروری، browser عمومی، ابزارهای توسعهٔ غیرمجاز و local administratorهای اضافی را حذف کنید. firewall باید به‌صورت allow-list باشد و دسترسی اینترنت runner را به مقصدهای لازم محدود کند.

Runner امضا نباید به production database، secret manager عمومی، فایل‌سرور مشتری یا محیط build توسعه دسترسی شبکه داشته باشد. logهای Windows Event، EDR و GitHub Actions باید به SIEM ارسال شوند. هرگونه تغییر در `.github/workflows/`، `tools/sign-release.ps1` یا تنظیمات Environment باید نیازمند تأیید دو نفره باشد.

GitHub توصیه می‌کند permissions توکن حداقل باشد، secretها به‌صورت plaintext در workflow قرار نگیرند، actionها با full commit SHA pin شوند و Environment برای بازبینی دسترسی به secretها استفاده شود. workflow فعلی ReportFlow این الگو را با default read-only permission و actionهای SHA-pinned شروع کرده است. [3]

## 5. ثبت runner در GitHub Actions

در GitHub به **Repository → Settings → Actions → Runners → New self-hosted runner** بروید و Windows x64 را انتخاب کنید. فرمان‌های generated شده در همان صفحه را فقط روی میزبان مورد اعتماد اجرا کنید؛ token ثبت runner موقتی است و GitHub برای آن اعتبار یک‌ساعته اعلام می‌کند. [4]

در PowerShell دارای دسترسی Administrator، مسیر `C:\actions-runner` را بسازید و archive runner را با فرمان تولیدشده از GitHub در آن extract کنید. سپس runner را با نام ثابت و label اختصاصی ثبت کنید. نمونهٔ زیر قالب فرمان است؛ URL دانلود، token و version باید از صفحهٔ GitHub همان لحظه گرفته شوند و هرگز در repository یا سند ثبت نشوند.

```powershell
New-Item -ItemType Directory -Force C:\actions-runner | Out-Null
Set-Location C:\actions-runner
# archive و token موقتی را فقط از صفحهٔ GitHub دریافت کنید.
.\config.cmd --url https://github.com/Ali-Marandi/ReportFlow `
  --token <ONE_HOUR_REGISTRATION_TOKEN> `
  --name reportflow-signing-win-01 `
  --labels reportflow-signing `
  --runasservice
```

Windows به‌صورت پیش‌فرض labelهای `self-hosted`, `Windows` و `X64` را اضافه می‌کند؛ label سفارشی `reportflow-signing` همان label سوم workflow ReportFlow است. برای اجرای service روی Windows، GitHub اجرای setup با دسترسی Administrator و استفاده از `C:\actions-runner` را توصیه می‌کند. [4]

پس از ثبت، در `services.msc` یا با فرمان زیر مطمئن شوید service اجراست. GitHub بیان می‌کند که اگر در setup اولیه گزینهٔ service انتخاب نشده باشد، باید runner را حذف و دوباره configure کرد تا service نصب شود. [5]

```powershell
Get-Service "actions.runner.*"
Start-Service "actions.runner.*"
Get-Content C:\actions-runner\_diag\Runner_*.log -Tail 100
```

## 6. نصب گواهی و اعتبارسنجی HSM

گواهی و کلید را طبق دستور vendor HSM برای **حساب سرویس runner** در store مناسب install کنید. مسیر فعلی `sign-release.ps1` با `signtool sign /sha1 <thumbprint>` کار می‌کند؛ بنابراین store پیش‌فرض `My` برای هویت service استفاده می‌شود. اگر تیم امنیتی استفاده از `LocalMachine\My` را الزامی می‌داند، باید سوئیچ `/sm` در script فعال و ACL کلید به هویت service محدود شود؛ این تغییر باید با smoke test و review جداگانه انجام شود.

پیش از هر release، وجود گواهی، زنجیره، EKU و دسترسی HSM را بررسی کنید. برای جلوگیری از نشت کلید، اطلاعات provider، PIN یا credentials HSM را در log چاپ نکنید.

```powershell
# در context همان حساب سرویس runner اجرا شود.
Get-ChildItem Cert:\CurrentUser\My | Where-Object Thumbprint -eq '<THUMBPRINT>' |
  Format-List Subject, Thumbprint, NotBefore, NotAfter, HasPrivateKey, EnhancedKeyUsageList

$signTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse |
  Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
& $signTool verify /pa /all /tw /v C:\staging\ReportFlow.exe
```

در smoke test یک executable غیرتولیدی را امضا و سپس با `signtool verify /pa /all /tw /v` تأیید کنید. `/tr` و `/td SHA256` برای RFC 3161 timestamp و SHA-256 باید در امضای واقعی استفاده شوند؛ timestamp سبب می‌شود اعتبار امضا پس از انقضای گواهی قابل بررسی باقی بماند. [2] [6]

## 7. پیکربندی Environment محافظت‌شده در GitHub

در **Repository → Settings → Environments** محیطی به نام `production-release` ایجاد کنید. سپس required reviewerهای مستقل از فرد tag-creator را فعال کنید و deployment branch/tag را به tagهای release کنترل‌شده محدود نمایید. GitHub اجازه می‌دهد Environment پیش از approval به workflow دسترسی به secretها ندهد. [3]

| نام تنظیم | محل نگهداری | مقدار production |
|---|---|---|
| `REPORTFLOW_SIGNING_MODE` | Environment variable | `certificate-store` |
| `REPORTFLOW_TIMESTAMP_URL` | Environment variable | endpoint HTTPS RFC 3161 مورد تأیید سازمان |
| `REPORTFLOW_CERTIFICATE_THUMBPRINT` | Environment secret مطابق workflow فعلی | thumbprint 40-کاراکتری گواهی production |
| `REPORTFLOW_PFX_BASE64` | نباید در production تعریف شود | ندارد |
| `REPORTFLOW_PFX_PASSWORD` | نباید در production تعریف شود | ندارد |

thumbprint به‌تنهایی کلید خصوصی نیست، اما چون workflow فعلی آن را secret می‌خواند، قرارداد فعلی را حفظ کنید. `SIGNING_MODE=pfx` فقط برای محیط آزمایش private و کلید موقت قابل‌قبول است؛ هرگز برای production استفاده نشود.

## 8. کنترل دسترسی و جداسازی workflow

runner را در runner group اختصاصی قرار دهید و فقط repository `Ali-Marandi/ReportFlow` را مجاز کنید. هیچ workflow با triggerهای PR، `pull_request_target` یا job توسعه نباید label `reportflow-signing` را درخواست کند. Job امضا باید فقط tag حفاظت‌شدهٔ `v2.*` و artifact job build وابسته را بپذیرد؛ همین الگو در workflow فعلی پیاده‌سازی شده است.

در repository ruleset، برای `main` و tagهای `v*` حداقل این کنترل‌ها را فعال کنید: required status checks، approval برای Pull Request، محدودیت ایجاد/حذف tag، CODEOWNERS برای workflow و script امضا، و ممنوعیت force-push. GitHub هشدار می‌دهد که self-hosted runnerها نباید به‌طور معمول برای repositoryهای public استفاده شوند، زیرا PRهای untrusted می‌توانند محیط runner را compromise کنند. [1]

## 9. Runbook انتشار

| گام | مسئول | شاهد موفقیت |
|---|---|---|
| 1. تأیید CI | Release Engineer | `test-and-package` سبز، SBOM و artifact موجود |
| 2. تأیید provenance | Security Approver | SHA commit، checksum artifact و scope تغییرات پذیرفته شده |
| 3. ساخت tag | Release Manager | tag حفاظت‌شدهٔ `v2.x.y` روی commit تأییدشده |
| 4. approval Environment | دو reviewer مجزا | approval ثبت‌شده در GitHub Environment |
| 5. امضا | runner اختصاصی | `SignTool verify` و `Get-AuthenticodeSignature` هر دو `Valid` |
| 6. انتشار | GitHub Actions | zip امضاشده، `SHA256SUMS.json`، `sbom.cdx.json` و attestation در Release |
| 7. کنترل پس از انتشار | Release Engineer | دانلود مستقل، hash check و verification امضا روی ماشین پاک |

## 10. پایش، نگهداری و واکنش به رخداد

هر هفته وضعیت service، patchهای Windows/SDK/HSM، انقضای گواهی و فضای دیسک runner را بررسی کنید. هر ماه دسترسی runner group، Environment reviewerها، secretها و audit log GitHub را بازبینی کنید. به محض مشاهدهٔ اجرای job ناشناس، تغییر certificate store، خروجی غیرمنتظرهٔ SignTool یا رفتار مشکوک EDR، service runner را متوقف کنید، runner را offline کنید، artifact/release را quarantine کنید و در صورت احتمال compromise با CA برای revoke گواهی هماهنگ شوید.

```powershell
Stop-Service "actions.runner.*"
Get-Service "actions.runner.*"
```

## منابع

[1]: https://docs.github.com/en/actions/reference/security/secure-use "GitHub Docs — Secure use reference"
[2]: https://learn.microsoft.com/en-us/dotnet/framework/tools/signtool-exe "Microsoft Learn — SignTool.exe"
[3]: https://docs.github.com/en/actions/reference/security/secure-use "GitHub Docs — Secrets, Environments, permissions and self-hosted runner hardening"
[4]: https://docs.github.com/actions/hosting-your-own-runners/adding-self-hosted-runners "GitHub Docs — Adding self-hosted runners"
[5]: https://docs.github.com/actions/hosting-your-own-runners/managing-self-hosted-runners/configuring-the-self-hosted-runner-application-as-a-service "GitHub Docs — Configuring self-hosted runner as a service"
[6]: https://learn.microsoft.com/en-us/windows/win32/seccrypto/time-stamping-authenticode-signatures "Microsoft Learn — Time Stamping Authenticode Signatures"

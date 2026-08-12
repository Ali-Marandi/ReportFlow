# دستورالعمل امضای کد و انتشار نهایی ReportFlow v2.0

## اصل حاکمیتی

در v2.0، build و test روی runner موقت GitHub انجام می‌شود؛ اما مرحلهٔ امضا و انتشار فقط پس از approval در GitHub Environment با نام `production-release` و روی runner اختصاصی Windows انجام می‌شود. این جداسازی از دسترسی secret/signing key برای buildهای عادی و pull requestها جلوگیری می‌کند. GitHub توصیه می‌کند permissions در حداقل سطح باشند، secretها review و rotate شوند و actionهای ثالث به commit SHA ثابت pin شوند.[1]

> **هیچ certificate، PFX، password، token یا secret واقعی را در source، config، issue، pull request یا آرگومان command-line قرار ندهید.** کلید production باید non-exportable و ترجیحاً در HSM/KSP باشد.

## 1. پیش‌نیازهای یک‌باره

| حوزه | تنظیم لازم | مالک |
|---|---|---|
| Certificate | گواهی معتبر Authenticode با private key non-exportable در HSM/KSP runner | PKI/Security |
| Signing runner | Windows خصوصی، ephemeral یا بازسازی‌شونده، labelهای `self-hosted`, `windows`, `reportflow-signing`، بدون دسترسی عمومی PR | Platform Engineering |
| GitHub Environment | محیط `production-release` با required reviewers، محدودیت branch/tag و secret/variableهای محیطی | Repository Admin |
| Protected tags | حفاظت از الگوی `v2.*` و محدودیت create/update tag به release managers | Repository Admin |
| GitHub Actions | فقط actionهای pinned؛ default `GITHUB_TOKEN` روی read؛ permissions job-level | Repository Admin |
| Vault/Secrets | signer runner و control plane با workload identity و least privilege | Security Engineering |

Runner امضا نباید برای PRهای fork، buildهای untrusted یا workflowهای آزمایشی استفاده شود. GitHub هشدار می‌دهد self-hosted runnerها در برابر کد untrusted ایزوله نیستند؛ بنابراین runner امضا باید فقط به repository و workflow protected محدود شود.[1]

## 2. تنظیم GitHub Environment

در repository settings محیط `production-release` را بسازید و حداقل یک Security approver و یک Release Manager برای آن الزامی کنید. متغیرهای زیر را در **Environment** و نه repository-wide configuration تعریف کنید:

| نام | محل | مقدار/کاربرد |
|---|---|---|
| `REPORTFLOW_SIGNING_MODE` | Environment variable | `certificate-store` برای production؛ `pfx` فقط برای rehearsal خصوصی |
| `REPORTFLOW_TIMESTAMP_URL` | Environment variable | HTTPS URL سرویس RFC 3161 مورد تأیید PKI |
| `REPORTFLOW_CERTIFICATE_THUMBPRINT` | Environment secret | thumbprint ۴۰ کاراکتری certificate-store/HSM |
| `REPORTFLOW_TEST_PFX_BASE64` | Environment secret | فقط test private؛ در production خالی باشد |
| `REPORTFLOW_TEST_PFX_PASSWORD` | Environment secret | فقط test private؛ در production خالی باشد |

مقدار `REPORTFLOW_SIGNING_MODE=certificate-store` مسیر production است. اسکریپت `tools/sign-release.ps1` با SignTool گواهی را از certificate store runner انتخاب، با SHA-256 امضا و RFC 3161 timestamp می‌کند؛ سپس `verify /pa /all /tw` را اجرا می‌کند. Microsoft برای SignTool مشخص‌کردن digest در `/fd` و `/td` را لازم می‌داند و SHA-256 را توصیه می‌کند.[2]

## 3. آماده‌سازی signing runner

1. Windows SDK را نصب کنید تا `signtool.exe` در دسترس باشد.
2. certificate را با private key **غیرقابل export** در `Cert:\CurrentUser\My` یا `Cert:\LocalMachine\My` هویت runner نصب کنید. ACL private key فقط به account سرویس runner مجوز دهد.
3. runner را در network segment محدود قرار دهید. egress فقط به GitHub، timestamp authority، package registry مصوب و destinationهای observability مجاز باشد.
4. GitHub runner service را با account محدود اجرا کنید و به آن local administrator، browser profile یا credential تعاملی ندهید.
5. logging را به SIEM ارسال کنید. لاگ SignTool، certificate thumbprint و release metadata نگه‌داری می‌شوند؛ PFX/password یا token هرگز log نمی‌شوند.
6. روی runner یک rehearsal با certificate تست انجام دهید و نتیجهٔ `Get-AuthenticodeSignature` را ثبت کنید.

## 4. اجرای انتشار v2.0

قبل از tag، ownerها باید تمام blockerهای برنامهٔ تست نفوذ را ببندند، release notes را تأیید کنند و حتماً یک build سبز از commit موردنظر داشته باشند. سپس release manager tag را از `main` ایجاد می‌کند:

```bash
git checkout main
git pull --ff-only origin main
git tag -a v2.0.0 -m "ReportFlow v2.0.0"
git push origin v2.0.0
```

workflow `.github/workflows/windows-build.yml` به‌ترتیب test، dependency audit، SBOM، unsigned package، approval محیط، signing/verification، archive، SHA-256 manifest، provenance attestation و GitHub Release را اجرا می‌کند. GitHub attestation provenance را به workflow، repository، commit SHA و event متصل می‌کند؛ این ادعا باید جداگانه توسط مصرف‌کننده verify شود.[3]

| gate | مدرک لازم | مسئول approval |
|---|---|---|
| Build | تست‌ها، `pip-audit` و package validation سبز | Engineering |
| Security | گزارش pentest و retest بدون Critical/High باز | Security Engineering |
| Signing | `signtool verify` و timestamp معتبر | PKI/Security |
| Supply chain | `SHA256SUMS.json`، SBOM و attestation قابل verify | Release Manager |
| Distribution | release notes، known issues و rollback owner | Product/Support |

## 5. بررسی پس از انتشار و rollback

بعد از release، یک دستگاه Windows تمیز باید archive را دریافت و hash، signature و attestation را verify کند. اگر هر مورد نامعتبر بود، release باید فوراً به‌عنوان draft/disabled علامت‌گذاری، distribution متوقف، certificate/secret مشکوک rotate و incident response شروع شود. **فقط حذف tag راه‌حل کافی نیست**؛ زیرا artifact ممکن است قبلاً دریافت شده باشد.

```powershell
# Verification on a clean Windows machine
Get-FileHash .\ReportFlow-Windows-v2.0.0.zip -Algorithm SHA256
Get-AuthenticodeSignature .\ReportFlow\ReportFlow.exe | Format-List Status,SignerCertificate,TimeStamperCertificate
```

```bash
# Provenance verification
gh attestation verify ReportFlow-Windows-v2.0.0.zip -R Ali-Marandi/ReportFlow
```

## 6. وضعیت این change set

کد pipeline، signing script، tests و runbook آماده شده‌اند؛ **release `v2.0.0` عمداً منتشر نشده است**. پیش از انتشار واقعی باید signing runner/HSM، Environment approval، timestamp authority، secret manager و تست staging طبق این سند توسط مالک سازمانی پیکربندی و تأیید شوند.

## منابع

[1]: https://docs.github.com/en/actions/reference/security/secure-use "GitHub Secure Use Reference"
[2]: https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool "Microsoft SignTool"
[3]: https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds "GitHub — Establish provenance for builds"

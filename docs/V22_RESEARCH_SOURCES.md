# منابع پژوهش v2.2 — صف توزیع، storage و portal

| حوزه | یافتهٔ طراحی | منبع |
|---|---|---|
| S3 integrity و write safety | upload باید checksum داشته باشد؛ `If-None-Match: *` برای جلوگیری از overwrite ناخواسته مناسب است و روی تعارض 409 باید retry کنترل‌شده انجام شود. | [AWS S3 — Object integrity](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html) · [AWS S3 — PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html) |
| Azure Blob | upload نیازمند concurrency control است؛ library از retry پشتیبانی می‌کند و انتقال با checksum قابل‌اعتبارسنجی است. برای هویت production، Microsoft Entra/RBAC بر credential ثابت ترجیح دارد. | [Microsoft Learn — Upload a blob](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-upload) · [Azure Blob Python API](https://learn.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob?view=azure-python) |
| Embedded isolation | portal چندمستاجره باید policy را در زمان صدور session و query enforce کند. RLS دسترسی ردیف را محدود می‌کند؛ OLS metadata حساس را پنهان و workspace separation برای tenantهای بزرگ isolation قوی‌تری می‌دهد. | [Microsoft Learn — Embedded analytics security](https://learn.microsoft.com/en-us/power-bi/developer/embedded/embedded-row-level-security) |

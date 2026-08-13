# منابع رسمی آزمون محلی Keycloak

| موضوع | یافتهٔ مورد استفاده | منبع |
|---|---|---|
| اجرای محلی | Keycloak در development mode با `bin/kc.sh start-dev` اجرا می‌شود؛ این حالت فقط برای توسعه است و نباید production استفاده شود. | [Getting Started](https://www.keycloak.org/getting-started/getting-started-zip) · [Server Configuration](https://www.keycloak.org/server/configuration) |
| Binding محلی | حالت development می‌تواند روی addressهای شبکه listen کند؛ در آزمون ReportFlow با `--http-host=127.0.0.1` محدود شده است. | [Server Configuration](https://www.keycloak.org/server/configuration) |
| Discovery | discovery endpoint در مسیر `/realms/{realm}/.well-known/openid-configuration` قرار دارد. | [OIDC Layers](https://www.keycloak.org/securing-apps/oidc-layers) |
| Endpointها | authorization، token، userinfo و certificate/JWKS در discovery مشخص می‌شوند و Authorization Code flow برای native client مناسب است. | [OIDC Layers](https://www.keycloak.org/securing-apps/oidc-layers) |
| امنیت | Implicit و Direct Grant برای سناریوی native ReportFlow استفاده نشده‌اند؛ Keycloak بر اساس RFC 9700 استفاده از آن‌ها را توصیه نمی‌کند. | [OIDC Layers](https://www.keycloak.org/securing-apps/oidc-layers) |
| IdP model | realmها ایزوله‌اند و Keycloak از user، group، role و protocol mapper برای claims پشتیبانی می‌کند. | [Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/index.html) |

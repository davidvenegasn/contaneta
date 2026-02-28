# Arquitectura — ContaNeta

Mapa de módulos, flujo de request, base de datos, integración SAT y assets estáticos.

---

## 1. Punto de entrada y arranque

| Elemento | Descripción |
|----------|-------------|
| **Entrada** | `app.py` (FastAPI). Arranque típico: `uvicorn app:app --reload` o `./run_server.sh [puerto]`. |
| **Configuración** | `config.py` carga `.env` con `dotenv`. Variables clave: `ENV`, `IS_PROD`, `DEV_MODE`, `SESSION_SECRET`, `DB_PATH`, `SITE_URL`, `STATIC_DIR`, `TEMPLATES_DIR`. |
| **Al arranque** | `apply_migrations(DB_PATH)` → `_startup_config_check()` (SESSION_SECRET, SITE_URL, PHP, storage). Si falla en prod → `RuntimeError`. |

---

## 2. Flujo de una petición HTTP

```
Cliente
   ↓
Middleware: request_id → security_headers → redirect_token (cookie/token ?token=)
   ↓
Ruta (FastAPI) → Depends(get_portal_issuer) en rutas /portal/, /api/, /download/
   ↓
Router (portal, auth, api, admin, invoicing, public, billing)
   ↓
Servicios (session, issuers, users, csrf, subscription, bank_*, pdf_to_excel, …)
   ↓
database.db() / db_rows() / db_execute()  o  db_catalogs() / list_catalog() / search_catalog()
   ↓
Respuesta: HTMLResponse (Jinja) o JSONResponse o FileResponse o RedirectResponse
```

- **404:** `not_found_handler` → HTML amigable o JSON según Accept y si ruta es `/api/`.
- **500:** `server_error_handler` → log completo, respuesta HTML/JSON genérica (sin stack).
- **401/403 (HTTPException):** `http_exception_handler` → HTML: redirect /login o página de error; API: JSON con `{ ok, error: { code, message }, detail }`.

---

## 3. Mapa de módulos

### 3.1 App y config

| Archivo | Rol |
|---------|-----|
| `app.py` | FastAPI app, mount `/static`, Jinja2Templates, exception handlers, middleware, health/ready/status, inclusión de routers. |
| `config.py` | Variables desde ENV: paths, DB, sesión, Stripe, PORTAL_SHELL_V2, etc. |

### 3.2 Routers

| Router | Prefijo | Uso |
|--------|---------|-----|
| `routers/auth.py` | (rutas bajo /login, /signup, /register, /onboarding, etc.) | Login, registro, onboarding, confirmar-perfil, forgot/reset password, terms, privacy. |
| `routers/api.py` | `/api/` | API JSON: clientes, productos, cotizaciones, proveedores, emitidas/recibidas, catálogos, account, reportes PDF/Excel. |
| `routers/public.py` | `/`, `/q/`, `/public/` | Demo, seguridad, cotización pública (ver, responder, gracias). |
| `routers/portal.py` | `/portal/` | HTML del portal: home, facturas, clientes, productos, proveedores, cotizaciones, resumen, plan, bancos (upload PDF, movimientos), config SAT (FIEL), datos fiscales, nómina. |
| `routers/invoicing.py` | (rutas facturación) | Formulario factura, descarga XML/PDF por UUID. |
| `routers/admin.py` | `/admin/` | Dashboard, usuarios, issuers, memberships, ops (sync SAT, etc.), impersonación. |
| `routers/billing.py` | (Stripe) | Checkout, portal de facturación, webhook. |
| `routers/deps.py` | — | `get_portal_issuer`: resuelve identidad por cookie o `?token=`; establece `request.state.issuer_id`, `issuer`, `user_id`, etc. |

### 3.3 Servicios

| Servicio | Función principal |
|----------|-------------------|
| `services/session.py` | Cookie de sesión (firmada HMAC), verify/sign, params de cookie. |
| `services/issuers.py` | get_issuer_by_id, get_issuer_by_token, get_demo_issuer. |
| `services/users.py` | Usuarios, memberships (get_membership). |
| `services/csrf.py` | generate_csrf_token, verify_csrf_token. |
| `services/subscription.py` | Estado de suscripción/plan. |
| `services/action_log.py` | log_action (auditoría). |
| `services/portal_errors.py` | portal_error_type (clasificación errores). |
| `services/pdf_to_excel.py` | Conversión PDF banco → Excel; get_storage_root, safe_join, ensure_parent_dir. |
| `services/bank_*` | Parsing, preview, ingest, cuentas, conciliación CFDI. |
| `services/quotations.py` | Cotizaciones, PDF. |
| `services/form_parse.py` | Parseo formulario factura. |
| `services/rate_limit.py` | Rate limit por IP. |
| `services/jobs.py` | Job system (cola genérica robusta): dedupe, locks, reintentos, backoff. |
| `worker.py` | Worker CLI (claim/execute) para jobs genéricos `jobs`. |
| `services/error_events.py` | Registro de errores 5xx para observabilidad (admin-only details). |
| `services/file_access_log.py` | Auditoría de accesos a archivos servidos (XML/PDF/exports). |
| `services/crypto_at_rest.py` | Cifrado at-rest (AES-GCM) + derivación por issuer. |
| `services/sat_credentials_secure.py` | Guardado/lectura segura de FIEL (cifrada) + env override para PHP. |
| `services/tenant.py` | Helpers mínimos para reforzar aislamiento (issuer_id siempre desde sesión). |

### 3.4 Base de datos

| Archivo | Rol |
|---------|-----|
| `database.py` | `db()` → conexión a invoicing.db (timeout 30s, WAL, busy_timeout, row_factory dict). `db_rows(sql, params)`, `db_execute(sql, params)`. `db_catalogs()` para catalogs.db. `list_catalog(table)`, `search_catalog(table, q, limit)` — **table debe estar en ALLOWED_CATALOG_TABLES** (whitelist); nunca pasar nombre de tabla desde entrada de usuario. `table_exists`, `has_column`, `safe_update`. |
| `migrations_runner.py` | Aplica `migrations/*.sql` ordenados por prefijo numérico; algunas versiones con lógica Python (003, 004, 006, 008, 011, 014, 016, 021, 023). Tabla `schema_migrations`. |
| **DB principal** | `invoicing.db` (por defecto; ruta en `APP_DB_PATH`): issuers, users, memberships, sat_credentials, sat_cfdi, sat_requests, sat_jobs, invoices, quotations, bank_statements, bank_movements, etc. |
| **DB catálogos** | `catalogs/catalogs.db`: tablas SAT (ProdServ, Unidad, etc.). |

---

## 4. Integración SAT (sat_sync)

| Componente | Descripción |
|------------|-------------|
| **PHP** | Requerido para FIEL y descarga masiva. Ejecutado vía `subprocess` desde Python. |
| **check_fiel.php** | Validación de certificados FIEL. Invocado desde `routers/portal.py` `_run_fiel_validation(issuer_id)` con timeout 30s y `APP_DB_PATH` en env. |
| **parse_xml.php** | Parseo de XML CFDI. |
| **sync_xml.php** | Sincronización con SAT (descarga masiva). |
| **verify_requests.php** | Verificación de solicitudes. |
| **cron_sat_sync.sh** | Script cron para ejecutar sync periódicamente. |
| **scripts/sat_worker.py** | Worker Python que procesa cola `sat_jobs`; subprocess con timeout 600s. |

La app no invoca sync directamente en cada request; el sync se hace por cron o worker. En portal solo se invoca check_fiel para validar FIEL al subir.

### 4.1 Seguridad de FIEL (e.firma) en la app
- Los archivos `.cer/.key` se almacenan **cifrados at-rest** como `*.enc` (AES‑GCM) bajo `storage/credentials/{issuer_id}/`.
- La contraseña de la clave se guarda cifrada en DB (`sat_credentials.fiel_key_password` con prefijo `enc:`).
- Para ejecutar PHP (SAT), el backend desencripta a temporales y pasa:
  - `SAT_FIEL_CER_PATH`, `SAT_FIEL_KEY_PATH`, `SAT_FIEL_PASSWORD`
- Scripts PHP (`sat_sync/*.php`) aceptan override por env para no depender de paths/password en claro.

---

## 5. Assets estáticos

| Ruta | Contenido |
|------|-----------|
| `/static` | Montado desde `config.STATIC_DIR` (carpeta `static/`). |
| **CSS** | `form.css`, `portal_tokens.css`, `components.css`, `portal.css`, `portal_ui_v2.css`, `portal_rail.css`, `portal_shell_v2.css` (condicional PORTAL_SHELL_V2). |
| **JS** | `catalog-cache.js`, `ui.js`, `count-up.js`, `portal_drawer.js`, `portal_resumen_collapse.js`, `portal_shell_v2.js`. |
| **Templates** | `templates/` (Jinja2): `base_portal.html`, `base_admin.html`, `portal_*.html`, `form.html`, `form/_section_*.html`, auth, public, partials, components. |

No hay bundler ni build step; carga vía `<link>` y `<script>` en los templates.

---

## 6. Job System (cola robusta)

### 6.1 Tabla `jobs`
Usada para jobs internos del SaaS (no confundir con `sat_jobs` del pipeline SAT legacy).

Campos clave:
- `status`: queued/running/success/failed
- `attempts`, `max_attempts`, `run_after` (reintentos + backoff)
- `locked_by`, `locked_at` (lease)
- `payload_hash` + índice único parcial para **dedupe** en queued/running
- `payload_json`, `result_json`, `error_json`

Implementación:
- `services/jobs.py`: `enqueue_job`, `claim_next_job`, `complete_job`, `fail_job`, `update_progress`
- `worker.py`: `--once` / `--loop`

---

## 7. Observabilidad (mínima)
- `error_events` (DB) guarda 5xx con `request_id` y detalles internos **solo para admin**.
- Panel admin:
  - `/admin/errors` + detalle `/admin/errors/{id}`
  - `/admin/jobs` + detalle `/admin/jobs/{id}`

---

## 8. Backups y recuperación
- DB: `scripts/backup_db.sh` → `backup/invoicing_*.db.gz`
- Storage esencial: `scripts/backup_storage.sh` → `backup/storage_*.tar.gz`
- Restore: ver `RECOVERY_PLAYBOOK.md`

---

## 9. Diagrama de dependencias (simplificado)

```
app.py
  ├── config.py
  ├── migrations_runner.py
  ├── routers (auth, api, portal, admin, invoicing, public, billing)
  │     └── routers/deps.py (get_portal_issuer)
  ├── services (session, issuers, users, csrf, subscription, pdf_to_excel, bank_*, …)
  └── database.py
        └── config (DB_PATH, CATALOGS_DB)
```

---

## 7. Rutas públicas (sin get_portal_issuer)

- `/`, `/favicon.ico`
- `/health`, `/ready`, `/status`
- `/sitemap.xml`, `/robots.txt`
- `/login`, `/signup`, `/register`, `/forgot-password`, `/reset-password`, `/confirmar-perfil`
- `/onboarding`, `/choose-issuer`
- `/demo`, `/seguridad`, `/pricing`, `/terms`, `/privacy`
- `/q/...` (cotización pública), `/public/...`
- Middleware `redirect_token_middleware`: si hay `?token=` y ruta es portal HTML, puede fijar cookie y redirigir.

Todas las rutas bajo `/portal/` (excepto redirects explícitos), `/api/` y `/download/` requieren autenticación vía `get_portal_issuer`.

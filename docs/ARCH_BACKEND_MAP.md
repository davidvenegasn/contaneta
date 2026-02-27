## Mapa rápido del backend (5 min)

### Stack
- **Framework**: FastAPI (en `app.py`)
- **DB**: SQLite (`DB_PATH`), migraciones SQL + runner Python (`migrations/`, `migrations_runner.py`)
- **SAT**: scripts PHP en `sat_sync/` ejecutados vía `services/subprocess_safe.py` (wrapper con timeout)
- **UI**:
  - HTML portal: `routers/portal.py`
  - JSON API: `routers/api.py`

---

### Routers (routers/*.py)

#### `routers/api.py` (prefix `/api`)
APIs JSON consumidas por el portal (clientes, productos, facturas, cotizaciones, proveedores, catálogos SAT).

- **Cuenta / checklist**
  - `GET /api/account/status`
- **Clientes**
  - `GET /api/customers`
  - `POST /api/customers/create`
  - `POST /api/customers/delete`
- **Productos**
  - `GET /api/products`
  - `POST /api/products/create`
  - `POST /api/products/delete`
- **Factura rápida**
  - `GET /api/quick-invoice/bootstrap`
  - `POST /api/invoices/quick`
- **Cotizaciones**
  - `GET /api/quotations`
  - `POST /api/quotations/create`
  - `GET /api/quotations/{qid}`
  - `POST /api/quotations/update-status`
  - `POST /api/quotations/respond`
- **Proveedores + reporte**
  - `GET /api/providers`
  - `POST /api/providers/create`
  - `GET /api/provider-invoices` (alias `GET /api/providers/invoices`)
  - `GET /api/provider-invoices/report` (PDF/Excel)
- **Facturas SAT (listados)**
  - `GET /api/invoices/issued`
  - `GET /api/invoices/received`
  - `GET /api/invoices/pending`
- **Catálogos SAT (desde `catalogs.db`)**
  - `GET /api/catalogs/forma_pago`
  - `GET /api/catalogs/metodo_pago`
  - `GET /api/catalogs/uso_cfdi`
  - `GET /api/catalogs/regimen_fiscal`
  - `GET /api/catalogs/moneda`
  - `GET /api/catalogs/prodserv`
  - `GET /api/catalogs/unidad`

#### `routers/portal.py` (prefix `/portal`)
Rutas HTML del portal, y endpoints JSON internos del portal (banco, SAT status/sync, guardar productos/clientes).

- **Home / creación**
  - `GET /portal/home`
  - `GET /portal/create`, `GET /portal/create/quick`, `GET /portal/create/multi`
- **Listados**
  - `GET /portal/invoices/issued`, `GET /portal/invoices/received`
  - `GET /portal/clients`, `GET /portal/products`, `GET /portal/providers`
  - `GET /portal/quotations` (alias `/portal/cotizaciones`)
- **SAT / CFDI viewer**
  - `POST /portal/sat/sync`
  - `GET /portal/sat/status`
  - `GET /portal/cfdi/issued/{uuid}`, `GET /portal/cfdi/received/{uuid}`
  - `GET /portal/sat/xml/{uuid}`, `GET /portal/sat/pdf/{uuid}`
- **Guardado “portal JSON” (no `/api`)**
  - `POST /portal/products/save`
  - `POST /portal/clients/save`
  - `POST /portal/catalog/backfill`
- **Banco (módulo movimientos / ingest / cuentas)**
  - `GET /portal/bank/statements` (HTML)
  - `POST /portal/bank/statements/ingest`
  - `GET/POST/PUT/DELETE /portal/bank/accounts`
  - `POST /portal/bank/preview/*` (export/reclassify/commit)
  - `POST /portal/bank/matches/{match_id}/confirm|reject`
  - `PATCH /portal/bank/movements/{movement_id}`
  - `POST /portal/bank/movements/delete-all`

#### `routers/invoicing.py` (descargas `/download/*` + submit)
- `POST /submit`
- `GET /download/xml/{uuid}`
- `GET /download/pdf/{uuid}`
- `GET /download/{fmt}/{invoice_id}`

#### `routers/auth.py` (login/signup/recuperación)
Login, registro, verificación email, reset password, elegir issuer, logout, callbacks OAuth.

#### `routers/admin.py` (prefix `/admin`)
- Dashboards, users, issuers, memberships, ops
- `GET /admin/health`, `GET /admin/status`
- Impersonación

#### `routers/public.py` (públicas)
- `GET /pricing`, `/demo`, `/seguridad`
- Cotización pública: `GET /q/{public_token}`, PDF y responder

---

### Services (services/*.py) — responsabilidades (alto nivel)

#### Base / cross-cutting
- `services/session.py`: cookies/sesión y helpers de autenticación
- `services/csrf.py`: tokens CSRF
- `services/subscription.py`: plan Trial/Pro y gating
- `services/action_log.py`: audit log / acciones
- `services/subprocess_safe.py`: wrapper único para subprocess con **timeout obligatorio**
- `services/sanitize.py`: sanitización/normalización de inputs

#### Cotizaciones
- `services/quotations.py`: reglas y acceso para cotizaciones (crear/actualizar, tokens públicos)

#### Banco (movimientos, ingest, conciliación)
- `services/bank_statement_parser.py`: parseo de estados de cuenta
- `services/bank_preview_pipeline.py` + `services/bank_parse_preview.py`: preview, clasificación, dedupe
- `services/bank_statement_ingest.py`: commit a DB, validaciones, ownership
- `services/bank_accounts.py` + `services/bank_own_accounts.py`: cuentas propias y cuentas registradas
- `services/bank_cfdi_matching.py`: conciliación movimientos ↔ CFDI
- `services/bank_*classifier*.py`: clasificación/heurísticas

#### SAT / catálogos
- `services/catalog_from_cfdi.py`: autocaptura de catálogo desde CFDI existente
- Integración PHP vive en `sat_sync/` y se invoca desde el backend con `run_php`

---

### DB schema y migraciones
- **SQL migrations**: `migrations/*.sql`
- **Runner**: `migrations_runner.py`
  - Crea/usa `schema_migrations(version, applied_at)`
  - Aplica migraciones en `startup` (`app.py`) con `apply_migrations(DB_PATH)`
- **Conexión DB**: `database.py` (helpers `db()`, `db_rows()`, etc.)
- **Catálogos SAT**: `catalogs.db` (whitelist en `database.py`)

---

### PHP SAT (sat_sync/)
Scripts relevantes (alto nivel):
- `check_fiel.php`: validación FIEL (se usa desde portal config SAT)
- `sync.php` / `sync_xml.php`: sincronización/descarga
- `verify_requests.php`: verificación de solicitudes SAT
- `parse_xml.php`: parseo de XML descargado a tablas (CFDI)
- `merge_duplicate_cfdis.php`: dedupe

Se ejecutan con timeout vía `services/subprocess_safe.py` y DB path vía env `APP_DB_PATH`.

---

### Flujos clave (resumen)

#### Emitir factura (Facturapi)
- UI: `templates/form.html` + `routers/invoicing.py` (`POST /submit`)
- Backend: `facturapi_client.py` (creación/descarga) + persistencia a DB

#### Listar emitidas/recibidas
- HTML: `routers/portal.py` (páginas)
- JSON: `routers/api.py` (`/api/invoices/issued`, `/api/invoices/received`)
- Fuente: tabla `sat_cfdi` (CFDI descargados/parceados SAT)

#### Banco: preview / ingest
- HTML: portal bank pages (router portal)
- Preview parse: `services/bank_preview_pipeline.py` / `services/bank_parse_preview.py`
- Commit: `services/bank_statement_ingest.py` (persistencia a `bank_statements`/`bank_movements`)

#### SAT sync + verify
- Trigger: `POST /portal/sat/sync`
- Estado: `GET /portal/sat/status` + tablas `sat_jobs` / `sat_sync_state`
- Ejecución: PHP scripts en `sat_sync/` (timeout + env DB)


# Auditoría rápida: db_init.py vs migrations/001_baseline.sql

## 1. ¿Se usa db_init.py?

**Respuesta: NO se usa.**

### Evidencia:
- ❌ **No se importa** en ningún archivo `.py` del proyecto (búsqueda con grep: 0 imports de `db_init`)
- ❌ **No se ejecuta** desde ningún script (no hay `python db_init.py` en `.sh` ni en código)
- ❌ **No se menciona** en documentación operativa (solo aparece en `AUDITORIA_SQLITE_DIAGNOSTICO.md` como referencia histórica)
- ✅ **Sistema actual:** `app.py` importa `migrations_runner` y llama `apply_migrations()` en startup, que aplica `migrations/001_baseline.sql` (y futuras migraciones numeradas)

### Conclusión:
`db_init.py` es código legacy/obsoleto. El proyecto usa el sistema de migraciones (`migrations_runner.py` + `migrations/*.sql`).

---

## 2. Qué crea/modifica db_init.py

### Tablas creadas por db_init.py:
1. **issuers** (líneas 11-18)
2. **issuer_tokens** (líneas 20-27)
3. **frequent_customers** (líneas 29-42) — ⚠️ **no usada por app.py**
4. **invoices** (líneas 44-63)
5. **invoice_items** (líneas 65-75)

### Columnas por tabla (db_init.py):

#### `issuers`:
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `alias TEXT NOT NULL` ⚠️
- `rfc TEXT NOT NULL`
- `facturapi_org_id TEXT NOT NULL` ⚠️
- `whatsapp_e164 TEXT` (opcional)
- `active INTEGER NOT NULL DEFAULT 1`

#### `issuer_tokens`:
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `issuer_id INTEGER NOT NULL`
- `token TEXT NOT NULL UNIQUE`
- `active INTEGER NOT NULL DEFAULT 1`
- `created_at TEXT NOT NULL DEFAULT (datetime('now'))`
- FK a `issuers(id)`

#### `frequent_customers`:
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `issuer_id INTEGER NOT NULL`
- `rfc TEXT NOT NULL`
- `legal_name TEXT NOT NULL`
- `zip TEXT NOT NULL`
- `tax_system TEXT NOT NULL`
- `cfdi_use TEXT NOT NULL`
- `email TEXT`
- `facturapi_customer_id TEXT`
- `created_at TEXT NOT NULL DEFAULT (datetime('now'))`
- UNIQUE(issuer_id, rfc)
- FK a `issuers(id)`

#### `invoices`:
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `issuer_id INTEGER NOT NULL`
- `status TEXT NOT NULL DEFAULT 'created'`
- `currency TEXT NOT NULL DEFAULT 'MXN'`
- `exchange_rate REAL`
- `payment_form TEXT NOT NULL`
- `payment_method TEXT NOT NULL`
- `cfdi_use TEXT NOT NULL`
- `customer_rfc TEXT NOT NULL`
- `customer_legal_name TEXT NOT NULL`
- `customer_zip TEXT NOT NULL`
- `customer_tax_system TEXT NOT NULL`
- `customer_email TEXT`
- `facturapi_invoice_id TEXT`
- `uuid TEXT`
- `total REAL`
- `created_at TEXT NOT NULL DEFAULT (datetime('now'))`
- FK a `issuers(id)`

#### `invoice_items`:
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `invoice_id INTEGER NOT NULL`
- `quantity REAL NOT NULL`
- `description TEXT NOT NULL`
- `product_key TEXT NOT NULL`
- `unit_price REAL NOT NULL`
- `iva_rate REAL NOT NULL DEFAULT 0.16`
- `created_at TEXT NOT NULL DEFAULT (datetime('now'))`
- FK a `invoices(id)`

---

## 3. Comparación: db_init.py vs migrations/001_baseline.sql

### 3.1 Tablas que existen en ambos

#### `issuers` — DIVERGENCIAS CRÍTICAS

| Aspecto | db_init.py | migrations/001_baseline.sql |
|---------|------------|----------------------------|
| **Columna nombre** | `alias TEXT NOT NULL` | `razon_social TEXT` (nullable) |
| **facturapi_org_id** | `TEXT NOT NULL` (obligatorio) | `TEXT` (nullable) |
| **regimen_fiscal** | ❌ No existe | ✅ `regimen_fiscal TEXT` |
| **created_at** | ❌ No existe | ✅ `created_at TEXT NOT NULL DEFAULT (datetime('now'))` |
| **updated_at** | ❌ No existe | ✅ `updated_at TEXT NOT NULL DEFAULT (datetime('now'))` |
| **whatsapp_e164** | ✅ Existe (opcional) | ❌ No existe |
| **rfc** | `TEXT NOT NULL` | `TEXT` (nullable) |

**Resumen:** `db_init.py` define un esquema incompatible con el código real:
- El código usa `razon_social` (SELECT en `get_issuer_by_token`), no `alias`
- El código necesita `regimen_fiscal` (usado en múltiples lugares)
- El código necesita `created_at`/`updated_at` (timestamps estándar)
- `facturapi_org_id` debe ser nullable (puede no existir en instalaciones antiguas)

---

#### `issuer_tokens` — COINCIDENCIA PARCIAL

| Aspecto | db_init.py | migrations/001_baseline.sql |
|---------|------------|----------------------------|
| **updated_at** | ❌ No existe | ✅ `updated_at TEXT NOT NULL DEFAULT (datetime('now'))` |
| **Índice issuer_id** | ❌ No se crea | ✅ `CREATE INDEX idx_issuer_tokens_issuer_id` |

**Resumen:** `001_baseline.sql` añade `updated_at` e índice que faltan en `db_init.py`.

---

#### `invoices` — DIVERGENCIAS IMPORTANTES

| Aspecto | db_init.py | migrations/001_baseline.sql |
|---------|------------|----------------------------|
| **Columnas básicas** | ✅ Coinciden (issuer_id, status, currency, exchange_rate, payment_form, payment_method, cfdi_use, customer_*, facturapi_invoice_id, uuid, total, created_at) | ✅ Coinciden |
| **Columnas extra** | ❌ No tiene | ✅ `export_code TEXT`, `tipo_comprobante TEXT`, `series TEXT`, `folio_number TEXT`, `order_ref TEXT`, `issue_date TEXT`, `notes TEXT`, `cancelled INTEGER NOT NULL DEFAULT 0` |
| **Índices** | ❌ No se crean | ✅ `idx_invoices_issuer_uuid`, `idx_invoices_issuer_payment_method`, `idx_invoices_issuer_issue_date` |

**Resumen:** `db_init.py` crea una tabla `invoices` mínima que no incluye columnas usadas por `_safe_update()` y SELECTs del código (`export_code`, `tipo_comprobante`, `series`, `folio_number`, `order_ref`, `issue_date`, `notes`, `cancelled`). Además, faltan índices críticos para performance.

---

#### `invoice_items` — DIVERGENCIAS MENORES

| Aspecto | db_init.py | migrations/001_baseline.sql |
|---------|------------|----------------------------|
| **Columnas básicas** | ✅ Coinciden (invoice_id, quantity, description, product_key, unit_price, iva_rate, created_at) | ✅ Coinciden |
| **Columnas opcionales** | ❌ No tiene | ✅ `unit_key TEXT`, `discount REAL` |
| **Índice** | ❌ No se crea | ✅ `idx_invoice_items_invoice_id` |

**Resumen:** `db_init.py` no incluye `unit_key` y `discount` que el código usa dinámicamente (vía PRAGMA table_info). Falta índice.

---

### 3.2 Tablas que solo existen en migrations/001_baseline.sql

`db_init.py` **NO crea** estas tablas que sí existen en `001_baseline.sql`:

1. **sat_credentials** — Credenciales FIEL por emisor
2. **sat_sync_state** — Estado de sincronización SAT
3. **sat_cfdi** — CFDI descargados del SAT (tabla principal)
4. **sat_requests** — Requests de descarga masiva SAT
5. **sat_jobs** — Jobs de procesamiento SAT
6. **customer_profiles** — Perfiles de clientes (la app usa esto, no `frequent_customers`)
7. **supplier_profiles** — Perfiles de proveedores
8. **issuer_products** — Productos/servicios por emisor
9. **quotations** — Cotizaciones
10. **quotation_items** — Items de cotizaciones
11. **payment_relations** — Relaciones de pagos (CFDI P)

**Resumen:** `db_init.py` solo crea 5 tablas básicas. `001_baseline.sql` crea 16 tablas completas necesarias para que la app funcione.

---

### 3.3 Tablas que solo existen en db_init.py

**frequent_customers** — ⚠️ **No usada por app.py**

- `db_init.py` crea `frequent_customers`
- `app.py` usa `customer_profiles` (creada por `ensure_customer_profiles_table()` y `001_baseline.sql`)
- `frequent_customers` es código legacy/obsoleto

---

## 4. Resumen de divergencias concretas

### Divergencias críticas (incompatibilidad con código):

| # | Tabla | Divergencia | Impacto |
|---|-------|-------------|---------|
| 1 | **issuers** | `alias` vs `razon_social` | ❌ **CRÍTICO**: El código SELECT usa `razon_social`, no `alias`. Si se crea con `db_init.py`, el SELECT fallará. |
| 2 | **issuers** | `facturapi_org_id NOT NULL` vs nullable | ⚠️ **ALTO**: En instalaciones antiguas puede no existir. Debe ser nullable. |
| 3 | **issuers** | Falta `regimen_fiscal` | ❌ **CRÍTICO**: El código usa `regimen_fiscal` en múltiples lugares. Sin esta columna, fallarán queries y lógica de negocio. |
| 4 | **issuers** | Falta `created_at`/`updated_at` | ⚠️ **MEDIO**: Timestamps estándar esperados por el código. |
| 5 | **invoices** | Faltan columnas: `export_code`, `tipo_comprobante`, `series`, `folio_number`, `order_ref`, `issue_date`, `notes`, `cancelled` | ⚠️ **ALTO**: `_safe_update()` y SELECTs las usan. Sin ellas, funcionalidad limitada. |
| 6 | **invoice_items** | Faltan `unit_key`, `discount` | ⚠️ **BAJO**: Se manejan dinámicamente vía PRAGMA, pero mejor tenerlas. |

### Divergencias de completitud (tablas faltantes):

| # | Tabla faltante en db_init.py | Impacto |
|---|------------------------------|---------|
| 1 | **sat_cfdi** | ❌ **CRÍTICO**: Tabla principal del sistema. Sin ella, la app no puede funcionar. |
| 2 | **customer_profiles** | ❌ **CRÍTICO**: La app usa esto, no `frequent_customers`. Sin ella, gestión de clientes falla. |
| 3 | **supplier_profiles** | ⚠️ **ALTO**: Gestión de proveedores no funciona. |
| 4 | **issuer_products** | ⚠️ **ALTO**: Productos/servicios no se pueden guardar. |
| 5 | **quotations** / **quotation_items** | ⚠️ **ALTO**: Sistema de cotizaciones no funciona. |
| 6 | **payment_relations** | ⚠️ **ALTO**: CFDI P (pagos) no funciona. |
| 7 | **sat_credentials**, **sat_sync_state**, **sat_requests**, **sat_jobs** | ⚠️ **MEDIO**: Funcionalidad SAT no funciona (si se usa sat_sync). |

### Divergencias de índices:

| Tabla | db_init.py | migrations/001_baseline.sql |
|-------|------------|----------------------------|
| **issuer_tokens** | ❌ Sin índices | ✅ `idx_issuer_tokens_issuer_id` |
| **invoices** | ❌ Sin índices | ✅ `idx_invoices_issuer_uuid`, `idx_invoices_issuer_payment_method`, `idx_invoices_issuer_issue_date` |
| **invoice_items** | ❌ Sin índices | ✅ `idx_invoice_items_invoice_id` |

---

## 5. Conclusión

### db_init.py se usa / no se usa:
**NO se usa.** Es código legacy/obsoleto. El proyecto actual usa `migrations_runner.py` + `migrations/001_baseline.sql`.

### Divergencias concretas:

1. **issuers**: `alias` vs `razon_social` (incompatible con código)
2. **issuers**: `facturapi_org_id NOT NULL` vs nullable (debe ser nullable)
3. **issuers**: Falta `regimen_fiscal` (requerido por código)
4. **issuers**: Faltan `created_at`/`updated_at` (timestamps estándar)
5. **invoices**: Faltan 8 columnas usadas por código (`export_code`, `tipo_comprobante`, `series`, `folio_number`, `order_ref`, `issue_date`, `notes`, `cancelled`)
6. **invoice_items**: Faltan `unit_key`, `discount` (usadas dinámicamente)
7. **Faltan 11 tablas** completas necesarias para que la app funcione (sat_cfdi, customer_profiles, supplier_profiles, issuer_products, quotations, quotation_items, payment_relations, sat_credentials, sat_sync_state, sat_requests, sat_jobs)
8. **Faltan índices** en issuer_tokens, invoices, invoice_items
9. **frequent_customers** existe solo en db_init.py pero no se usa (legacy)

### Recomendación:
**Eliminar o deprecar `db_init.py`** y documentar que el sistema de migraciones (`migrations/001_baseline.sql`) es la única fuente de verdad para crear la base de datos desde cero.

# Auditoría SQLite — Diagnóstico (Backend / app.py)

**Objetivo:** Listar tablas y columnas que el backend asume, índices recomendados e inconsistencias detectadas. Sin implementar cambios.

---

## 1. Tabla → columnas requeridas por el código

Resumen por tabla según **SELECT / INSERT / UPDATE** en `app.py` y scripts de migración (`db_migrate_*.py`, `db_init.py`).

### 1.1 `issuers`

| Origen | Columnas usadas |
|--------|------------------|
| **SELECT** (get_issuer_by_token) | `id`, `rfc`, `razon_social`, `regimen_fiscal`, `active` |
| **Código (dict devuelto)** | También se usa `facturapi_org_id` vía `d.get("facturapi_org_id")` — **no está en el SELECT** |
| **UPDATE** (db_migrate_add_david_venegas) | `regimen_fiscal`, `razon_social`, `rfc` |

**Columnas requeridas por el código:** `id`, `rfc`, `razon_social`, `regimen_fiscal`, `active`.  
**Columnas usadas pero no seleccionadas:** `facturapi_org_id`.

---

### 1.2 `issuer_tokens`

| Origen | Columnas usadas |
|--------|------------------|
| **SELECT** (get_issuer_by_token) | `token`, `issuer_id` (join) |
| **INSERT** (db_migrate_*) | `issuer_id`, `token`, `active` |

**Columnas requeridas:** `id`, `issuer_id`, `token`, `active`.

---

### 1.3 `sat_cfdi`

| Origen | Columnas usadas |
|--------|------------------|
| **SELECT** (múltiples vistas/APIs) | `issuer_id`, `direction`, `fecha_emision`, `nombre_receptor`, `nombre_emisor`, `uuid`, `rfc_receptor`, `rfc_emisor`, `total`, `moneda`, `status`, `xml_path`, `serie`, `folio`, `concepto`, `forma_pago`, `metodo_pago`, `uso_cfdi`, `subtotal`, `descuento`, `impuestos`, `tipo_comprobante`, `xml_status`, `retenciones` (opcional vía _has_column) |
| **ALTER en app.py** | `concepto` (TEXT), `retenciones` (REAL) |

**Columnas requeridas:**  
`id`, `issuer_id`, `direction`, `uuid`, `status`, `fecha_emision`, `rfc_emisor`, `nombre_emisor`, `rfc_receptor`, `nombre_receptor`, `total`, `moneda`, `tipo_comprobante`, `xml_path`, `metadata_json`, `created_at`, `updated_at`, `serie`, `folio`, `forma_pago`, `metodo_pago`, `uso_cfdi`, `subtotal`, `descuento`, `impuestos`, `lugar_expedicion`, `condiciones_pago`, `xml_status`, `xml_sha256`, `xml_downloaded_at`, `parsed_at`, `parse_version`, `concepto`, `retenciones`.

---

### 1.4 `customer_profiles`

| Origen | Columnas usadas |
|--------|------------------|
| **SELECT** (api_customers) | `id`, `rfc`, `legal_name`, `zip`, `tax_system`, `email`, `alias` |
| **INSERT/UPDATE** (submit, api_customers_create) | `issuer_id`, `rfc`, `legal_name`, `zip`, `tax_system`, `email`, `alias`, `updated_at` |
| **DELETE** (api_customers_delete) | `issuer_id`, `rfc` |

**Columnas requeridas:** `id`, `issuer_id`, `rfc`, `legal_name`, `zip`, `tax_system`, `email`, `alias`, `created_at`, `updated_at`.

---

### 1.5 `supplier_profiles`

| Origen | Columnas usadas |
|--------|------------------|
| **SELECT** (api_providers) | `rfc`, `legal_name`, `email`, `alias` |
| **INSERT/UPDATE** (api_providers_create) | `issuer_id`, `rfc`, `legal_name`, `zip`, `tax_system`, `email`, `alias`, `updated_at` |

**Columnas requeridas:** `id`, `issuer_id`, `rfc`, `legal_name`, `zip`, `tax_system`, `email`, `alias`, `created_at`, `updated_at`.

---

### 1.6 `quotations`

| Origen | Columnas usadas |
|--------|------------------|
| **SELECT** (varios) | `id`, `issuer_id`, `folio`, `customer_rfc`, `customer_legal_name`, `customer_email`, `status`, `public_token`, `valid_until`, `notes`, `responded_at`, `created_at`, `updated_at`, `iva_rate`, `currency`, `rejection_reason`, `sent_at`, `accepted_at`, `rejected_at`, `decision_ip`, `decision_user_agent` |
| **INSERT** (api_quotations_create) | `issuer_id`, `folio`, `customer_rfc`, `customer_legal_name`, `customer_email`, `status`, `public_token`, `notes`, `iva_rate`, `currency`, `sent_at`, `updated_at` |
| **UPDATE** (api_quotations_update_status, respond) | `status`, `updated_at`, `responded_at`, `accepted_at`, `rejected_at`, `decision_ip`, `decision_user_agent`, `rejection_reason` |

**Columnas requeridas:**  
`id`, `issuer_id`, `folio`, `customer_rfc`, `customer_legal_name`, `customer_email`, `status`, `public_token`, `valid_until`, `notes`, `responded_at`, `created_at`, `updated_at`, `iva_rate`, `currency`, `sent_at`, `accepted_at`, `rejected_at`, `decision_ip`, `decision_user_agent`, `rejection_reason`.

---

### 1.7 `quotation_items`

| Origen | Columnas usadas |
|--------|------------------|
| **SELECT** (varios) | `id`, `quotation_id`, `description`, `quantity`, `unit_price`, `iva_rate`, `product_id`, `sort_order`, `extra_desc` (opcional) |
| **INSERT** (api_quotations_create) | `quotation_id`, `description`, `quantity`, `unit_price`, `iva_rate`, `product_id`, `sort_order` |

**Columnas requeridas:** `id`, `quotation_id`, `description`, `quantity`, `unit_price`, `iva_rate`, `product_id`, `sort_order`, `extra_desc`.

---

### 1.8 `issuer_products`

| Origen | Columnas usadas |
|--------|------------------|
| **SELECT** (api_products) | `id`, `description`, `product_key`, `unit_key`, `unit_price`, `iva_rate`, `created_at` |
| **INSERT** (api_products_create) | `issuer_id`, `description`, `product_key`, `unit_key`, `unit_price`, `iva_rate` |

**Columnas requeridas:** `id`, `issuer_id`, `description`, `product_key`, `unit_key`, `unit_price`, `iva_rate`, `created_at`.

---

### 1.9 `invoices`

| Origen | Columnas usadas |
|--------|------------------|
| **INSERT** (submit) | `issuer_id`, `currency`, `exchange_rate`, `payment_form`, `payment_method`, `cfdi_use`, `customer_rfc`, `customer_legal_name`, `customer_zip`, `customer_tax_system`, `customer_email` |
| **_safe_update** (submit) | `export_code`, `tipo_comprobante`, `series`, `folio_number`, `order_ref`, `issue_date`, `notes` |
| **UPDATE** (submit) | `facturapi_invoice_id`, `uuid`, `total` |
| **SELECT** (submit, api_pending_invoices) | `id`, `issuer_id`, `uuid`, `payment_method`, `issue_date`, `created_at`, `customer_legal_name`, `customer_rfc`, `total`; opcionalmente `status`, `cancelled` (vía PRAGMA table_info) |

**Columnas requeridas:**  
`id`, `issuer_id`, `currency`, `exchange_rate`, `payment_form`, `payment_method`, `cfdi_use`, `customer_rfc`, `customer_legal_name`, `customer_zip`, `customer_tax_system`, `customer_email`, `facturapi_invoice_id`, `uuid`, `total`, `created_at`, `export_code`, `tipo_comprobante`, `series`, `folio_number`, `order_ref`, `issue_date`, `notes`; opcionales: `status`, `cancelled`.

**Nota:** La tabla `invoices` **no se crea en app.py** (no hay `ensure_invoices_table`). Solo existe en `db_init.py`. Si la base se arma solo con `ensure_*` de app.py, `invoices` no existirá y fallarán submit y payment_relations.

---

### 1.10 `invoice_items`

| Origen | Columnas usadas |
|--------|------------------|
| **INSERT** (submit, dinámico por PRAGMA) | Base: `invoice_id`, `quantity`, `description`, `product_key`, `unit_price`, `iva_rate`; opcionales: `unit_key`, `discount` |
| **PRAGMA table_info** | Para construir INSERT dinámico |

**Columnas requeridas:** `id`, `invoice_id`, `quantity`, `description`, `product_key`, `unit_price`, `iva_rate`; opcionales: `unit_key`, `discount`, `created_at`.

**Nota:** Tampoco se crea en app.py; solo en `db_init.py`.

---

### 1.11 `payment_relations`

| Origen | Columnas usadas |
|--------|------------------|
| **INSERT** (submit, CFDI P) | `payment_invoice_id`, `related_invoice_id`, `related_uuid`, `amount` |
| **CREATE** (ensure_payment_tables) | FK a `invoices(id)` |

**Columnas requeridas:** `id`, `payment_invoice_id`, `related_invoice_id`, `related_uuid`, `amount`, `created_at`.

---

### 1.12 Tablas solo en esquema / migraciones (no usadas en app.py)

- **sat_credentials**, **sat_sync_state**, **sat_requests**, **sat_jobs**: creadas/usadas por otro proceso (p. ej. sat_sync), no por app.py en los fragmentos auditados.
- **frequent_customers** (db_init.py): no referida en app.py; la app usa `customer_profiles`.

---

### 1.13 Base de datos de catálogos (`catalogs.db`)

Consultas dinámicas por tabla. Columnas esperadas (por nombre genérico):

- **cfdi_40_formas_pago**, **cfdi_40_metodos_pago**, **cfdi_40_usos_cfdi**, **cfdi_40_regimenes_fiscales**, **cfdi_40_monedas**: clave (id/clave/key/c_Clave) y etiqueta (texto/descripcion/description/value/nombre).
- **cfdi_40_productos_servicios**, **cfdi_40_claves_unidades**: mismo par clave/etiqueta + búsqueda LIKE.

---

## 2. Índices que serían útiles

Basado en filtros y ordenaciones recurrentes en el código:

| Tabla | Índice sugerido | Uso principal |
|-------|------------------|---------------|
| **sat_cfdi** | `(issuer_id, direction, fecha_emision)` | Ya existe en schema_snapshot. Listados por mes. |
| **sat_cfdi** | `(issuer_id, direction, uuid)` | Ya como UNIQUE. Lookup por UUID. |
| **sat_cfdi** | `(issuer_id, direction, rfc_emisor)` | Reporte proveedores / api provider-invoices. |
| **sat_cfdi** | `(issuer_id, direction, tipo_comprobante)` | Filtro nómina (tipo N). |
| **quotations** | `(issuer_id)` | Ya existe. Listado por emisor. |
| **quotations** | `(public_token)` | Ya UNIQUE. Vista pública. |
| **quotation_items** | `(quotation_id)` | Ya existe. Items por cotización. |
| **customer_profiles** | `(issuer_id)` | Ya existe. |
| **customer_profiles** | `(alias)` | Ya existe. |
| **supplier_profiles** | `(issuer_id)` | Ya existe. |
| **issuer_products** | `(issuer_id)` | Ya existe. |
| **invoices** | `(issuer_id, uuid)` | Lookup en submit (CFDI P) y payment_relations. **Recomendado.** |
| **invoices** | `(issuer_id, payment_method)` | api_pending_invoices (PPD). |
| **invoices** | `(issuer_id, issue_date)` o `(issuer_id, created_at)` | Orden en pending. |
| **payment_relations** | `(payment_invoice_id)`, `(related_invoice_id)` | Ya existen en schema_snapshot. |

---

## 3. Inconsistencias detectadas

### 3.1 `issuers`: código pide `facturapi_org_id` pero el SELECT no lo incluye

- **Dónde:** `get_issuer_by_token()` devuelve `"facturapi_org_id": d.get("facturapi_org_id")`.
- **Problema:** El `SELECT` solo pide `i.id, i.rfc, i.razon_social, i.regimen_fiscal, i.active, t.token`. No se selecciona `facturapi_org_id`.
- **Consecuencia:** Siempre será `None` aunque la columna exista en la DB.
- **Esquemas:** `schema_snapshot.sql` para `issuers` tiene `id`, `rfc`, `razon_social`, `created_at`, `updated_at`, `active`, `regimen_fiscal` — **no tiene `facturapi_org_id`**. `db_init.py` sí define `facturapi_org_id TEXT NOT NULL` y usa `alias` en lugar de `razon_social`.
- **Resumen:** Hay dos “versiones” de esquema de issuers (snapshot vs db_init). Si la DB viene del snapshot, no existe `facturapi_org_id`; si viene de db_init, existe pero no se lee. En ambos casos el valor usado en timbrado/descarga será `None` salvo que se añada la columna al SELECT y se rellene en la DB.

### 3.2 Tablas `invoices` e `invoice_items` no creadas por app.py

- **Dónde:** `ensure_payment_tables()` crea `payment_relations` con FK a `invoices(id)`. Submit hace `INSERT INTO invoices` y `INSERT INTO invoice_items`. `api_pending_invoices` hace `SELECT ... FROM invoices`.
- **Problema:** Ningún `ensure_*` en app.py crea `invoices` ni `invoice_items`. Solo `db_init.py` las crea.
- **Consecuencia:** Si la base se crea solo ejecutando app.py (o un snapshot sin esas tablas), al facturar o usar CFDI P se producirán errores de “table invoices does not exist” y las FK de `payment_relations` fallarán al crearse.
- **Recomendación:** Añadir un `ensure_invoices_tables()` en app.py que cree `invoices` e `invoice_items` si no existen (o documentar que es obligatorio ejecutar db_init primero).

### 3.3 Esquema de `issuers`: dos definiciones distintas

- **db_init.py:** `id`, `alias`, `rfc`, `facturapi_org_id`, `whatsapp_e164`, `active` (sin `razon_social`, `regimen_fiscal`, `created_at`, `updated_at`).
- **schema_snapshot / migraciones:** `id`, `rfc`, `razon_social`, `created_at`, `updated_at`, `active`, `regimen_fiscal` (sin `alias`, `facturapi_org_id`).
- **Problema:** La app asume `razon_social` (SELECT y migraciones) y opcionalmente `regimen_fiscal` y `facturapi_org_id`. Según qué script se use para crear la DB, faltarán columnas o nombres distintos.
- **Recomendación:** Unificar en un único esquema de referencia (p. ej. `razon_social` + `regimen_fiscal` + `facturapi_org_id`) y migrar bases antiguas con ALTER si hace falta.

### 3.4 `customer_profiles`: zip/tax_system NOT NULL vs nullable

- **app.py ensure:** Crea `zip TEXT`, `tax_system TEXT` (sin NOT NULL).
- **schema_snapshot:** Lleva `zip TEXT NOT NULL`, `tax_system TEXT NOT NULL`.
- **Migración db_migrate_customer_profiles_nullable:** Hace `zip` y `tax_system` nullable.
- **Consecuencia:** Dependiendo del orden de ejecución (ensure vs snapshot vs migración), la definición puede ser distinta. Si se aplica la migración, es coherente con INSERT/UPDATE que no exigen siempre zip/tax_system.

### 3.5 `sat_schema.sql` desactualizado

- **Contenido:** Define `sat_cfdi` sin columnas como `serie`, `folio`, `forma_pago`, `metodo_pago`, `uso_cfdi`, `subtotal`, `descuento`, `impuestos`, `concepto`, `retenciones`, `xml_status`, etc.
- **Problema:** El código y `schema_snapshot.sql` sí usan esas columnas. Quien use solo `sat_schema.sql` tendría una tabla incompleta.
- **Recomendación:** Considerar sat_schema.sql obsoleto o actualizarlo al mismo esquema que schema_snapshot para sat_cfdi.

### 3.6 Columnas opcionales en `invoices` / `invoice_items`

- **invoices:** El código usa `_safe_update` para `export_code`, `tipo_comprobante`, `series`, `folio_number`, `order_ref`, `issue_date`, `notes`. Si la tabla se creó con db_init.py (solo columnas básicas), esas columnas no existen y _safe_update las ignora sin error. Comportamiento aceptable pero implícito.
- **invoice_items:** Se comprueba con PRAGMA si existen `unit_key` y `discount` antes de insertar. Si no existen, no se insertan. Coherente con esquemas mínimos.

### 3.7 FK de `payment_relations` a `invoices`

- **Problema:** `ensure_payment_tables()` crea `payment_relations` con FK a `invoices(id)`. Si `invoices` no existe aún, el CREATE TABLE falla (en SQLite con foreign_keys ON, depende del orden; si invoices no existe, la FK puede fallar al crearla).
- **Recomendación:** Crear primero `invoices` (e `invoice_items`) en app.py o garantizar que db_init (o equivalente) se ejecute antes que cualquier ensure que cree `payment_relations`.

---

## 4. Resumen ejecutivo

| # | Inconsistencia | Severidad |
|---|----------------|-----------|
| 1 | `facturapi_org_id` no se SELECT en get_issuer_by_token y en schema_snapshot no existe en issuers | Alta (timbrado/descarga fallan en producción) |
| 2 | `invoices` e `invoice_items` no creadas por app.py | Alta (submit y CFDI P fallan si no se corrió db_init) |
| 3 | Dos definiciones de `issuers` (db_init vs snapshot/migraciones) | Alta |
| 4 | `payment_relations` depende de `invoices` que app.py no crea | Alta |
| 5 | `customer_profiles` NOT NULL vs nullable según origen del esquema | Baja (mitigada por migración) |
| 6 | `sat_schema.sql` desactualizado respecto a sat_cfdi | Media (solo si se usa como fuente única) |
| 7 | Columnas extra de invoices/invoice_items opcionales y no documentadas en un solo sitio | Baja |

**Acciones recomendadas (solo diagnóstico; no implementado aquí):**

1. Incluir `facturapi_org_id` en el SELECT de `get_issuer_by_token()` y asegurar que la columna exista en `issuers` (migración si hace falta).
2. Crear `invoices` e `invoice_items` desde app.py (p. ej. `ensure_invoices_tables()`) o documentar y garantizar la ejecución de db_init antes de usar facturación.
3. Unificar el esquema de `issuers` (razon_social/alias, regimen_fiscal, facturapi_org_id) en un solo script de referencia y migrar bases existentes.
4. Añadir índice `(issuer_id, uuid)` en `invoices` para lookups y payment_relations.
5. Actualizar o deprecar `sat_schema.sql` para que coincida con el uso real de `sat_cfdi`.

---

*Documento generado por auditoría del repo. No se ha modificado código ni base de datos.*

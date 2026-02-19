# Auditoría: DB vieja vs código — columnas a asegurar en 003/004

Objetivo: lista concreta de **tabla.columna** que deben existir (o ser nullable) para compatibilidad con DBs viejas, **priorizando lo que causa crash**.

---

## Criterio de prioridad

- **Crash:** la columna aparece en un `SELECT`/`INSERT`/`UPDATE` explícito sin comprobar existencia → si falta, error SQL "no such column" o constraint.
- **Sin crash pero recomendable:** la columna se usa vía `_safe_update`, `PRAGMA table_info` o `_has_column` → si falta, no crashea pero se pierde dato o filtro.
- **Constraint:** columna `NOT NULL` cuando el código puede escribir `NULL`/vacío → error de integridad.

---

## 1. Prioridad CRASH (obligatorio en 003/004)

Si falta la columna, la app falla en ese flujo.

### sat_cfdi

El código hace `SELECT ... FROM sat_cfdi` listando estas columnas **sin** comprobar si existen (salvo `retenciones` y `concepto`, que ya se aseguran en startup con `ensure_retenciones_column` y `ensure_concepto_column`). En DBs creadas antes de tener todas las columnas (p. ej. solo con `sat_schema.sql` o migraciones antiguas), faltan varias.

| tabla.columna   | Uso en código | Nota |
|-----------------|----------------|------|
| **sat_cfdi.serie** | SELECT en portal issued/received/nomina y en _provider_report_rows | |
| **sat_cfdi.folio** | Idem | |
| **sat_cfdi.forma_pago** | Idem | |
| **sat_cfdi.metodo_pago** | Idem | |
| **sat_cfdi.uso_cfdi** | Idem | |
| **sat_cfdi.subtotal** | SELECT en listados y en _get_month_totals (SUM(subtotal)) | Si falta, crash en totales y listados. |
| **sat_cfdi.descuento** | SELECT en listados y reporte proveedor | |
| **sat_cfdi.impuestos** | SELECT en listados, reporte y _get_month_totals | Si falta, crash en totales. |
| **sat_cfdi.concepto** | SELECT en listados y api provider-invoices | Ya cubierto por `ensure_concepto_column` en app; migración lo refuerza. |
| **sat_cfdi.retenciones** | SELECT COALESCE(retenciones,0) en portal issued; _get_month_totals usa _has_column | En listado emitidas se usa en el SELECT directo → si falta, crash. Ya cubierto por `ensure_retenciones_column`; migración lo refuerza. |
| **sat_cfdi.tipo_comprobante** | WHERE en varios (nómina, recibidas, proveedores) y en SELECT | Si falta, puede fallar en WHERE/SELECT. |
| **sat_cfdi.xml_status** | SELECT en portal issued/received/nomina | |

**Resumen crash sat_cfdi:** Asegurar en 003/004 (por si la DB no pasó por ensure_* o es muy vieja):

- **sat_cfdi.serie**
- **sat_cfdi.folio**
- **sat_cfdi.forma_pago**
- **sat_cfdi.metodo_pago**
- **sat_cfdi.uso_cfdi**
- **sat_cfdi.subtotal**
- **sat_cfdi.descuento**
- **sat_cfdi.impuestos**
- **sat_cfdi.concepto**
- **sat_cfdi.retenciones**
- **sat_cfdi.tipo_comprobante**
- **sat_cfdi.xml_status**

Opcional (no usadas en app.py; sí en sat_sync u otros): xml_sha256, xml_downloaded_at, parsed_at, parse_version, lugar_expedicion, condiciones_pago — incluirlas si se quiere un solo esquema completo.

---

### invoices

| tabla.columna | Uso en código | Nota |
|---------------|----------------|------|
| **invoices.issue_date** | SELECT en `api_pending_invoices`: `SELECT id, uuid, total, customer_legal_name, customer_rfc, issue_date, created_at` y en ORDER BY `COALESCE(issue_date, created_at)` | Si la tabla viene de un init viejo sin esta columna → **crash** en ese endpoint. |

El resto (export_code, tipo_comprobante, series, folio_number, order_ref, notes, status, cancelled) se usa vía `_safe_update` o con `if "col" in cols` → no crashea si falta; solo no se guarda o no se filtra.

---

## 2. Prioridad ALTA (no crashea pero datos/filtros incompletos)

Recomendable en 003/004 para que la app se comporte igual que con baseline nuevo.

### invoices (columnas solo en _safe_update o WHERE opcional)

| tabla.columna | Motivo |
|---------------|--------|
| **invoices.export_code** | _safe_update; sin columna no se persiste. |
| **invoices.tipo_comprobante** | Idem. |
| **invoices.series** | Idem. |
| **invoices.folio_number** | Idem. |
| **invoices.order_ref** | Idem. |
| **invoices.issue_date** | Ya en crash; asegurar en migración. |
| **invoices.notes** | _safe_update. |
| **invoices.status** | Opcional en WHERE (api_pending_invoices); sin columna no se excluyen canceladas. |
| **invoices.cancelled** | Idem. |

### invoice_items (solo se insertan si existen en PRAGMA)

| tabla.columna | Motivo |
|---------------|--------|
| **invoice_items.unit_key** | Se inserta solo si `"unit_key" in cols`; sin columna no se guarda unidad. |
| **invoice_items.discount** | Se inserta solo si `"discount" in cols`; sin columna no se guarda descuento. |

---

## 3. Prioridad CONSTRAINT (customer_profiles)

Si `zip` o `tax_system` son `NOT NULL` y el código hace INSERT/UPDATE con valor vacío o NULL (p. ej. desde API o formulario opcional), SQLite puede devolver constraint error.

| tabla.columna | Motivo |
|---------------|--------|
| **customer_profiles.zip** | Asegurar que sea **nullable** (o que el código no envíe NULL si se mantiene NOT NULL). En DBs viejas creadas con schema que tenía zip NOT NULL, un INSERT con zip vacío/NULL falla. |
| **customer_profiles.tax_system** | Idem. |

Acción recomendada en 003/004: migración que deje **zip** y **tax_system** como nullable (en SQLite suele implicar recrear tabla, como en `db_migrate_customer_profiles_nullable.py`).

---

## 4. Lista final para migraciones 003 / 004

### Obligatorias (evitar crash)

- **sat_cfdi.serie**
- **sat_cfdi.folio**
- **sat_cfdi.forma_pago**
- **sat_cfdi.metodo_pago**
- **sat_cfdi.uso_cfdi**
- **sat_cfdi.subtotal**
- **sat_cfdi.descuento**
- **sat_cfdi.impuestos**
- **sat_cfdi.concepto**
- **sat_cfdi.retenciones**
- **sat_cfdi.tipo_comprobante**
- **sat_cfdi.xml_status**
- **invoices.issue_date**

### Recomendadas (comportamiento completo)

- **invoices.export_code**
- **invoices.tipo_comprobante**
- **invoices.series**
- **invoices.folio_number**
- **invoices.order_ref**
- **invoices.notes**
- **invoices.status**
- **invoices.cancelled**
- **invoice_items.unit_key**
- **invoice_items.discount**

### Constraint (evitar error de integridad)

- **customer_profiles.zip** → nullable
- **customer_profiles.tax_system** → nullable

---

## 5. Sugerencia de reparto 003 / 004

- **003:** sat_cfdi (todas las columnas de crash) + invoices.issue_date + customer_profiles zip/tax_system nullable.  
- **004:** resto de columnas de invoices + invoice_items (unit_key, discount) y, si se desea, columnas opcionales de sat_cfdi (xml_sha256, xml_downloaded_at, parsed_at, parse_version, etc.).

Así se prioriza primero lo que evita crash y errores de constraint en DBs viejas.

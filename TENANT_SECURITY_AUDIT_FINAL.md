# Auditoría final de seguridad multi-tenant (aislamiento por issuer_id)

**Objetivo:** Evitar que un cliente (issuer) vea o descargue datos de otro.  
**Alcance:** Todos los SELECT/UPDATE en rutas `/api/*` y `/portal/*` (y descargas asociadas).  
**Fecha:** Post-MEGA (auditoría automática). Sin cambios de UI.

---

## 1. Metodología

- Grep/scan de `SELECT` y `execute(` en `routers/api.py`, `routers/portal.py`, `routers/invoicing.py`, `routers/public.py`.
- Comprobación: en tablas con columna `issuer_id` (sat_cfdi, customer_profiles, issuer_products, quotations, quotation_items, supplier_profiles, invoices, sat_credentials, sat_jobs, sat_sync_state), toda consulta que devuelva datos por tenant debe incluir `issuer_id = ?` en el WHERE, con el valor proveniente de la sesión (`issuer["id"]` de `get_portal_issuer`), nunca de query/body.
- Descargas XML/PDF y páginas de detalle CFDI: confirmar que siempre se filtra por `issuer_id` antes de devolver el recurso.

---

## 2. Endpoints revisados

### 2.1 API (`/api/*`)

| Endpoint | Método | Tabla(s) | issuer_id en WHERE | Notas |
|----------|--------|----------|--------------------|--------|
| (get_portal_issuer) | — | — | — | Fuente: sesión o token; `issuer["id"]` usado en todo lo siguiente. |
| `/api/onboarding-status` | GET | issuers, sat_credentials, customer_profiles, issuer_products | Sí (issuer_id de sesión) | OK. |
| `/api/customers` | GET | customer_profiles | Sí | OK. |
| `/api/customers/create` | POST | INSERT customer_profiles | issuer_id del payload = sesión | OK. |
| `/api/customers/delete` | POST | DELETE customer_profiles | Sí (issuer_id, rfc) | OK. |
| `/api/products` | GET | issuer_products | Sí | OK. |
| `/api/products/create` | POST | INSERT issuer_products | issuer_id sesión | OK. |
| `/api/quotations` | GET | quotations | Sí | OK. |
| `/api/quotations/create` | POST | quotations, quotation_items | issuer_id sesión | OK. |
| `/api/quotations/{qid}` | GET | quotations, quotation_items | Sí (issuer_id, id) | OK. |
| `/api/quotations/update-status` | POST | quotations | Sí (issuer_id, id) | OK. |
| `/api/quotations/respond` | POST | quotations (SELECT/UPDATE) | No (por diseño) | Busca por `public_token`; flujo público; no hay enumeración de tenants. OK. |
| `/api/provider-invoices`, `/api/providers/invoices` | GET | sat_cfdi | Sí (issuer_id, rfc_emisor) | OK. |
| `/api/providers`, `/api/providers/create` | GET/POST | supplier_profiles, sat_cfdi | Sí | OK. |
| `/api/provider-invoices/report` | GET | supplier_profiles, sat_cfdi | Sí | OK. |
| `/api/invoices/issued` | GET | sat_cfdi | Sí (where_parts + params) | OK. |
| `/api/invoices/received` | GET | sat_cfdi | Sí | OK. |
| `/api/invoices/pending` | GET | invoices | Sí | OK. |

### 2.2 Portal HTML y descargas (`/portal/*`)

| Endpoint | Método | Tabla(s) | issuer_id en WHERE | Notas |
|----------|--------|----------|--------------------|--------|
| `/portal/home` | GET | sat_cfdi, sat_credentials, customer_profiles, issuer_products | Sí | OK. |
| `/portal/quotations/{qid}/pdf` | GET | quotations | Sí (issuer_id, id); luego servicio por public_token de esa fila | OK. |
| `/portal/quotations/{qid}` | GET | quotations | Sí (issuer_id, id) | OK. |
| `/portal/invoices/issued`, `/portal/invoices/received` | GET | sat_cfdi (listados y totales) | Sí | OK. |
| `/portal/sat/xml/{uuid}` | GET | sat_cfdi | Sí (issuer_id, uuid); path con _safe_abs_path | OK. |
| `/portal/sat/pdf/{uuid}` | GET | sat_cfdi | Sí (issuer_id, uuid); path con _safe_abs_path | OK. |
| `/portal/cfdi/issued/{uuid}`, `/portal/cfdi/received/{uuid}` | GET | sat_cfdi vía _get_cfdi_by_uuid(issuer_id, uuid, direction) | Sí | OK. |
| `/portal/summary` | GET | sat_cfdi (totales por mes) | Sí | OK. |
| `/portal/config/sat`, `/portal/sat/sync`, `/portal/sat/status` | GET/POST | sat_credentials, sat_jobs, sat_sync_state | Sí | OK. |
| `/portal/sat/config/save`, `/portal/sat/validate` | POST | sat_credentials | Sí | OK. |
| `/portal/clients`, `/portal/providers`, `/portal/products`, etc. | GET | Solo render HTML; datos vía API | N/A | OK. |

### 2.3 Invoicing (submit y descargas)

| Endpoint | Método | Tabla(s) | issuer_id en WHERE | Notas |
|----------|--------|----------|--------------------|--------|
| `/submit` | POST | invoices, invoice_items, customer_profiles, payment_relations | issuer_id en INSERTs; SELECT invoices para related: issuer_id + uuid | OK. |
| `/download/xml/{uuid}` | GET | sat_cfdi | Sí (issuer_id, uuid); _safe_abs_path | OK. |
| `/download/pdf/{uuid}` | GET | sat_cfdi | Sí (issuer_id, uuid); _safe_abs_path | OK. |
| `/download/{fmt}/{invoice_id}` | GET | Ninguna (solo Facturapi) | No se valida en BD | Ver hallazgo MEDIA §3.1. |

### 2.4 Rutas públicas (sin sesión portal)

| Endpoint | Método | Tabla(s) | issuer_id en WHERE | Notas |
|----------|--------|----------|--------------------|--------|
| `/q/{public_token}`, `/q/{public_token}/pdf` | GET | quotations (vía get_quotation_by_public_token) | No | Acceso por token no predecible; no enumeración de tenants. OK. |
| `/public/cotizacion/{public_token}`, `/public/cotizacion/respond` | GET/POST | quotations (SELECT por public_token; UPDATE por id de esa fila) | No en SELECT | Idem; qid obtenido de la fila con ese token. OK. |

### 2.5 Admin y Billing

| Área | Notas |
|------|--------|
| `/admin/*` | Intencionalmente global; protegido por require_admin. No es flujo tenant. |
| `/billing/checkout`, `/webhooks/stripe` | Billing por user_id; no expone datos entre issuers. |

---

## 3. Hallazgos (prioridad: evitar que un cliente vea datos de otro)

### 3.1 MEDIA – Descarga por `invoice_id` sin validación en BD (Facturapi)

- **Endpoint:** `GET /download/{fmt}/{invoice_id}` (invoicing router).
- **Comportamiento:** Se usa `issuer["facturapi_org_id"]` de la sesión y `invoice_id` de la URL para llamar a `download_invoice(org_id, invoice_id, fmt)`. No se consulta la tabla `invoices` para comprobar que ese `invoice_id` (o el UUID/facturapi_invoice_id asociado) pertenezca al `issuer_id` de la sesión.
- **Riesgo:** Si la API de Facturapi asociara por error un recurso a otro org, o si hubiera un bug de autorización del lado de Facturapi, un usuario podría intentar IDs ajenos y recibir contenido de otra organización. La defensa actual depende 100% de Facturapi.
- **Fix sugerido (no implementado):** Antes de llamar a `download_invoice(issuer["facturapi_org_id"], invoice_id, fmt)`, validar en nuestra BD que exista una fila en `invoices` con `issuer_id = issuer["id"]` y con `facturapi_invoice_id = invoice_id` (o el campo que almacene el ID de Facturapi). Si no existe, devolver 404. Ejemplo:

```python
# Antes de download_invoice(...):
row = conn.execute(
    "SELECT id FROM invoices WHERE issuer_id = ? AND facturapi_invoice_id = ? LIMIT 1",
    (issuer["id"], invoice_id),
).fetchone()
if not row:
    raise HTTPException(status_code=404, detail="Factura no encontrada para este emisor")
# Luego llamar a download_invoice(issuer["facturapi_org_id"], invoice_id, fmt)
```

(Adaptar nombre de columna si en el esquema es `facturapi_invoice_id` o similar.)

---

### 3.2 BAJA – Autenticación por `?token=` (legacy)

- **Comportamiento:** En `deps.py`, si la petición trae `?token=XXX`, se resuelve el issuer con `issuers.get_issuer_by_token(XXX)` y se considera autenticado como ese issuer.
- **Riesgo:** Quien conozca o adivine un token válido puede actuar como ese issuer. No es fuga entre tenants por consultas sin filtro; es diseño legacy (links por token).
- **Fix sugerido (opcional):** Documentar que los tokens deben tratarse como secretos; en entornos estrictos, deshabilitar auth por token y exigir solo sesión por cookie.

---

### 3.3 BAJA – Cotización pública expone issuer_name / issuer_rfc

- **Comportamiento:** `get_quotation_by_public_token` devuelve `issuer_id`, `issuer_name`, `issuer_rfc` para la cotización. Las plantillas públicas muestran nombre/RFC del emisor de esa cotización.
- **Riesgo:** Quien tenga el link ve que la cotización es de cierto emisor. No hay fuga de datos de *otros* tenants; es el emisor de esa cotización.
- **Fix sugerido (opcional):** Si en el futuro se expone una API pública de cotización en JSON, no incluir `issuer_id` en la respuesta; mantener solo nombre/RFC para mostrar.

---

## 4. Resumen

| Severidad | Cantidad | Descripción |
|-----------|----------|-------------|
| Alta | 0 | Ninguna fuga directa por SELECT/descarga sin issuer_id en rutas tenant. |
| Media | 1 | Descarga Facturapi por `invoice_id` sin validación en BD (§3.1). |
| Baja | 2 | Auth por token legacy (§3.2); datos de emisor en cotización pública (§3.3). |

**Conclusión:** En todas las rutas `/api/*` y `/portal/*` que devuelven datos por tenant, los SELECT aplican `issuer_id` en el WHERE cuando la tabla es multi-tenant. Las descargas de XML/PDF desde `sat_cfdi` (portal e invoicing) y el detalle CFDI (issued/received) están correctamente acotadas por `issuer_id`. El único punto de atención media es la descarga vía Facturapi por `invoice_id`, que no valida en nuestra BD la pertenencia al issuer; el fix sugerido es añadir esa validación antes de llamar a Facturapi.

# Auditoría de seguridad multi-tenant (aislamiento por issuer_id)

**Objetivo:** Garantizar que un cliente (issuer) no pueda acceder a datos de otro. Sin cambios de UI/CSS.

**Alcance:** Endpoints que leen o descargan datos: facturas (invoices, sat_cfdi), descargas XML/PDF, detalle CFDI, proveedores, cotizaciones, clientes, productos.

---

## 1. Fuente de verdad del tenant: `get_portal_issuer`

- **Origen:** Cookie de sesión (`portal_session`) o, en modo legacy, `?token=` en la URL.
- **Comportamiento:** `routers/deps.py` resuelve `issuer_id` desde la sesión verificada (o token válido) y devuelve el diccionario `issuer` con `id`, `rfc`, `alias`, etc.
- **Uso correcto:** Todo endpoint que devuelva datos por tenant debe usar `issuer: dict = Depends(get_portal_issuer)` y filtrar **siempre** con `issuer["id"]` (nunca con `issuer_id` o `org_id` llegados por query/body sin validar).

---

## 2. Endpoints auditados

### 2.1 Portal (HTML y descargas)

| Endpoint | Método | Filtro por issuer | Notas |
|----------|--------|-------------------|--------|
| `/portal/home` | GET | Sí (`issuer_id` de sesión) | Queries a sat_cfdi, customer_profiles, issuer_products, sat_credentials con `issuer_id = ?`. |
| `/portal/quotations`, `/portal/quotations/{qid}`, `/portal/quotations/{qid}/pdf` | GET | Sí | `WHERE issuer_id = ? AND id = ?` en quotations; PDF vía servicio que usa quote ya validado. |
| `/portal/invoices`, `/portal/invoices/issued`, `/portal/invoices/received`, `/portal/invoices/nomina` | GET | Sí | Todas las consultas a `sat_cfdi` incluyen `issuer_id = ?`. |
| `/portal/sat/xml/{uuid}` | GET | Sí | `SELECT ... FROM sat_cfdi WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)`. Ruta de archivo con `_safe_abs_path`. |
| `/portal/sat/pdf/{uuid}` | GET | Sí | Mismo patrón que XML; path con `_safe_abs_path`. |
| `/portal/cfdi/issued/{uuid}`, `/portal/cfdi/received/{uuid}` | GET | Sí | `_get_cfdi_by_uuid(issuer["id"], uuid, direction)` → WHERE issuer_id y uuid. |
| `/portal/clients`, `/portal/providers`, `/portal/products` | GET | Sí | Páginas que cargan datos vía API; la API filtra por issuer (ver abajo). |
| `/portal/summary`, `/portal/plan`, `/portal/config/sat`, `/portal/sat/sync`, `/portal/sat/status` | GET/POST | Sí | Usan `issuer["id"]` en consultas a sat_cfdi, sat_jobs, sat_credentials, etc. |

### 2.2 Invoicing (submit y descargas)

| Endpoint | Método | Filtro por issuer | Notas |
|----------|--------|-------------------|--------|
| `/submit` | POST | Sí | `issuer["id"]` en INSERT invoices, customer_profiles y en llamada a Facturapi (`issuer["facturapi_org_id"]`). Relación de pagos: `WHERE issuer_id = ? AND uuid = ?`. |
| `/download/xml/{uuid}` | GET | Sí | `WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)`; path con `_safe_abs_path`. |
| `/download/pdf/{uuid}` | GET | Sí | Mismo patrón que XML. |
| `/download/{fmt}/{invoice_id}` | GET | Parcial | Usa `issuer["facturapi_org_id"]` y `invoice_id` de la URL. La petición a Facturapi va con el org de la sesión; **no se valida en nuestra BD** que `invoice_id` pertenezca a ese issuer (véase riesgo en §4). |

### 2.3 API JSON (`/api/*`)

| Endpoint | Método | Filtro por issuer | Notas |
|----------|--------|-------------------|--------|
| `/api/customers`, `/api/customers/create`, `/api/customers/delete` | GET/POST | Sí | `WHERE issuer_id = ?` o `INSERT ... issuer_id = ?`. |
| `/api/products`, `/api/products/create` | GET/POST | Sí | `issuer_id` de sesión. |
| `/api/quotations`, `/api/quotations/create`, `/api/quotations/{qid}`, `/api/quotations/update-status` | GET/POST | Sí | Todas las consultas/updates con `issuer_id = ?` e `id = ?` (qid). |
| `/api/quotations/respond` | POST | No (por diseño) | Busca por `public_token` únicamente. Cualquiera con el link puede aceptar/rechazar; no hay filtro por issuer porque es flujo público. Aceptable. |
| `/api/provider-invoices`, `/api/providers/invoices`, `/api/provider-invoices/report` | GET | Sí | `_provider_report_rows(issuer["id"], rfc_norm)` y WHERE `issuer_id = ? AND direction = 'received'`. |
| `/api/providers`, `/api/providers/create` | GET/POST | Sí | `supplier_profiles WHERE issuer_id = ?`. |
| `/api/invoices/issued`, `/api/invoices/received` | GET | Sí | `where_parts` incluyen `issuer_id = ?` y params con `issuer_id`. |
| `/api/invoices/pending` | GET | Sí | `WHERE issuer_id = ?` en tabla `invoices`. |

### 2.4 Rutas públicas (sin sesión)

| Endpoint | Método | Filtro por issuer | Notas |
|----------|--------|-------------------|--------|
| `/q/{public_token}`, `/q/{public_token}/pdf`, `/public/cotizacion/{public_token}`, `/public/cotizacion/respond` | GET/POST | N/A (por token público) | Acceso por `public_token`; la cotización pertenece a un solo issuer. No hay selección de tenant por sesión; quien tiene el link ve solo esa cotización. No constituye fuga entre tenants. |

### 2.5 Admin

| Endpoint | Método | Filtro por issuer | Notas |
|----------|--------|-------------------|--------|
| `/admin/*` | GET/POST | Intencionalmente global | Protegido por `require_admin` / `require_admin_or_owner`. Lista usuarios, issuers, memberships y audit; impersonación por `issuer_id`/RFC. Debe seguir restringido a roles admin. |

---

## 3. Path traversal (rutas de archivo)

- **Rutas que sirven archivos:** Solo aquellas que leen `xml_path` desde la BD tras filtrar por `issuer_id` y `uuid`.
- **Función usada:** `_safe_abs_path(path_like)` (en `routers/portal.py` y `routers/invoicing.py`):
  - Exige que la ruta resuelta esté **dentro de `BASE_DIR`** (`startswith(base + os.sep)`).
  - Ningún endpoint usa un path llegado directamente por query, body o path parameter sin haberlo obtenido de una fila ya filtrada por `issuer_id`.
- **Conclusión:** No se detectó path traversal; el path siempre viene de la BD tras validar tenant y UUID.

---

## 4. Riesgos encontrados

### 4.1 Media – Descarga Facturapi por `invoice_id` (URL)

- **Endpoint:** `GET /download/{fmt}/{invoice_id}` (router de invoicing).
- **Comportamiento:** Se usa `issuer["facturapi_org_id"]` de la sesión y `invoice_id` de la URL para llamar a `download_invoice(org_id, invoice_id, fmt)`.
- **Riesgo:** Si la API de Facturapi no asegura que `invoice_id` pertenezca a `org_id`, un atacante podría probar IDs ajenos y descargar facturas de otra organización.
- **Mitigación actual:** La petición se hace con el header de organización de la sesión; la seguridad depende de Facturapi.
- **Fix sugerido (sin implementar):** Validar en nuestra BD que el `invoice_id` (o el UUID asociado) corresponda al issuer de la sesión antes de llamar a Facturapi. Ejemplo de query segura:

```python
# Antes de download_invoice(issuer["facturapi_org_id"], invoice_id, fmt):
row = conn.execute(
    "SELECT id FROM invoices WHERE issuer_id = ? AND (facturapi_invoice_id = ? OR uuid = ?) LIMIT 1",
    (issuer["id"], invoice_id, invoice_id),
).fetchone()
if not row:
    raise HTTPException(status_code=404, detail="Factura no encontrada para este emisor")
# Luego llamar a download_invoice
```

---

### 4.2 Baja – Acceso por `?token=` (legacy)

- **Comportamiento:** En `deps.py`, si la petición trae `?token=XXX`, se resuelve el issuer con `issuers.get_issuer_by_token(XXX)` y se considera autenticado como ese issuer.
- **Riesgo:** Quien conozca o adivine un token válido puede actuar como ese issuer. Es diseño legacy (links por token).
- **Fix sugerido (opcional):** Documentar que los tokens deben tratarse como secretos; en entornos estrictos, deshabilitar auth por token y exigir solo sesión por cookie.

---

### 4.3 Baja – Datos de emisor en cotización pública

- **Comportamiento:** `get_quotation_by_public_token` devuelve `issuer_id`, `issuer_name`, `issuer_rfc` para la cotización. Las plantillas públicas pueden mostrar nombre/RFC del emisor.
- **Riesgo:** Quien tenga el link ve que la cotización es de cierto emisor (nombre/RFC). No hay fuga de datos de *otros* tenants; es el emisor de esa cotización.
- **Fix sugerido (opcional):** Si en el futuro se expone una API pública de cotización, evitar incluir `issuer_id` en el JSON; mantener solo nombre/RFC para mostrar.

---

## 5. Resumen de buenas prácticas observadas

- Uso consistente de `Depends(get_portal_issuer)` en rutas que deben estar acotadas al tenant.
- Consultas parametrizadas con `issuer_id` de sesión (nunca `issuer_id` tomado de query/body sin validar).
- Rutas de archivo que usan siempre `_safe_abs_path` sobre un path obtenido de la BD tras filtrar por `issuer_id` y UUID.
- Endpoints públicos (cotización por link) acotados a un recurso identificado por token no predecible; no permiten enumerar otros tenants.

---

## 6. Checklist de verificación para nuevos endpoints

- [ ] ¿El endpoint devuelve o modifica datos por tenant (issuer)?
- [ ] Si sí: ¿usa `issuer = Depends(get_portal_issuer)` (o equivalente con sesión)?
- [ ] ¿Todas las consultas/INSERT/UPDATE incluyen `issuer_id = ?` con el valor de `issuer["id"]`?
- [ ] ¿Se usa algún identificador de la petición (path, query, body) como `issuer_id` u `org_id` sin validar contra la sesión? → Debe corregirse.
- [ ] Si se sirve un archivo: ¿el path viene de la BD tras filtrar por tenant (+ UUID/u otro id)? ¿Se pasa por `_safe_abs_path` (o equivalente bajo BASE_DIR)?

---

**Fecha de auditoría:** 2025-02  
**Alcance:** Routers portal, invoicing, api, public, admin; servicios de cotizaciones; facturapi_client. Sin cambios de UI/CSS aplicados.

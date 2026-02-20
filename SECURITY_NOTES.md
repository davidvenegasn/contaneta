# Notas de seguridad

Auditoría de aislamiento por `issuer_id`, cookies, rate limiting y variables críticas para producción.

---

## 1. Aislamiento por issuer_id

Todas las rutas que devuelven o modifican datos de negocio deben filtrar por el `issuer_id` de la sesión (o token). El `issuer_id` se obtiene de la dependencia `get_portal_issuer` (cookie o `?token=`) y **nunca** del cuerpo o query del request sin validar pertenencia.

### 1.1 Portal (routers/portal.py)

| Ruta / flujo | Validación issuer_id |
|--------------|----------------------|
| `GET /portal/home` | Totales y listados usan `issuer["id"]` en `_get_month_totals(issuer_id, ...)` y en queries con `WHERE issuer_id = ?`. |
| `GET /portal/invoices/issued` | `issuer_id = issuer["id"]` en SELECT a `sat_cfdi` con `WHERE issuer_id = ? AND direction = 'issued'`. |
| `GET /portal/invoices/received` | Igual con `direction = 'received'`. |
| `GET /portal/sat/xml/{uuid}` | `SELECT ... FROM sat_cfdi WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)`. Ruta del archivo resuelta con `_safe_abs_path` (bajo BASE_DIR). |
| `GET /portal/sat/pdf/{uuid}` | Misma cláusula `issuer_id = ?` y `_safe_abs_path`. |
| `GET /portal/cfdi/issued/{uuid}` | `_get_cfdi_by_uuid(issuer["id"], uuid, "issued")` — SELECT con `WHERE issuer_id = ? AND ...`. |
| `GET /portal/cfdi/received/{uuid}` | Igual con `"received"`. |
| `GET /portal/quotations/{qid}/pdf` | `SELECT ... FROM quotations WHERE issuer_id = ? AND id = ?`. |
| Detalle cotización, create desde cotización | Queries a `quotations` y `quotation_items` con `issuer_id = issuer["id"]`. |
| Resumen, nómina, proveedores | Todas las queries usan `issuer_id = issuer["id"]` o `_get_month_totals(issuer_id, ...)`. |

### 1.2 API (routers/api.py)

| Endpoint / flujo | Validación issuer_id |
|------------------|----------------------|
| Clientes (`customer_profiles`) | `WHERE issuer_id = ?` / `ON CONFLICT(issuer_id, rfc)` con `issuer["id"]`. |
| Productos (`issuer_products`) | `WHERE issuer_id = ?` e INSERT con `issuer["id"]`. |
| Cotizaciones (list, get, create, update status) | `q.issuer_id = ?` o `WHERE issuer_id = ? AND id = ?`. |
| Reporte por proveedor | `_provider_report_rows(issuer["id"], rfc_norm)` y queries con `WHERE issuer_id = ?`. |
| Facturas recibidas (list) | `WHERE issuer_id = ? AND direction = 'received'`. |

### 1.3 Descargas (routers/invoicing.py)

| Ruta | Validación issuer_id |
|------|----------------------|
| `GET /download/xml/{uuid}` | `SELECT ... FROM sat_cfdi WHERE issuer_id = ? AND uuid = ?`; entrega vía `_safe_abs_path`. |
| `GET /download/pdf/{uuid}` | Misma cláusula y `_safe_abs_path`. |

### 1.4 Rutas públicas (sin issuer de sesión)

- `/q/{public_token}` y `/q/{public_token}/pdf`: acceso por `public_token` único; no filtran por sesión. El token identifica una sola cotización; no exponen datos de otros issuers.
- Login con `?token=`: el token es de `issuer_tokens`; valida `issuer_id` del token y establece sesión para ese issuer.

### 1.5 Path traversal

- Todas las rutas que sirven archivos (XML/PDF) usan `_safe_abs_path(path)`: la ruta se resuelve bajo `BASE_DIR` y se rechaza si sale del árbol. Evita `../` y acceso a archivos ajenos al proyecto.

---

## 2. Rate limiting (login)

- **Implementado:** En `routers/auth.py`, antes de validar credenciales en `POST /login`:
  - Contador por IP (memoria): ventana de **60 segundos**, máximo **5 intentos** por IP.
  - Si se supera: `sleep(2)` y redirección a `/login?error=invalid` (mensaje genérico).
- **Objetivo:** Reducir brute force por IP; no revelar si el email existe o no (mismo mensaje genérico).
- **Limitación:** Contador en memoria; no persiste entre reinicios y no se comparte entre múltiples workers. Para producción con varios workers, considerar Redis o similar (fuera de alcance actual).

---

## 3. Cookies de sesión

- **Nombre:** `portal_session` (configurable vía `SESSION_COOKIE_NAME`).
- **Parámetros** (en `services/session.py`, `session_cookie_params()`):
  - **HttpOnly:** `True` — el cookie no es accesible desde JavaScript (mitiga XSS).
  - **SameSite:** `lax` — se envía en navegaciones top-level (ej. clic desde otro sitio); reduce riesgo CSRF en flujos GET.
  - **Secure:** Valor de `COOKIE_SECURE` (env). Si `True`, el cookie solo se envía por HTTPS.
  - **max_age:** `SESSION_TTL_DAYS * 86400` (ej. 7 días).
  - **path:** `/`.

### COOKIE_SECURE en producción

- **Variable:** `COOKIE_SECURE` (env). Valores: `0` (false) o `1` (true).
- **Producción con HTTPS:** Debe ser `COOKIE_SECURE=1` para que el navegador solo envíe la cookie por HTTPS.
- **Desarrollo sin HTTPS:** `COOKIE_SECURE=0`. No usar `1` en HTTP o la cookie no se enviará y parecerá que no hay sesión.
- **Override por request:** Si el request llega con `X-Forwarded-Proto: https` o `request.url.scheme == "https"`, `session_cookie_params()` fuerza `secure=True` aunque `COOKIE_SECURE` sea 0 (útil detrás de un proxy HTTPS).

---

## 4. Variables de entorno críticas

Resumen; ver `env.example` para lista completa y valores por defecto seguros.

- **DEV_MODE:** En producción debe ser `0`. Con `1`, se permite acceso al portal sin sesión usando `DEV_TOKEN`.
- **SESSION_SECRET:** Secreto para firmar la cookie; debe ser aleatorio y fuerte (ej. 32+ bytes hex). Si no se define, se genera uno al arrancar (no recomendado en producción multi-worker).
- **COOKIE_SECURE:** `1` en producción con HTTPS.
- **APP_DB_PATH:** Ruta absoluta a `invoicing.db` en producción.
- **FACTURAPI_SECRET_KEY:** Requerido para timbrado real (facturapi_client).

---

*Documento de apoyo a LAUNCH_CHECKLIST.md y QA_STEPS.md.*

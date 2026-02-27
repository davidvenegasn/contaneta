# Endurecimiento de seguridad del MVP

Cambios mínimos de alta ganancia, sin reescribir flujos. Cada cambio está documentado con motivo.

---

## 1. Riesgos detectados (prioridad)

### Alta

| Riesgo | Mitigación aplicada |
|--------|----------------------|
| Cookie de sesión enviada por HTTP en prod | `ENV=prod` → `COOKIE_SECURE=1` por defecto; documentar `SESSION_SECRET` obligatorio en prod. |
| Descargas XML/PDF sin registro de quién/cuándo | Auditoría en `/download/xml/{uuid}` y `/download/pdf/{uuid}` (issuer_id ya validado; se añade `audit.log`). |
| Path traversal en rutas de descarga | `_safe_abs_path` ya existía; se añade `normpath` y validación de `path_like` vacío/trim. |

### Media

| Riesgo | Mitigación aplicada |
|--------|----------------------|
| Cabeceras de seguridad ausentes | Middleware que añade X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy; CSP en prod. |
| Impersonation sin trazabilidad clara | Acciones de auditoría renombradas a `impersonate_start` / `impersonate_stop` con `target_issuer_id` y detalles (restored_issuer_id). |
| SESSION_SECRET por proceso en prod | Documentación: en prod debe definirse y rotarse si hay compromiso. |

### Baja

| Riesgo | Estado |
|--------|--------|
| Rate limiting solo en memoria | Ya existía para login/registro/forgot; documentado. Multi-worker requeriría Redis (fuera de alcance). |
| CSP demasiado estricta rompe UI | CSP solo activa con `ENV=prod`; incluye `unsafe-inline` donde se necesita (scripts/estilos). |

---

## 2. Cambios realizados (por archivo)

### config.py

- **ENV / IS_PROD:** `ENV=prod` → `IS_PROD=True`; en prod `COOKIE_SECURE` por defecto `1`.
- **Motivo:** Asegurar Secure en producción sin depender de que se setee `COOKIE_SECURE` a mano.

### services/session.py

- **Comentario:** Aclarar que HttpOnly y SameSite=Lax son siempre; Secure según config o request (HTTPS).
- **Motivo:** Dejar explícito el modelo de cookie para futuras revisiones.

### app.py

- **security_headers_middleware:** Añade a todas las respuestas:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: SAMEORIGIN`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), microphone=(), camera=()`
  - Con `ENV=prod`: `Content-Security-Policy` (default-src 'self'; script/style/font/frame/connect permiten mismo origen, Stripe, Google Fonts; frame-ancestors 'self').
- **Motivo:** Reducir XSS, clickjacking y fugas de referrer; CSP en prod refuerza frame-ancestors.

### routers/invoicing.py

- **get_portal_issuer:** Sin cambio; ya asegura `issuer_id` por sesión/token.
- **_safe_abs_path:** Rechazo explícito de `path_like` vacío o solo espacios; uso de `os.path.normpath` antes de comprobar prefijo con `BASE_DIR`.
- **download_xml / download_pdf:**  
  - UUID normalizado (strip, primer token); query con `LOWER(TRIM(uuid))` para consistencia.  
  - `audit.log(action="download_xml"|"download_pdf", user_id=request.state.user_id, issuer_id=issuer["id"], details=uuid, request=request, entity="cfdi", entity_id=uuid)`.
- **Motivo:** Trazabilidad de descargas (quién, qué UUID, cuándo, IP/UA vía audit); refuerzo anti-traversal y consistencia de UUID.

### routers/admin.py

- **Impersonation:**  
  - Inicio: `action="impersonate_start"`, `details` con `target_issuer_id` y RFC.  
  - Fin: `action="impersonate_stop"`, `details` con `restored_issuer_id`.
- **Motivo:** Auditoría clara de inicio/fin de impersonation; `audit_log.created_at` da el timestamp.

### SECURITY_NOTES.md

- Cookies: descripción de ENV/COOKIE_SECURE y default en prod.
- Variables críticas: SESSION_SECRET obligatorio en prod y rotación; ENV=prod.
- Descargas: tabla actualizada con auditoría en `/download/xml` y `/download/pdf`.

---

## 3. Rate limiting (ya existente)

- **Login:** `routers/auth.py` — 5 intentos / 60 s por IP; mensaje genérico al exceder.
- **Registro:** 3 intentos / 60 s por IP.
- **Forgot password:** 3 intentos / 60 s por IP.
- **Limitación:** En memoria; no persiste entre reinicios ni se comparte entre workers. Para prod multi-worker, valorar Redis (fuera de este PR).

---

## 4. Descargas XML/PDF — verificación y auditoría

- **Autorización:** Siempre por `issuer_id` de la sesión (dependencia `get_portal_issuer`). Query: `WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)`.
- **Path:** `_safe_abs_path` resuelve bajo `BASE_DIR`, rechaza rutas fuera del árbol, normaliza con `normpath`.
- **Auditoría:** Cada descarga (portal e invoicing) registra en `audit_log`: action, user_id, issuer_id, entity_id (uuid), IP y user-agent vía `request`.

---

## 5. PR plan — cambios mínimos y pruebas rápidas

| Paso | Acción | Prueba rápida |
|------|--------|----------------|
| 1 | Merge config (ENV, COOKIE_SECURE default) | `ENV=prod` → verificar que cookie tenga Secure en respuesta (o en navegador). |
| 2 | Merge security headers middleware | `curl -I` a cualquier ruta; comprobar X-Content-Type-Options, X-Frame-Options, Referrer-Policy. |
| 3 | Merge invoicing: _safe_abs_path + audit en download | Descargar XML/PDF con sesión; revisar `audit_log` (action download_xml/download_pdf, issuer_id, entity_id). |
| 4 | Merge admin: impersonate_start/impersonate_stop | Como admin: impersonate → stop; revisar `audit_log` por action y target_issuer_id/restored_issuer_id. |
| 5 | Actualizar SECURITY_NOTES y docs | Revisión de documentación y checklist de despliegue. |

**Pruebas sugeridas (manual o script):**

- Sin `ENV=prod`: cookie sin Secure (en HTTP). Con `ENV=prod`: cookie Secure (o detrás de HTTPS).
- Una petición a `/portal/home` o `/login`: cabeceras de seguridad presentes.
- Una descarga de XML/PDF (portal o invoicing): una fila en `audit_log` con action, issuer_id, entity_id.
- Impersonation start/stop: dos filas en `audit_log` con `impersonate_start` e `impersonate_stop`.

---

*Documento de apoyo al checklist de endurecimiento del MVP.*

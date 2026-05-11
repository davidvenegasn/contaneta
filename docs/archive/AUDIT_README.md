# Auditoría completa del proyecto — ContaNeta MVP

**Rol:** Arquitecto de software / Tech Lead  
**Alcance:** FastAPI, SQLite, portal `/portal/*`, API `/api/*`, admin, auth, servicios SAT/PDF/bancos, front Jinja2 + CSS/JS.  
**Importante:** Este documento es solo auditoría y plan; no incluye cambios de código.

---

## Resumen ejecutivo

| Área            | Estado     | Riesgo principal |
|-----------------|------------|------------------|
| **Estabilidad** | A mejorar  | Errores 500 devueltos como 400; `subprocess.run` sin timeout; excepciones crudas en respuestas |
| **Funcionamiento** | Aceptable | Fetch sin timeout en parte del portal; sesión expirada en formularios largos; sync SAT sin mensaje “puede tardar” |
| **Base de datos** | Correcto con riesgos | Migraciones 019 duplicadas; schema vs código alineado; WAL y busy_timeout OK |
| **UX/UI**       | A mejorar  | Empty/load-error no unificados en todas las pantallas; modales sin focus trap; móvil con tablas pesadas |
| **Seguridad básica** | Aceptable | SESSION_SECRET obligatorio en prod; CSRF en formularios; rutas admin protegidas por rol |
| **Mantenibilidad** | A mejorar | Helpers de fetch/format duplicados entre templates; estilos inline dispersos; lógica repetida en listados |
| **Performance básica** | A mejorar | Listados con LIMIT 300/500 sin paginación server-side; queries N+1 posibles; respuestas grandes |

**Conclusión:** El proyecto es desplegable en producción con configuración correcta (SESSION_SECRET, ENV=prod), pero conviene priorizar: unificar manejo de errores (no devolver 500 como 400), timeouts en subprocess y en fetch del portal, y resolver migraciones 019 duplicadas. A medio plazo: paginación/límites en listados, consistencia UX (empty/error/skeleton) y accesibilidad en modales.

---

## 1. Estabilidad (errores, fallos posibles, timeouts, excepciones)

### 1.1 Manejo de excepciones en rutas

- **Problema:** En `routers/portal.py` varias rutas usan `try/except Exception` y devuelven `HTMLResponse(..., status_code=400)` o JSON con el mensaje de la excepción. Errores de servidor (BD, subprocess, archivo no encontrado) se exponen como 400.
- **Archivos/rutas:** `routers/portal.py` (rutas que sirven HTML del portal y hacen operaciones que pueden fallar: SAT, PDF, descargas, bank).
- **Impacto:** Monitoreo interpreta 400 en lugar de 5xx; usuario puede ver mensajes crudos (`str(e)`).
- **Recomendación:** Errores de servidor → `HTTPException(500, detail="...")` o dejar que suban al handler global en `app.py` (ya existe `server_error_handler` que devuelve HTML/JSON genérico).

### 1.2 Handlers globales

- **app.py:** `@app.exception_handler(404)` y `@app.exception_handler(500)` devuelven HTML para `text/html` y JSON para API. `HTTPException` la maneja FastAPI por defecto; hay `_html_http_error` para códigos 400/401/403/404/429/500/503.
- **Bien:** 500 hace `logging.exception`; no se filtra stack en la respuesta al cliente.

### 1.3 Timeouts

- **SQLite:** `database.py`: `timeout=30`, `busy_timeout=5000`, WAL. Correcto.
- **subprocess.run sin timeout:**
  - `routers/portal.py` ~L64: `subprocess.run(["php", php_script, ...])` para validación FIEL (timeout=30 en el código actual según grep; confirmar que esté en la rama que se despliega).
  - `routers/admin.py` ~L321 y ~L337: `subprocess.run` para scripts de backup/restore (DB y storage) **sin timeout** → riesgo de bloqueo si el script se cuelga.
  - `scripts/sat_worker.py` ~L89: `subprocess.run(cmd, ...)` sin timeout.
- **Frontend:** `static/js/ui.js` define `portalFetchWithTimeout` (default 30s) y `portalFetchJSON` con `timeoutMs` y retry. Varias pantallas ya lo usan (portal_home, portal_clients, portal_products, portal_quotations, portal_providers, bank preview). Otras llamadas pueden usar `fetch()` directo (ver `AUDIT_COVERAGE_REPORT.md` y `docs/UI_PATTERNS.md`). Listados emitidas/recibidas cargan datos vía API; si no usan el helper con timeout, pueden quedar en “Cargando…” indefinidamente.

### 1.4 Dependencias opcionales

- **pdfplumber:** Si falta, flujo PDF→Excel puede generar XLSX vacío o mensaje en hoja Resumen.
- **reportlab:** `/portal/sat/pdf/{uuid}` devuelve error con hint de instalación; no tira la app.
- **PHP (sat_sync):** Validación FIEL y descarga SAT usan `subprocess.run(["php", ...])`. Si PHP no está en PATH, validación FIEL falla; documentar en OPS/LAUNCH.

---

## 2. Funcionamiento (flujos que pueden romperse o confundir)

### 2.1 Sesión expirada

- **get_portal_issuer** (`routers/deps.py`): Sin cookie válida (o token) y sin demo → `HTTPException(401)`. En HTML suele redirigir a `/login`.
- **Modal “Sesión expirada”:** Definido en `templates/base_portal.html`; el helper de fetch en `ui.js` puede interceptar 401 y mostrar modal. No todas las pantallas/submits pasan por el mismo helper; en formularios largos (form de factura, cotización) si el usuario tarda y la sesión expira, el 401 debe mostrar el modal y cerrar overlays de forma consistente.

### 2.2 Sync SAT

- Botón “Sync SAT” encola jobs; el procesamiento lo hace cron o `scripts/sat_worker.py`. Si el cron no está activo, el usuario ve “Sincronización iniciada” pero no llegan datos. No hay mensaje tipo “Puede tardar unos minutos” o “Revisa que el cron esté configurado”.

### 2.3 APIs de catálogo

- Búsqueda ProdServ/Unidad vía `/api/catalogs/...`. Si la API falla o tarda, la UI puede mostrar lista vacía sin distinguir “no hay resultados” de “error de red/timeout”. Ver UX empty vs load-error en `docs/UI_PATTERNS.md`.

### 2.4 Flujos críticos por ruta

- **Portal:** `/portal/home`, `/portal/create`, `/portal/clients`, `/portal/products`, `/portal/invoices/issued`, `/portal/invoices/received`, `/portal/quotations`, `/portal/providers`, `/portal/bank/pdf-to-excel`, `/portal/sat/sync`, `/portal/config/sat`.
- **Auth:** `/login`, `/signup`, `/logout`, `/confirmar-perfil`, `/onboarding`, `/auth/google/callback`, `/auth/facebook/callback`.
- **Admin:** `/admin`, `/admin/users`, `/admin/issuers`, `/admin/impersonate`, `/admin/ops` (backup/restore con subprocess sin timeout).
- **Invoicing:** `/submit` (form factura), descargas XML/PDF.
- **Billing:** `/billing/checkout`, `/webhooks/stripe`.

---

## 3. Base de datos (migraciones, consistencia schema vs código)

### 3.1 Migraciones

- **Directorio:** `migrations/`. Archivos `001_baseline.sql` … `019_*.sql`. Orden por prefijo numérico en `migrations_runner.py` (`_list_migration_files`).
- **Riesgo crítico:** Existen **dos archivos con prefijo 019**: `019_bank_movements.sql` y `019_bank_statements_and_movements.sql`. El runner ordena por `(int(version), path)`, por tanto ambos tienen `version_key = "019"`. Solo se aplicará **una** de las dos (la que quede primera en el orden de archivos); la otra nunca se ejecutará. Esto puede dejar tablas o columnas sin crear según qué dependa el código.
- **Acción:** Renombrar una a `020_...` (o fusionar contenido en una sola 019) y documentar en MIGRATIONS.md.

### 3.2 Aplicación en arranque

- `app.py` startup llama `apply_migrations(DB_PATH)`. Si una migración falla, se hace `rollback`, `logging.exception` y se re-lanza → **la aplicación no arranca**. Correcto para evitar esquema inconsistente.

### 3.3 Pragmas y conexión

- `database.py`: `db()` con `timeout=30`, `PRAGMA foreign_keys = ON`, `busy_timeout = 5000`, `journal_mode = WAL`. Sin pool; una conexión por request. Adecuado para SQLite single-process.

### 3.4 Schema vs código

- Tablas referenciadas en código: `issuers`, `issuer_tokens`, `sat_credentials`, `sat_cfdi`, `sat_requests`, `sat_jobs`, `customer_profiles`, `issuer_products`/`products`, `invoices`, `invoice_items`, `users`, `user_memberships`, `audit_log`, `bank_statements`, `bank_movements`, `bank_pdf_exports`, etc. Las migraciones 003/004/006/008/011/014/016 se aplican vía lógica Python en el runner (`_apply_003_safe_add_columns`, etc.); el resto vía SQL. No se detectó en esta auditoría un desajuste explícito entre columnas usadas en routers/services y columnas creadas en 001 o migraciones posteriores; conviene un chequeo puntual si se añaden features (p. ej. nuevas columnas en `sat_cfdi` o `bank_movements`).

### 3.5 Catálogos

- `database.py`: `db_catalogs()`, `list_catalog()`, `search_catalog()` para `catalogs.db`. Si `CATALOGS_DB` no existe, `db_catalogs()` lanza `FileNotFoundError`. El health check en `app.py` no comprueba explícitamente catalogs.db; rutas que usan catálogos fallarían con 500 si falta el archivo.

---

## 4. UX/UI (carga, errores, empty states, modales, móvil)

### 4.1 Patrones documentados

- **docs/UI_PATTERNS.md:** Empty state (lista vacía) vs load-error (timeout/red/5xx). Componentes: `portal_empty_state`, `portal_load_error` en `templates/portal/_ui_components.html`. Estilos: `portal.css` (`.empty-state`, `.empty-state--empty`, `.empty-state--error`, `.load-error`, `.skeleton`).

### 4.2 Uso real en templates

- **Skeleton + load-error + empty:** Usados en `portal_received.html`, `portal_issued.html`, `portal_quotations.html`, `portal_providers.html` (skeleton inicial, luego fetch, luego mostrar tabla/empty/loadError con Reintentar).
- **Solo empty (sin load-error):** `portal_clients.html`, `portal_products.html` usan `portal_empty_state` pero no siempre incluyen `portal_load_error` con id consistente para mostrar error de carga + Reintentar.
- **innerHTML con mensaje de error:** En `portal_issued.html` y `portal_received.html` se asigna texto a `loadErrorStateMsg`; si ese texto viene del servidor o de una variable no escapada, riesgo XSS. Ver AUDIT_COVERAGE_REPORT.md (revisar sanitización).

### 4.3 Modales y drawers

- Modales en `base_portal.html` (factura rápida, agregar cliente/producto, ProdServ, sesión expirada, etc.). No se verificó focus trap ni cierre con Escape en todos; hay referencias a accesibilidad en PORTAL_AUDITORIA_MEJORAS.md (focus trap, ESC, aria-live). Drawers (detalle CFDI, proveedores) con scroll interno; comportamiento móvil según media queries en `portal.css`.

### 4.4 Móvil

- Tablas con scroll horizontal (`.table-wrap`); lista en cards para emitidas/recibidas (`invoice-list-mobile`). Targets y espaciado en `portal.css` para breakpoints; algunas vistas pueden seguir siendo pesadas en pantallas muy pequeñas.

### 4.5 Estilos inline

- Hay estilos inline en varios templates (portal_products, portal_home, etc.). Recomendación: mover a clases en `portal.css`/`components.css` y usar variables de `portal_tokens.css`.

---

## 5. Seguridad básica (sesiones, secretos, rutas sensibles)

### 5.1 Sesión y cookie

- **config.py:** `SESSION_SECRET` obligatorio en producción (`ENV=prod` → `RuntimeError` si falta). Cookie: `SESSION_COOKIE_NAME = "portal_session"`; `COOKIE_SECURE` según env o `COOKIE_SECURE` env.
- **services/session.py:** Firma HMAC con `SESSION_SECRET`; cookie HttpOnly, SameSite=Lax; Secure si request es HTTPS o `X-Forwarded-Proto: https`. Correcto.

### 5.2 CSRF

- **services/csrf.py:** Token generado y verificado con HMAC. Formularios críticos (login, signup, submit factura, portal config, admin ops, impersonate) reciben `csrf_token` y lo validan (Form o header `X-CSRF-Token`). Rutas en `routers/auth.py`, `routers/invoicing.py`, `routers/portal.py`, `routers/admin.py` usan `csrf_service.verify_csrf_token`. Bien.

### 5.3 Rutas sensibles

- **Portal:** Casi todas las rutas bajo `/portal` dependen de `get_portal_issuer` (cookie o token); 401 si no hay sesión válida.
- **Admin:** `routers/admin.py` usa `_get_session_user_and_issuer` y comprueba rol admin para acceder a `/admin`, users, issuers, memberships, ops, impersonate. Impersonate registrado en audit_log. Rutas admin requieren CSRF en POST.
- **API:** `/api/*` en `routers/api.py`; endpoints de datos (customers, products, invoices, etc.) validan sesión vía mismo mecanismo (cookie/token). No se exponen datos de otros issuers si el código filtra por `issuer_id` correctamente (revisión puntual por endpoint recomendada).
- **Billing:** `/billing/checkout` y `/webhooks/stripe` usan sesión o firma de webhook; webhook debe validar `STRIPE_WEBHOOK_SECRET`.

### 5.4 Secretos

- No se almacenan en código; se leen de `.env` vía `config.py`. `.env` no debe estar en repo (usar `.env.example` como plantilla). Health/status no devuelven secretos.

---

## 6. Mantenibilidad (duplicación, estilos inline, helpers repetidos)

### 6.1 Helpers de fetch

- **Unificado:** `static/js/ui.js`: `portalFetchWithTimeout`, `portalFetchJSON` con timeout, 401, retry. Uso recomendado en todo el portal.
- **Duplicación:** Algunos templates siguen usando `fetch()` directo o lógica distinta para timeout/401 (ver script `scripts/audit_coverage.py` y AUDIT_COVERAGE_REPORT.md). Patrón documentado en `docs/UI_PATTERNS.md`.

### 6.2 Formateo y escape

- **formatDate, formatMoney, escapeHtml, truncate:** Repetidos en varios templates (portal_received, portal_issued, etc.) en lugar de un único módulo o helpers globales en `base_portal.html`. Duplicación de lógica y riesgo de inconsistencias.

### 6.3 Estilos

- Estilos inline en templates; clases repetidas para espaciado. Centralizar en `portal.css`/`components.css` y tokens.

### 6.4 Lógica de listados

- Emitidas, recibidas, cotizaciones, proveedores comparten patrón: skeleton → fetch → render tabla/cards → empty/loadError. La implementación está repetida por template (debounce, filtros, paginación en cliente). Valorar componente o script común para “listado con filtros y paginación”.

---

## 7. Performance básica (listados grandes, queries, respuestas)

### 7.1 Límites en queries

- **routers/portal.py:** Varios SELECT con `LIMIT 50`, `LIMIT 300`, `LIMIT 500` (emitidas/recibidas, clientes, productos). No hay paginación server-side; se devuelve hasta 300/500 ítems en una sola respuesta. Para cuentas con muchos CFDI o clientes, la respuesta puede ser pesada y lenta.
- **routers/api.py:** Endpoints como `/api/customers`, `/api/products` aceptan `limit`; el front a veces pide `limit=200`. Validar límite máximo (p. ej. 500) y documentarlo.

### 7.2 N+1 y múltiples round-trips

- En algunas vistas del portal se hacen varias consultas secuenciales (issuer, credentials, counts, listado). No se revisó en detalle cada ruta; para listados muy cargados conviene revisar si se puede reducir a menos queries o un único SELECT con agregaciones.

### 7.3 Respuestas grandes

- Export Excel (bank), descarga de XML/PDF: flujos que devuelven archivos grandes; el body se sirve por streaming donde aplica (FileResponse). PDF-to-Excel genera archivo en disco y devuelve URL de descarga; correcto.

### 7.4 Frontend

- Listados que cargan 200–500 ítems en memoria y luego filtran/paginan en cliente pueden volverse lentos en dispositivos débiles. Valorar paginación server-side (limit/offset o cursor) para emitidas/recibidas y otros listados grandes.

---

## Lista priorizada de mejoras

### Alta

1. **Errores 500 como 400:** Revisar `routers/portal.py` (y otras rutas HTML) para no devolver 400 con cuerpo de excepción; usar 500 y mensaje genérico.
2. **Migraciones 019 duplicadas:** Resolver conflicto entre `019_bank_movements.sql` y `019_bank_statements_and_movements.sql` (renombrar una a 020 o fusionar).
3. **subprocess.run sin timeout:** Añadir `timeout=N` en `routers/admin.py` (backup/restore) y en `scripts/sat_worker.py`.
4. **Timeouts en fetch del portal:** Asegurar que todos los listados y submits usen `portalFetchWithTimeout`/`portalFetchJSON` con timeout y manejo 401 (y Reintentar en load-error).

### Media

5. **Sesión expirada unificada:** Un solo comportamiento en 401 (modal + cierre de overlays) en todas las pantallas y formularios.
6. **Empty state vs load-error:** Misma convención en todas las listas; siempre `portal_load_error` con Reintentar donde haya fetch; no confundir “lista vacía” con “error de carga”.
7. **Configuración en arranque:** Ya se valida SESSION_SECRET en prod; opcional: comprobar SITE_URL si se usa billing; documentar en .env.example y LAUNCH_CHECKLIST.
8. **Paginación y límites:** Límite máximo en APIs de listado (p. ej. 500); paginación server-side para emitidas/recibidas si el volumen lo requiere.
9. **Sanitización de mensajes de error:** Revisar asignaciones a `loadErrorStateMsg` (y similares) para no inyectar HTML no escapado (XSS).

### Baja

10. **Sync SAT y documentación:** Mensaje en UI “La sincronización puede tardar unos minutos”; documentar cron/sat_worker en OPS_RUNBOOK.
11. **Estilos y breadcrumbs:** Reducir estilos inline; breadcrumbs en detalle CFDI y cotización.
12. **Accesibilidad:** Focus trap y Escape en modales/drawers; aria-live en toasts y load-error.
13. **Helpers compartidos:** Centralizar formatDate, formatMoney, escapeHtml en un script común o en base_portal para no duplicar por template.
14. **Catálogos DB en health:** Opcional: comprobar existencia de catalogs.db en `/health` o `/ready` para fallar pronto si falta.

---

## Riesgos de producción

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| SESSION_SECRET no definido en prod | Baja | Alto (app no arranca o sesiones inválidas) | Ya validado en config.py (RuntimeError en prod) |
| Migración 019 aplica solo una de dos | Alta si hay dos archivos | Medio/Alto (tablas/columnas faltantes) | Renombrar/fusionar 019 y desplegar con migración correcta |
| subprocess de backup/restore colgado | Media | Medio (admin bloqueado) | Añadir timeout y mensaje claro en UI |
| Listado muy grande sin paginación | Media | Medio (timeout o respuesta lenta) | Límites máximos y paginación server-side |
| PHP no instalado en servidor | Media | Alto para FIEL/SAT | Documentar en LAUNCH_CHECKLIST y OPS_RUNBOOK |
| Error de servidor mostrado como 400 | Alta | Bajo (confusión en logs y soporte) | Job 1: unificar manejo de errores |
| Fetch sin timeout en alguna pantalla | Media | Medio (UI colgada) | Usar portalFetchWithTimeout en todas las cargas |
| XSS en mensaje de error de carga | Baja | Alto si se inyecta contenido | Escapar siempre contenido en loadErrorStateMsg |

---

## Qué sí está listo y qué no

### Listo para producción (con configuración correcta)

- Arranque con migraciones aplicadas y health/ready/status.
- Autenticación por cookie (y token), CSRF en formularios críticos, SESSION_SECRET obligatorio en prod.
- Portal básico: home, clientes, productos, emitidas, recibidas, cotizaciones, proveedores, bank PDF-to-Excel (preview y export), config SAT, plan.
- API REST bajo `/api` con autenticación y filtro por issuer.
- Admin: usuarios, issuers, memberships, ops (backup/restore), impersonate con audit_log.
- Billing: checkout Stripe y webhook.
- Empty states y load-error en varias pantallas; skeletons en emitidas, recibidas, cotizaciones, proveedores.
- Helpers de fetch con timeout y 401 en parte del portal (base_portal, home, clients, products, quotations, providers, bank).
- SQLite con WAL, busy_timeout, foreign_keys; conexión por request sin pool.

### No listo o a reforzar

- **Migraciones:** Conflicto 019 debe resolverse antes de desplegar en entornos nuevos o con DB vacía.
- **Manejo de errores:** Unificar para no devolver 500 como 400 con detalle de excepción.
- **Timeouts:** subprocess en admin y sat_worker sin timeout; algunas llamadas fetch aún sin helper con timeout.
- **Paginación:** Listados grandes (emitidas/recibidas) sin paginación server-side; límites altos (300/500) en una sola respuesta.
- **UX consistente:** No todas las listas tienen load-error + Reintentar; modales sin focus trap/ESC documentado en todas partes.
- **Catálogos:** Si catalogs.db no existe, las rutas que dependen de él fallan con 500; health no lo comprueba.
- **Documentación operativa:** Cron SAT, requisito de PHP, y recuperación ante fallos (RECOVERY_PLAYBOOK, MIGRATIONS.md) deben estar actualizados.

---

## Jobs recomendados

1. **Job 1 — Unificar manejo de errores en el portal (estabilidad)**  
   Revisar rutas en `routers/portal.py` (y otras que sirvan HTML) que usen `try/except Exception` y devuelvan 400 con cuerpo de excepción. Reemplazar por 500 con mensaje genérico o dejar que suba al handler global. **Prioridad: Alta.**

2. **Job 2 — Resolver migraciones 019 duplicadas (base de datos)**  
   Renombrar `019_bank_movements.sql` o `019_bank_statements_and_movements.sql` a `020_...` (o fusionar contenido en una sola 019). Comprobar que el esquema resultante coincida con el uso en `routers/portal.py` y servicios de bank. Actualizar MIGRATIONS.md. **Prioridad: Alta.**

3. **Job 3 — Timeouts en subprocess (estabilidad)**  
   Añadir `timeout=...` a todas las llamadas `subprocess.run` en `routers/admin.py` (backup/restore) y `scripts/sat_worker.py`. Definir valor razonable (p. ej. 300 s para backups) y manejar `TimeoutExpired` con mensaje claro. **Prioridad: Alta.**

4. **Job 4 — Timeouts y 401 en todas las peticiones del portal (estabilidad + UX)**  
   Asegurar que listados y submits usen `portalFetchWithTimeout` o `portalFetchJSON`; timeout 30 s; en 401 mostrar modal sesión expirada y cerrar overlays; en timeout/error mostrar load-error con Reintentar. Documentar en UI_PATTERNS.md. **Prioridad: Alta.**

5. **Job 5 — Experiencia de sesión expirada (UX)**  
   Un solo comportamiento ante 401: modal “Sesión expirada” y cierre de overlays/drawers en todas las pantallas (form factura, cotización, config SAT, etc.). **Prioridad: Media.**

6. **Job 6 — Consistencia empty state / load-error (UX)**  
   Todas las listas que cargan por fetch deben tener: skeleton inicial, load-error con Reintentar cuando falle la petición, empty state cuando 200 y lista vacía. Revisar portal_clients, portal_products y el resto. **Prioridad: Media.**

7. **Job 7 — Paginación y límites en listados (performance)**  
   Límite máximo en APIs de listado (ej. 500); parámetros limit/offset o page; en front, paginación server-side para emitidas/recibidas si hay muchos registros. **Prioridad: Media.**

8. **Job 8 — Verificación de configuración y documentación (operación)**  
   En prod, SESSION_SECRET ya obligatorio. Opcional: comprobar SITE_URL si billing activo. Actualizar .env.example, LAUNCH_CHECKLIST y OPS_RUNBOOK (PHP, cron SAT, recuperación). **Prioridad: Media.**

9. **Job 9 — Sanitización de mensajes de error en UI (seguridad)**  
   Revisar asignaciones a `loadErrorStateMsg` y similares; asegurar que todo texto mostrado esté escapado (evitar XSS). **Prioridad: Media.**

10. **Job 10 — Sync SAT y mensaje al usuario (funcionamiento)**  
    Mensaje en UI tipo “La sincronización puede tardar unos minutos”. Documentar en OPS_RUNBOOK el cron y sat_worker. **Prioridad: Baja.**

11. **Job 11 — Estilos y accesibilidad (mantenibilidad + UX)**  
    Reducir estilos inline; focus trap y Escape en modales; aria-live en toasts y load-error; breadcrumbs en detalle CFDI y cotización. **Prioridad: Baja.**

12. **Job 12 — Helpers compartidos (mantenibilidad)**  
    Centralizar formatDate, formatMoney, escapeHtml, truncate en un script común incluido desde base_portal para no duplicar en cada template. **Prioridad: Baja.**

---

## Referencias en el proyecto

| Documento | Contenido |
|-----------|-----------|
| **AUDIT_COVERAGE_REPORT.md** | Generado por `scripts/audit_coverage.py`: patrones de errores, fetch sin timeout, subprocess sin timeout |
| **PORTAL_AUDITORIA_MEJORAS.md** | Hallazgos detallados F1–F9, C1–C7, D1–D11 |
| **docs/UI_PATTERNS.md** | Empty state vs load-error, skeleton, componentes reutilizables |
| **OPS_RUNBOOK.md** | Operación, health, backups, cron |
| **LAUNCH_CHECKLIST.md** | Checklist de puesta en marcha |
| **RECOVERY_PLAYBOOK.md** | Qué hacer cuando algo falla |
| **MIGRATIONS.md** | Funcionamiento de migraciones y rollback |

**Código clave:**  
`app.py` (handlers, startup, health), `config.py`, `database.py`, `migrations_runner.py`, `routers/portal.py`, `routers/deps.py`, `routers/admin.py`, `services/session.py`, `services/csrf.py`, `templates/base_portal.html`, `static/js/ui.js`, `templates/portal/_ui_components.html`.

---

*Auditoría completa como arquitecto de software / tech lead. Solo lectura y plan; sin cambios de código.*

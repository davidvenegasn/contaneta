# Auditoría completa para análisis por IA (ChatGPT u otra)

**Objetivo:** Este documento describe el funcionamiento actual del programa ContaNeta, vulnerabilidades identificadas, aspectos estructurales y de diseño, y puntos a considerar para que una IA pueda analizarlo y proponer mejoras concretas sin romper la lógica contable/SAT.

**Reglas que no se deben violar:** No introducir React/Tailwind/build; no cambiar cálculos ni flujos SAT/CFDI; cambios incrementales y validables.

---

## 1. Qué hace el programa (funcionamiento actual)

### 1.1 Descripción general

- **ContaNeta** es un portal contable/fiscal en México. Permite a emisores fiscales (por token o login email/contraseña/OAuth):
  - Gestionar clientes, productos, proveedores.
  - Emitir facturas (CFDI) y cotizaciones.
  - Sincronizar con SAT (descarga masiva de XML, validación FIEL).
  - Subir PDF de estados de cuenta bancarios, convertirlos a Excel y conciliar con CFDI.
  - Ver facturas emitidas/recibidas, nómina, resumen, plan/suscripción (Stripe).
- **Multi-tenant:** Cada petición identifica al emisor por `issuer_id` que **siempre** viene de la sesión (cookie o token inicial), nunca de query/body. Las consultas y descargas filtran por `issuer_id`.

### 1.2 Stack

- **Backend:** Python 3, FastAPI. Entrada: `app.py`. Config: `config.py` (variables desde `.env`).
- **Frontend:** Jinja2 (HTML), CSS en `static/css/`, JS vanilla en `static/js/`. Sin frameworks ni bundler.
- **Base de datos:** SQLite: `invoicing.db` (principal) y `catalogs/catalogs.db` (catálogos SAT). Migraciones en `migrations/*.sql` + lógica Python en `migrations_runner.py`.
- **SAT:** Scripts PHP en `sat_sync/` (phpcfdi/sat-ws-descarga-masiva). La app los invoca con `subprocess` (ej. `check_fiel.php` con timeout 30s). Sync masivo vía cron o `scripts/sat_worker.py`.

### 1.3 Flujo de una petición

1. **Middleware:** request_id → security headers (CSP, X-Frame-Options, etc.) → redirect_token (si hay `?token=` en URL de portal, fija cookie y quita el token de la URL).
2. **Autenticación:** En rutas `/portal/`, `/api/`, `/download/`: dependencia `get_portal_issuer(request)`. Resuelve identidad por cookie `portal_session` (firmada HMAC) o por `?token=`. Sin sesión válida: HTML → redirect `/login`; API → 401.
3. **Routers:** auth (login, signup, onboarding, forgot/reset), portal (páginas HTML), api (JSON), invoicing (formulario factura, descargas), admin, public, billing.
4. **Servicios:** session, issuers, users, csrf, subscription, bank_*, pdf_to_excel, etc. Acceden a DB con `database.db()`, `db_rows()`, `db_execute()`.
5. **Errores:** 404/500/HTTPException manejados en `app.py`; respuesta HTML amigable o JSON según `Accept` y si la ruta es `/api/` o `/download/`. No se expone stack al cliente.

### 1.4 Funcionalidades críticas (no tocar lógica)

- Cálculo de totales, IVA, retenciones en facturas.
- Parsing y almacenamiento de XML CFDI.
- Sincronización SAT (estado de solicitudes, jobs, descarga de paquetes).
- Validación FIEL (certificados .cer/.key) vía PHP.
- Conversión PDF banco → movimientos y conciliación con CFDI.
- Generación de PDF/Excel de reportes y cotizaciones.

---

## 2. Vulnerabilidades y riesgos

### 2.1 Severidad: Critical

- **Ninguna crítica identificada** con la revisión actual. Sesión firmada (HMAC), issuer desde sesión, SQL parametrizado en rutas de negocio, uploads con límite y path seguro (`safe_join`).

### 2.2 Severidad: High

| ID | Descripción | Evidencia | Recomendación |
|----|-------------|-----------|---------------|
| H1 | **API JSON sin CSRF:** Los endpoints POST/PUT/DELETE de la API (`/api/customers`, `/api/products`, `/api/quotations`, etc.) no verifican token CSRF. La autenticación es por cookie. Si un sitio malicioso hace que el navegador envíe un POST con cookies (same-origin o en condiciones de CORS), podría ejecutar acciones en nombre del usuario. | `routers/api.py`: create/delete usan `Body(...)` y `get_portal_issuer`; no hay `verify_csrf_token`. | Valorar: (a) exigir header `X-CSRF-Token` en POST/PUT/DELETE de la API cuando la petición viene del mismo origen (leer token del meta o cookie), o (b) documentar que la API es para uso interno del portal y confiar en SameSite=Lax + origen. |
| H2 | **Rate limit en memoria:** El rate limit (`services/rate_limit.py`) usa un diccionario en memoria. En despliegue con varios workers (gunicorn multi-worker), cada proceso tiene su propio contador; el límite efectivo es N × max_attempts. No hay persistencia. | `_STORE: dict[str, list[float]]` en módulo. | Para entornos multi-worker: considerar Redis o límite por IP a nivel de proxy. Documentar el comportamiento actual. |

### 2.3 Severidad: Medium

| ID | Descripción | Evidencia | Recomendación |
|----|-------------|-----------|---------------|
| M1 | **Nombres de tabla/columna en SQL con f-string:** En `database.py`, `list_catalog(table)` y `search_catalog(table, q)` construyen SQL con `table` y nombres de columna desde `_table_columns`/`_pick_column`. Si en el futuro algún llamador pasara `table` desde entrada de usuario, habría riesgo de inyección. Hoy los llamadores (api.py) solo pasan literales ("cfdi_40_productos_servicios", etc.). | `database.py` líneas 98, 117-118, 132-134. `safe_update` y `has_column` también usan f-string con nombre de tabla (desde código). | Mantener lista blanca: solo permitir nombres de tabla/columna desde constantes o listas fijas. Documentar en guía de desarrollo; opcionalmente validar `table` contra whitelist en `list_catalog`/`search_catalog`. |
| M2 | **Logs con datos sensibles:** Algunos `logger.exception` o `logger.warning` incluyen `issuer_id`, `uuid`, `qid`. No se han visto contraseñas ni tokens en logs. Riesgo: en entornos con logs centralizados, evitar que campos identificables (RFC, email) se logueen en claro. | Ej. `portal.py`: "portal: error renderizando ... issuer_id=%s", "uuid=%s". | Revisar que ningún log incluya password, token completo, o RFC/email en texto plano si el nivel de log es INFO en prod. Usar identificadores opacos (id) en lugar de RFC donde sea suficiente. |
| M3 | **Dos fuentes de verdad para el schema:** Existen scripts `db_migrate_*.py` en la raíz del proyecto y en `scripts/legacy/`, mientras que el flujo oficial es `migrations/*.sql` + `migrations_runner.py`. Ejecutar scripts antiguos puede desincronizar el estado de la DB. | Git: archivos db_migrate_* en raíz; migraciones en `migrations/`. | Deprecar o eliminar scripts de migración fuera de `migrations/`; mover cualquier lógica pendiente a una migración numerada y documentar en MIGRATIONS.md. |
| M4 | **Subprocess sin timeout en algunos scripts:** La app usa timeout en `check_fiel.php` (30s) y en admin (60s/120s). Scripts como `sat_worker.py` usan 600s. Otros scripts (legacy, one-off) podrían invocar PHP o shell sin timeout. | `scripts/audit_coverage.py` detecta subprocess sin timeout. | Revisar todos los `subprocess.run`/`Popen` y añadir `timeout=N` donde corresponda. |

### 2.4 Severidad: Low

| ID | Descripción | Evidencia | Recomendación |
|----|-------------|-----------|---------------|
| L1 | **Redirects:** Todas las redirecciones usan URLs fijas (ej. `/portal/home`, `/login`). No se ha encontrado open redirect (parámetro `next` o similar controlado por el usuario). | Búsqueda de `next=`, `redirect.*request` en routers. | Mantener redirecciones solo a rutas internas o URLs construidas por servidor (SITE_URL). |
| L2 | **Content-Disposition filename:** Algunos nombres de archivo en descargas incluyen datos del usuario (RFC, UUID). Ej. `filename="facturas-recibidas-{rfc_norm[:8]}.pdf"`. Riesgo menor de caracteres especiales o longitud. | `routers/api.py`, `routers/portal.py`, `routers/invoicing.py`. | Sanitizar o truncar el segmento que va en filename (solo alfanuméricos y guión) para evitar problemas con cabeceras. |
| L3 | **FIEL: nombre de archivo en log:** Al subir .cer/.key se podría registrar el nombre original del archivo; si contiene datos sensibles en el nombre, no loguearlo. | `routers/portal.py` upload FIEL. | Asegurar que en logs no se escriba el nombre de archivo subido por el usuario, o usar solo un hash/identificador. |

---

## 3. Estructura y mantenibilidad

### 3.1 Puntos fuertes

- Separación clara: routers por dominio (auth, portal, api, admin, invoicing, public, billing).
- Dependencia única de identidad: `get_portal_issuer` centraliza cookie/token y rellena `request.state`.
- Servicios reutilizables (session, issuers, users, csrf, bank_*, pdf_to_excel).
- Migraciones versionadas y aplicadas al arranque; conexiones SQLite con WAL y busy_timeout.
- Handlers globales de error que evitan pantallas blancas y no exponen stack.

### 3.2 Deuda y fragilidad

- **Duplicación de contexto de portal:** Cada ruta que renderiza HTML construye un dict con issuer, active_page, title, csrf_token, etc. La función `_render_portal` centraliza parte, pero hay repetición de `extra` y de bloques try/except con el mismo patrón. Extraer helpers por sección reduciría ruido.
- **Tamaño de routers:** `routers/portal.py` tiene miles de líneas. Dificulta navegación y pruebas. Valorar dividir por dominio (portal_invoices, portal_bank, portal_config, etc.) manteniendo un único prefijo `/portal/`.
- **Construcción de WHERE dinámico en API:** En `api.py` y `portal.py` se construyen cláusulas `WHERE` con f-strings (ej. `base_where`, `where_sql`) pero los **valores** van en parámetros. Los nombres de columnas son fijos en código. Riesgo bajo si nadie introduce columnas desde input; documentar y no usar input de usuario en nombres de columnas.
- **Tests:** Solo existe `tests/test_import.py` (import de app/config y ruta /health). No hay tests de integración de rutas ni de aislamiento tenant (ej. usuario A no puede descargar XML de usuario B). Añadir al menos un test de aislamiento para descargas.

### 3.3 Convenciones

- Python: snake_case. Comentarios y mensajes al usuario en español.
- CSS: tokens en `portal_tokens.css`; BEM-like en componentes. No añadir !important sin justificación.
- Jinja: `template_name` siempre literal; no pasar nombres de template desde input.

---

## 4. Cosas a considerar (config, operación, diseño)

### 4.1 Configuración y entorno

- **ENV=prod:** Obliga SESSION_SECRET, comprueba SITE_URL, PHP (si SAT), storage escribible. Si falla, la app no arranca. En dev, SESSION_SECRET puede ser aleatorio (warning).
- **DEV_MODE / ALLOW_DEMO_PORTAL:** En prod debe ser 0. Si por error se deja ALLOW_DEMO_PORTAL=1, cualquiera podría entrar al portal con el issuer demo sin autenticación.
- **CORS:** No se ha configurado CORS explícitamente en el documento; si se expone la API a otro origen, habría que definir Allow-Origin y considerar CSRF/credentials.
- **Secrets:** SESSION_SECRET, Stripe, SMTP, etc. en .env. No subir .env; .env.example sin valores reales.

### 4.2 Logging y observabilidad

- Request_id en middleware; se puede enviar en cabecera de respuesta (LOG_REQUEST_ID=1). Útil para trazar una petición en logs.
- LOG_FILE opcional: si se define, los logs se escriben también en archivo. Formato configurable con LOG_FORMAT.
- No hay métricas (Prometheus, etc.) ni tracing distribuido. Para producción grande, considerar instrumentación.

### 4.3 Uploads

- PDF bancarios: máximo 15MB por archivo, 50MB total en multi-upload; validación de extensión .pdf y content-type; ruta de guardado con `safe_join`; nombre de archivo generado en servidor (timestamp + hash).
- FIEL: .cer y .key; máximo 2MB cada uno; validación de extensión. Contenido no se ejecuta; se guarda en `storage/credentials/{issuer_id}/`.
- No se ha revisado exhaustivamente si algún parser de PDF (pdfplumber, etc.) puede ser explotado con PDFs malformados; asumir actualizaciones de dependencias.

### 4.4 Paginación y límites

- API: DEFAULT_LIST_LIMIT=200, MAX_LIST_LIMIT=500. Todos los listados usan Query(ge=1, le=MAX_LIST_LIMIT). Evita devolver miles de filas en una petición.
- Algunas listas HTML (portal) cargan datos por fetch con paginación; revisar que no se carguen todos los registros en el cliente de una vez.

### 4.5 Dependencias

- requirements.txt: FastAPI, uvicorn, jinja2, python-dotenv, requests, reportlab, openpyxl, pandas, pdfplumber, qrcode, Pillow, bcrypt, httpx, gunicorn, stripe. Mantener actualizadas por seguridad (avisos de CVE).

---

## 5. Mejoras recomendadas (priorizadas)

1. **Documentar decisión API + CSRF** (H1): Si la API solo se usa desde el mismo origen y con cookie, documentar que no se usa CSRF en JSON por diseño; si se abre a otros orígenes, añadir CSRF o otro mecanismo.
2. **Rate limit multi-worker** (H2): Documentar límite en memoria; si se usa gunicorn con varios workers, indicar en runbook o considerar Redis.
3. **Whitelist de tablas en catálogos** (M1): En `list_catalog`/`search_catalog`, validar `table` contra una lista fija de nombres permitidos; fallar si no está en la lista.
4. **Revisión de logs** (M2): Barrido de logger.* para no incluir password, token completo, ni RFC/email en producción.
5. **Unificar migraciones** (M3): Marcar db_migrate_*.py como obsoletos; mover lógica necesaria a migrations/*.sql o migrations_runner.
6. **Timeouts en subprocess** (M4): Revisar scripts que llamen a PHP o shell y añadir timeout.
7. **Test de aislamiento tenant** (L): Test automatizado: dos usuarios A y B; A no puede acceder a descarga (XML/PDF) de un UUID que pertenece a B.
8. **Sanitizar filename en Content-Disposition** (L2): Función helper que deje solo caracteres seguros y longitud máxima en el nombre de archivo de descarga.

---

## 6. Instrucciones para el analista (IA)

Al analizar este proyecto:

1. **Respeta las reglas** del proyecto: no frameworks nuevos (React, Tailwind, build); no cambiar lógica contable ni SAT; cambios incrementales.
2. **Usa este documento** como fuente de verdad sobre vulnerabilidades y consideraciones ya identificadas. No repitas exactamente lo mismo; profundiza o propón pasos concretos de implementación.
3. **Prioriza** según severidad (Critical > High > Medium > Low) y según esfuerzo/riesgo. Propón cambios pequeños y validables (smoke test o test unitario).
4. **Para cada propuesta:** indica archivo(s) y función/ruta afectados; si hay riesgo de regresión, sugiere cómo validar (ej. script de smoke o caso de prueba).
5. **Estructura:** si propones refactors (ej. dividir portal.py), mantén el mismo comportamiento externo (mismas URLs y respuestas).
6. **Documentación:** sugiere actualizaciones a README, MIGRATIONS.md, o docs/ cuando el cambio afecte a operación o desarrollo.

Puedes usar además los documentos `docs/ARCHITECTURE.md`, `docs/FRONTEND_GUIDE.md`, `docs/AUDIT_REPORT.md` y `docs/README_FOR_AI.md` para más contexto.

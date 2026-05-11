# Auditoría técnica y de producto — Conta Invoicing MVP

Proyecto: facturación y portal con integración SAT (CFDI).  
Alcance: arquitectura, frontend/UX, animaciones, seguridad, rendimiento, deuda técnica.  
Idioma: español (código y comentarios mayormente en español).

---

## 1. ARQUITECTURA DE SOFTWARE

### 1.1 Estructura de carpetas

- **routers/** — Rutas FastAPI: `portal.py`, `api.py`, `auth.py`, `admin.py`, `invoicing.py`, `public.py`, `deps.py`, `billing` (incluido en app). Separación por dominio (portal HTML, API JSON, auth, admin).
- **services/** — Lógica de negocio: `session.py`, `issuers.py`, `users.py`, `subscription.py`, `csrf.py`, `action_log.py`, `audit`, `quotations.py`, `form_parse.py`, `email_sender.py`. Sin capa de repositorio explícita; servicios llaman a `database.db()` / `db_rows()` directamente.
- **templates/** — Jinja2: `base_portal.html`, `base_admin.html`, páginas portal (`portal_*.html`), `form.html` y secciones en `form/_section_*.html`, auth (`login.html`, `signup.html`, etc.), públicos (`public_quotation*.html`).
- **static/** — CSS (`portal.css`, `form.css`, `components.css`, `portal_tokens.css`) y JS (`ui.js` y otros). Sin bundler; carga por `<link>`/`<script>`.
- **sat_sync/** — Integración SAT en PHP (Composer, phpcfdi/sat-ws-descarga-masiva): `sync.php`, `check_fiel.php`, `parse_xml.php`, etc. La app Python invoca scripts PHP vía `subprocess` (ej. `check_fiel.php` para validar FIEL).
- **scripts/** — Operacionales y one-off: `backup_db.sh`, `backup_storage_xml.sh`, `cron_backup_example.sh`, `smoke.sh`, `smoke_selfserve.py`, `smoke_onboarding.py`, `sat_worker.py`, `link_issuers_to_users.py`, `set_plan_pro_*.py`, `run_migrations.py`, etc.
- **migrations/** — SQL versionado: `001_baseline.sql` hasta `016_*.sql`. Aplicadas al arranque por `migrations_runner.apply_migrations(DB_PATH)`.

### 1.2 Puntos de entrada y configuración

- **Entrada:** `app.py` (FastAPI). Arranque típico: `uvicorn app:app --reload` o `./run_server.sh [puerto]` (run_server.sh usa `.venv/bin/python -m uvicorn` con `--host 0.0.0.0` y `--reload`).
- **Configuración:** `config.py` carga `.env` con `dotenv`; no hay `config.py` alternativo. Variables clave: `ENV`, `IS_PROD`, `DEV_MODE`, `ALLOW_DEMO_PORTAL`, `SESSION_SECRET`, `DB_PATH`, `COOKIE_SECURE`, etc. `.env.example` documenta todas las variables y recomienda no subir `.env`.

### 1.3 Base de datos

- **Motor:** SQLite (`invoicing.db` por defecto; ruta por `APP_DB_PATH`). Catálogos en `catalogs/catalogs.db`.
- **Acceso:** `database.py` expone `db()` (conexión con `row_factory`, `PRAGMA foreign_keys=ON`, `busy_timeout=5000`, `journal_mode=WAL`), `db_rows(sql, params)`, `db_execute(sql, params)`, `table_exists`, `has_column`, `safe_update`. Cada llamada abre/cierra conexión (sin pool).
- **Schema principal (001_baseline + migraciones):** `issuers`, `issuer_tokens`, `sat_credentials`, `sat_sync_state`, `sat_cfdi`, `sat_requests`, `sat_jobs`, `customer_profiles`, `supplier_profiles`, `issuer_products`, `quotations` / `quotation_items`, `invoices` / `invoice_items`, `payment_relations`; más `users`, `memberships`, `schema_migrations`, `audit_log`, tablas de verificación email y reset password (migraciones 012+), `subscriptions`, etc.
- **Migraciones:** `migrations_runner.py` aplica `migrations/*.sql` ordenados por prefijo numérico; algunas versiones (003, 004, 006, 008, 011, 014, 016) tienen lógica Python inline (`_safe_add_column`, rebuild de tablas). Tabla `schema_migrations` registra versiones aplicadas. Idempotente.

### 1.4 Capas y dependencias

- **Flujo:** Rutas (routers) → `Depends(get_portal_issuer)` → servicios → `database.db()` / `db_rows()`.
- **get_portal_issuer (routers/deps.py):** Resuelve identidad por cookie de sesión o por `?token=`. Establece `request.state.issuer_id`, `request.state.issuer`, `request.state.user_id`, etc. Sin cookie válida: HTML → 401 con detail "redirigir a /login"; API → 401. Demo issuer solo si `DEV_MODE` y `ALLOW_DEMO_PORTAL` y no es API.
- **Inyección:** FastAPI Depends para `get_portal_issuer`; no hay contenedor IoC. Servicios son módulos importados (ej. `from services import issuers, session`). Errores: HTTPException en dependencias; excepciones no capturadas llegan a handlers globales (404/500) que devuelven HTML o JSON según `Accept` y si la ruta es `/api/` o `/download/`.

### 1.5 APIs

- **Prefijos:** `/api/` (API JSON, `routers/api.py`), `/portal/` (HTML y algunas respuestas JSON para listas), `/download/` (XML/PDF por UUID, protegido por sesión). Rutas públicas: `/`, `/login`, `/signup`, `/q/`, `/public/`, `/health`, `/ready`, `/status`.
- **Autenticación:** API y download exigen `get_portal_issuer` (cookie o token). No hay Bearer JWT en uso; token legacy en query solo para login inicial, luego cookie.
- **Respuestas:** `/api/*` devuelve JSON (listas, account status, catálogos, cotizaciones, proveedores, etc.). Errores con cuerpo uniforme `{ ok: false, error: { code, message }, detail }` (app.py). Portal HTML devuelve `HTMLResponse` con Jinja2.

### 1.6 Dependencias externas

- **PHP (sat_sync):** Requerido para FIEL (validación con `check_fiel.php`) y para sincronización SAT (sync.php, etc.). Ejecución vía `subprocess` con `APP_DB_PATH` en env. Cron documentado (ej. cron_sat_sync) para ejecutar sync periódicamente.
- **Workers:** `scripts/sat_worker.py` procesa cola `sat_jobs`; puede usarse desde cron como alternativa o complemento al flujo PHP.
- **Cron:** Backups (backup_db.sh, backup_storage), SAT sync, opcionalmente sat_worker. Documentado en OPS_RUNBOOK, LAUNCH_CHECKLIST, BACKLOG.

---

## 2. FRONTEND Y UX

### 2.1 Templates y herencia

- **Base:** `base_portal.html` define layout del portal: meta CSRF, estilos (form.css, portal_tokens.css, components.css, portal.css), fuentes (Plus Jakarta Sans), bloques inline para demo/impersonation/welcome, macros para iconos y month_picker, barra de carga, sidebar, topbar, breadcrumbs, menú usuario, `{% block content %}`, toasts y scripts.
- **Herencia:** Páginas portal extienden `base_portal.html` y rellenan `title`, `active_page`, `content` y opcionalmente `topbar_actions`, `page_icon`.
- **Includes:** `portal_list_sync_bar.html` (barra de sync SAT en listas — actualmente no incluida tras quitar Sync SAT de la UI), secciones del formulario en `form/_section_*.html` (comprobante, receptor, conceptos, IVA, retenciones, extras, resumen, sticky action, scripts).

### 2.2 Navegación

- **Sidebar:** Drawer en móvil (`sidebar-drawer`), navegación por secciones (Principal: Inicio, Genera factura; Facturas: Emitidas, Recibidas, Nómina; Catálogos: Clientes, Proveedores, Productos; Otros: Cotizaciones, Resumen, Mi plan). Cierre con botón y backdrop.
- **Topbar:** Izquierda: toggle sidebar, nombre/RFC del issuer. Centro: título de página (visible sobre todo en móvil). Derecha: acciones de página, menú usuario (dropdown con configuración, FIEL, datos fiscales, seguridad, Resumen, Inicio, modo noche, Cerrar sesión).
- **Breadcrumbs:** `portal-topbar__breadcrumb`: Inicio › [página actual] (Emitidas, Recibidas, Clientes, etc.).
- **Menú usuario:** `role="menu"`, `role="menuitem"` en enlaces y botones; chips de estado SAT/Catálogo con datos del servidor.

### 2.3 Páginas clave

- **Inicio:** `/portal/home` (portal_home.html).
- **Facturas emitidas/recibidas:** `/portal/invoices/issued`, `/portal/invoices/received` (listados con mes, descarga). **P41:** detalle CFDI en drawer: clic en fila o card abre panel lateral (UUID, receptor/emisor, totales, PDF/XML/Copiar UUID); ESC, overlay y scroll interno; sin recargar página.
- **Genera factura:** `/portal/create` (form.html con secciones incluidas; modos simple/multi según flujo).
- **Clientes / Productos / Proveedores:** `/portal/clients`, `/portal/products`, `/portal/providers` (listados; proveedores con drawer de facturas).
- **Config SAT:** `/portal/config/sat` (FIEL, validación).
- **Login / Signup:** `/login`, `/signup` (y `/register` → redirect signup), onboarding, confirmar-perfil, forgot, reset-password.

### 2.4 Formularios

- **Validación:** Backend en routers (Form(...), validadores en `validators` para cliente/producto). Front: HTML5 y JS en formularios (ej. form); mensajes de error vía toasts y estados vacíos.
- **Feedback:** Toasts (`window.uiToast`, `portalToast` en base), empty states en listas, overlays de éxito (`uiSuccessOverlay`), botones con estado loading (`uiSetButtonLoading`) y éxito (`uiSetButtonSuccess`). Errores 4xx/5xx en listas muestran bloque "No se pudo cargar" + Reintentar (BACKLOG B6).

### 2.5 Responsive y móvil

- **Breakpoints y touch:** CSS en portal.css/form/components; drawer para sidebar; listas en tablas con `.table-wrap` y scroll horizontal en móvil (MOBILE_CHECKLIST 390px). Touch targets: botones y enlaces con padding suficiente; en varios lugares se acercan a ~44px (btn, nav-item).
- **Documentación:** MOBILE_CHECKLIST.md, QA_MOBILE_SMOKE.md; BACKLOG menciona vista en cards para Clientes/Productos/Proveedores en 390px como mejora.

### 2.6 Accesibilidad

- **Patrones observados:** `aria-label`, `aria-hidden`, `aria-expanded`, `aria-haspopup`, `aria-live="polite"`, `aria-controls`, `role="banner"`, `role="menu"`/`role="menuitem"`, `role="dialog"`, `role="status"`, `role="switch"` (modo noche), `aria-modal`, breadcrumb con `aria-label`. Focus: menú usuario y drawer con soporte de teclado/ESC documentado en BACKLOG (B5 drawer proveedores). Contraste: no auditado en detalle; uso de variables CSS y estilos coherentes.

---

## 3. ANIMACIONES Y MICRO-INTERACCIONES

### 3.1 CSS

- **Transiciones:** Múltiples en portal.css, form.css, components.css (120–350 ms): transform, background, border-color, box-shadow, opacity. Easing: `ease`, `cubic-bezier(.2,.8,.2,1)` o similar.
- **Keyframes:** `fadeSlideIn`, `pageIn`, `pageOut`, `toastIn`, `shimmer`, `menuIn`, `fiel-spin`, `btnSpinner`, `successCheckPop`, `successCheckDraw`, `provider-drawer-skeleton`, `cardEnter`, `formModalIn`.
- **Clases:** `.fade-in` (y `--1` … `--5` para delay escalonado), `.spinner`, `.spinner--sm`, `.btn__spinner`, modales (confirm-modal, welcome-popup) con transición de opacidad/visibility.

### 3.2 JS

- **ui.js:** Toasts, loading en botones (spinner), skeleton para tablas, success overlay (checkmark animado, acciones, copiar enlace). No controla directamente apertura/cierre de modales del sidebar; el sidebar y el menú usuario están en el HTML/CSS y se manejan con script inline o en base_portal.
- **Sidebar/drawer:** Abre/cierra con clases y atributos (`aria-expanded`, `hidden`); transiciones CSS (transform, left, opacity) definidas en portal.css.
- **Barra de carga:** Barra superior en navegación full-page (`/portal/`, `/onboarding/`), activada por clics en enlaces (script en base).

### 3.3 Consistencia y reducción de movimiento

- **Duraciones:** 120–180 ms para micro-interacciones (docs/MOTION.md); algunas transiciones hasta ~350 ms para páginas/drawer.
- **Easing:** `ease`, `ease-out`, `cubic-bezier(0.25, 0.1, 0.25, 1)` o similar.
- **prefers-reduced-motion:** Respetado en portal.css y form.css: `@media (prefers-reduced-motion: reduce)` anula o reduce duraciones (0.01ms) y animaciones; `@media (prefers-reduced-motion: no-preference)` envuelve fade-in, hover de tablas, barra de carga, botones, spinner. Documentado en docs/MOTION.md.

---

## 4. SEGURIDAD Y BUENAS PRÁCTICAS

### 4.1 Autenticación y sesión

- **Cookie:** Nombre `portal_session` (SESSION_COOKIE_NAME). Valor: payload firmado HMAC-SHA256 (user_id|issuer_id|expiry[|restore_issuer_id]); base64url. Parámetros: HttpOnly, SameSite=Lax, Secure según config/request (session.py). TTL: SESSION_TTL_DAYS (default 7).
- **Token legacy:** `?token=` solo para login inicial; middleware en app.py puede fijar cookie y redirigir sin token en URL. API/dashboard no dependen de token en query para operaciones.
- **get_portal_issuer:** Siempre deriva issuer de sesión o token; no se usa `issuer_id` desde query params en rutas (búsqueda en código: no hay `query_params.get("issuer")` para autorización). Issuer se toma de `request.state.issuer` tras la dependencia.

### 4.2 CSRF

- **Formularios críticos:** Login, signup, forgot, reset, confirmar-perfil, onboarding, upload FIEL, submit factura, admin (stop-impersonate, ops), etc. reciben `csrf_token` por Form o `X-CSRF-Token` y verifican con `csrf_service.verify_csrf_token()`. Token generado con `csrf_service.generate_csrf_token()` (firmado, expiración 1 h). Meta `csrf-token` en base_portal para uso desde JS.

### 4.3 Validación y SQL

- **Entradas:** Validadores (`validate_customer`, `validate_product`) en backend; límites en Query (ej. limit/offset, min_length). Rate limit por IP en auth (login, register, forgot, reset) y en portal (FIEL upload, validate, sat sync).
- **SQL:** Consultas con parámetros (`?` o named) en db_rows/db_execute. Los únicos `execute(f"...")` con interpolación usan nombres de tabla/columna controlados por código (PRAGMA table_info, ALTER TABLE con listas fijas, CREATE INDEX); no hay concatenación de entrada de usuario en SQL. En `database.search_catalog`, el nombre de tabla viene del llamador (api.py con tablas fijas); el término de búsqueda va en params.

### 4.4 Exposición de datos

- **issuer_id:** Siempre desde sesión/token vía get_portal_issuer; descargas (XML/PDF) filtran por `issuer_id` en WHERE. BACKLOG A3 recomienda verificar aislamiento en descargas (ya implementado según revisión).
- **Health/status:** `/health` y `/status` no exponen secretos; incluyen db_readable, migrations_applied, storage_writable, migration_version.

---

## 5. RENDIMIENTO Y MANTENIBILIDAD

### 5.1 Carga de listas

- **APIs:** Listas de clientes, productos, cotizaciones, proveedores (reportes) con paginación en api.py (`page`, `per_page`, limit/offset). Otras listas (emitidas/recibidas por mes) acotadas por ventana temporal y issuer.
- **Assets:** Estáticos servidos por StaticFiles en `/static`; fuentes desde Google Fonts (preconnect). Sin minificación ni bundling documentado.

### 5.2 Código y convenciones

- **Duplicación:** Lógica repetida entre routers (ej. construcción de contexto para templates, rate limit) podría extraerse a helpers; servicios ya centralizan lógica de negocio.
- **Nombres:** Coherentes (snake_case en Python, BEM-like en CSS). Prefijos de ruta claros (/api/, /portal/, /download/).
- **Documentación:** README.md (arranque, env, auth, registro), MIGRATIONS.md, OPS_RUNBOOK.md, DEPLOY_GUIDE.md, LAUNCH_CHECKLIST.md, BACKLOG.md, QA_STEPS.md, MOBILE_CHECKLIST.md, docs (MOTION.md, SECURITY_HARDENING.md, PERFORMANCE_PORTAL.md, etc.). Varios .md de auditoría/playbooks (SESSION_AUDIT, RECOVERY_PLAYBOOK, etc.).

---

## 6. DEUDA TÉCNICA Y RIESGOS

### 6.1 Código comentado / scripts one-off

- **Scripts db_migrate_*.py en raíz:** Varios (db_migrate_001_sat_xml.py, 002–009, set_sat_ok_diego_carolina, add_david_venegas, etc.) son migraciones o correcciones one-off; el schema oficial está en migrations/*.sql y en migrations_runner. Riesgo: dos fuentes de verdad si alguien aplica solo unos y no otros; lo recomendable es que todo esté en migrations/ y runner.
- **Código muerto:** No se ha hecho un barrido exhaustivo; no se detectaron bloques grandes comentados obvios en los archivos revisados.

### 6.2 Dos fuentes de verdad (schema)

- **Schema:** Definición en `001_baseline.sql` y migraciones 002–016; además, migraciones "Python" dentro de migrations_runner (003, 004, 006, 008, 011, 014, 016) añaden columnas. Los db_migrate_*.py en raíz no forman parte del flujo estándar de apply_migrations; pueden quedar desincronizados con el estado real de la DB.

### 6.3 Riesgos operativos

- **DEV_MODE en producción:** Si en prod no se define `DEV_MODE=0`, el default con `ENV=prod` es ya 0 (config.py: _DEV_MODE_DEFAULT). Riesgo bajo si ENV=prod está fijado; documentado en .env.example y SESSION_AUDIT.
- **Secrets en .env:** .env no debe subirse; SESSION_SECRET obligatorio en prod (warning CRITICAL al arranque si falta). Otras claves (FACTURAPI, SMTP, Stripe) documentadas en .env.example.

---

## Resumen ejecutivo

### Fortalezas

- Arquitectura clara: routers → get_portal_issuer → servicios → DB; prefijos /api/, /portal/, /download/ bien delimitados.
- Autenticación por cookie firme (HMAC, HttpOnly, SameSite, Secure según entorno); issuer siempre desde sesión, no desde query.
- CSRF en formularios sensibles (login, registro, FIEL, submit, admin) con token firmado y expiración.
- SQL parametrizado en uso normal; sin concatenación de entrada de usuario en sentencias.
- Migraciones versionadas y aplicadas al arranque; WAL y busy_timeout en conexiones SQLite.
- Frontend con base_portal, herencia e includes; navegación consistente (sidebar, topbar, breadcrumbs, menú usuario).
- Animaciones con duraciones razonables y respeto a prefers-reduced-motion en CSS/JS.
- Documentación abundante (README, MIGRATIONS, OPS, BACKLOG, QA_STEPS, MOBILE_CHECKLIST, docs).
- Health/ready/status sin secretos; rate limit en auth y en operaciones FIEL/sync.

### Áreas de mejora

- Unificar schema en migrations/ y runner; deprecar o eliminar scripts db_migrate_*.py de la raíz para evitar dos fuentes de verdad.
- Revisar paginación/límites en todas las listas (HTML y API) para evitar cargar miles de filas (BACKLOG B9).
- Consolidar helpers de rate limit y de contexto de templates entre routers para reducir duplicación.
- Revisar empty states y mensaje único en error de carga (evitar toast + bloque duplicado) (BACKLOG B6).
- Mejorar vista móvil 390px (tablas vs cards) y drawer proveedores (ESC, focus trap) (BACKLOG B4, B5).
- Documentar en un solo flujo self-serve: registro → FIEL → facturas (BACKLOG C10).

### Órdenes sugeridas para el asistente

1. **Migraciones:** Revisar cada `db_migrate_*.py` de la raíz: si la lógica ya está en `migrations/*.sql` o en `migrations_runner.py`, marcar el script como obsoleto en un comentario o mover la lógica pendiente a una migración nueva y eliminar el script.
2. **Paginación API:** Añadir o documentar límite máximo (ej. 500) y parámetros page/per_page en cualquier endpoint de listado que aún no los tenga (clientes, productos, emitidas/recibidas si aplica).
3. **CSRF en formularios:** Revisar que todo POST que modifique estado (crear/editar/eliminar) incluya verificación CSRF (form + header X-CSRF-Token) y que el token se inyecte en el template correspondiente.
4. **Mensaje único en error de listas:** En las páginas que cargan listas por API (emitidas, recibidas, clientes, productos, proveedores), asegurar que en 4xx/5xx se muestre un solo bloque "No se pudo cargar" con Reintentar, sin duplicar con toast.
5. **Drawer proveedores:** Implementar cierre con tecla ESC y focus trap dentro del drawer mientras esté abierto (accesibilidad).
6. **Documento self-serve:** Crear o actualizar un único documento (ej. SELF_SERVE_SAT.md) con pasos: registro, Config SAT → subir y validar FIEL, Emitidas/Recibidas, ver listado; enlazarlo desde README.
7. **Verificación aislamiento descargas:** Añadir test (manual o automatizado) que con dos usuarios A y B verifique que A no puede descargar XML/PDF de un UUID que pertenece a B (GET /download/xml/{uuid}, /download/pdf/{uuid}).
8. **Variables de producción:** En README o DEPLOY_GUIDE, añadir checklist: ENV=prod, DEV_MODE=0, SESSION_SECRET definido, COOKIE_SECURE=1 con HTTPS, ALLOW_DEMO_PORTAL no definido o 0.
9. **Reducción de movimiento:** Revisar que cualquier animación/transición nueva en CSS use `@media (prefers-reduced-motion: no-preference)` o que el global `prefers-reduced-motion: reduce` siga anulando duraciones (0.01ms) en portal.css.
10. **Health en deploy:** Confirmar que el cron o proceso de monitoreo use /health o /ready y que no se expongan SESSION_SECRET ni rutas internas en respuestas.

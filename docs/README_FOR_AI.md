# Contexto para IA (ChatGPT / Cursor / etc.) — ContaNeta

Este documento sirve para que una IA entienda rápido de qué va el proyecto, cómo está hecho y qué se ha auditado. Léelo primero si vas a proponer cambios o responder preguntas sobre el código.

---

## 1. Qué es el proyecto

- **Nombre:** ContaNeta (Conta Invoicing MVP).
- **Qué hace:** Portal contable/fiscal en México: facturación (CFDI), integración con SAT (descarga masiva, FIEL), clientes/productos/proveedores, cotizaciones, movimientos bancarios (subir PDF de estados de cuenta, convertir a Excel), nómina, resumen, plan/suscripción.
- **Usuarios:** Emisores fiscales (empresas o personas) que se identifican por token o por login (email/contraseña u OAuth). Multi-tenant por `issuer_id` (siempre desde sesión, nunca desde query).

---

## 2. Stack técnico (sin cambiarlo)

- **Backend:** Python 3, FastAPI. Sin Django ni Flask.
- **Frontend:** Jinja2 (templates HTML), CSS plano en `static/css/`, JS vanilla en `static/js/`. **No** React, **no** Tailwind, **no** build step (webpack/vite).
- **Base de datos:** SQLite: `invoicing.db` (principal) y `catalogs/catalogs.db` (catálogos SAT). Migraciones en `migrations/*.sql` + lógica Python en `migrations_runner.py`.
- **SAT:** Scripts PHP en `sat_sync/` (Composer, phpcfdi/sat-ws-descarga-masiva). La app Python los llama con `subprocess` (ej. `check_fiel.php` para validar FIEL). Sync masivo vía cron o `scripts/sat_worker.py`.
- **Pagos:** Stripe (billing). Opcional.

---

## 3. Estructura de la app (resumen)

- **Entrada:** `app.py` (FastAPI). Arranque: `uvicorn app:app --reload` o `./run_server.sh`.
- **Config:** `config.py` lee `.env` (dotenv). Clave: `ENV`, `DEV_MODE`, `SESSION_SECRET`, `DB_PATH`, `SITE_URL`.
- **Routers:** `routers/auth.py` (login, signup, onboarding), `routers/portal.py` (HTML del portal), `routers/api.py` (JSON), `routers/invoicing.py` (formulario factura, descargas), `routers/admin.py`, `routers/public.py`, `routers/billing.py`.
- **Autenticación en portal/API:** `routers/deps.py` → `get_portal_issuer(request)`. Resuelve identidad por cookie `portal_session` o por `?token=`. Sin cookie válida: HTML → redirect `/login`; API → 401.
- **Servicios:** `services/session.py`, `issuers.py`, `users.py`, `csrf.py`, `subscription.py`, `pdf_to_excel.py`, `bank_*`, etc. Llaman a `database.db()`, `db_rows()`, `db_execute()`.
- **DB:** `database.py` expone `db()` (conexión con row_factory dict), `db_rows(sql, params)`, `db_execute(sql, params)`. SQL **siempre con parámetros**; nombres de tabla/columna nunca desde entrada de usuario.

Flujo: **Request → Middleware (request_id, security headers, redirect token) → Ruta → get_portal_issuer → Router → Servicios → DB → HTML/JSON/File.**

---

## 4. Frontend (Jinja / CSS / JS)

- **Base:** `templates/base_portal.html`: meta CSRF, estilos (form.css, portal_tokens.css, components.css, portal.css), sidebar, topbar, breadcrumbs, menú usuario, `{% block content %}`.
- **Páginas:** Extienden `base_portal.html`; el backend pasa `template_name` (siempre literal), `issuer`, `active_page`, `title`, `csrf_token`, etc. vía `_render_portal()` en `portal.py`.
- **CSS:** Tokens en `portal_tokens.css`; componentes en `components.css`; layout en `portal.css`. No añadir frameworks; no abusar de `!important`.
- **JS:** `ui.js` (toasts, loading, skeleton), `catalog-cache.js`. Errores de fetch no deben dejar pantalla en blanco: mostrar bloque “No se pudo cargar” + Reintentar.
- **Accesibilidad:** ARIA en menús y drawer, `:focus-visible`, `prefers-reduced-motion` (ver `docs/ACCESSIBILITY.md`, `docs/MOTION.md`).

---

## 5. Reglas que no se tocan

- **No** cambiar lógica contable ni cálculos ni queries de SAT/CFDI.
- **No** introducir React, Tailwind ni build steps.
- Cambios **incrementales**, con commits claros y forma de validar (smoke test o test manual).
- Prioridad: **no romper** y **claridad** antes que refactors grandes.

---

## 6. Auditoría y docs recientes

Se hizo una auditoría de arquitectura, seguridad, frontend y mantenibilidad. Los entregables están en `docs/`:

| Documento | Contenido |
|-----------|-----------|
| **docs/AUDIT_REPORT.md** | Hallazgos en formato tabla: severidad, evidencia, fix propuesto, riesgo de regresión. Incluye: pantallas blancas, 500, SQL, uploads, timeouts, logging, multi-tenant, CSRF, deuda técnica. Plan de implementación por prioridad. |
| **docs/ARCHITECTURE.md** | Mapa de entrada, flujo HTTP, routers, servicios, DB (invoicing + catalogs), integración SAT (PHP, cron, sat_worker), assets, rutas públicas. |
| **docs/FRONTEND_GUIDE.md** | Convenciones Jinja (bloques, includes, active_page), CSS (tokens, capas), JS, accesibilidad, CSRF, cómo editar sin romper. |
| **docs/SMOKE_TESTS.md** | Pasos manuales (Inicio, Facturas, Movimientos, Bancos, Resumen) y uso de scripts de smoke. |

**Scripts de verificación:**

- `scripts/smoke.sh` — curl a `/health`, `/ready`, `/`, `/login`, `/signup`, `/portal/home`, etc. Opción `START_SERVER=1` para levantar uvicorn.
- `scripts/smoke_portal.sh` — Llama a `smoke.sh` y comprueba que `/login` devuelva HTML con contenido (no pantalla blanca).
- `scripts/smoke_selfserve.py` — Con `PORTAL_SMOKE_TOKEN`: login con token, GET /portal/home, /api/customers, /api/products, crear cliente/producto y comprobar que aparecen.

**Tests mínimos:**

- `tests/test_import.py` — Import de `config` y `app`, existencia de ruta `/health`. Ejecutar: `python -m tests.test_import` o `pytest tests/test_import.py`.

---

## 7. Estado actual (resumen)

- **Errores 500:** Hay handler global en `app.py`; devuelve HTML o JSON según Accept, sin stack al cliente. Log con `logging.exception`.
- **404:** Handler que devuelve página amigable o JSON para `/api/`.
- **Seguridad:** Sesión por cookie HMAC; CSRF en formularios sensibles; SQL parametrizado; uploads con límite de tamaño y `safe_join` para paths; subprocess con timeout en check_fiel y admin.
- **Config al arranque:** En prod se valida SESSION_SECRET, SITE_URL, PHP (si SAT), storage escribible; si falla, la app no arranca.
- **Deuda conocida:** Scripts `db_migrate_*.py` en raíz vs migraciones oficiales en `migrations/` (evitar dos fuentes de verdad). Mejoras menores: empty states unificados, test de aislamiento tenant para descargas.

---

## 8. Documentación reciente (hardening)

- **docs/CHANGELOG_HARDENING.md** — Fases aplicadas (CSRF API, whitelist catálogos, migraciones, subprocess, log sanitize, test tenant).
- **docs/DEVELOPER_QUICKSTART.md** — Arranque, migraciones, smoke tests, tests de aislamiento.

---

## 9. Cómo usar este contexto

- Para **preguntas de arquitectura o flujo:** usa `docs/ARCHITECTURE.md` y este README.
- Para **cambios en templates/CSS/JS:** sigue `docs/FRONTEND_GUIDE.md` y no introduzcas frameworks.
- Para **riesgos y mejoras:** consulta `docs/AUDIT_REPORT.md` y aplica fixes en el orden indicado (observabilidad → seguridad → mantenibilidad → UX).
- Para **probar que no se rompe nada:** ejecuta `./scripts/smoke_portal.sh` o `python -m tests.test_import` y los pasos de `docs/SMOKE_TESTS.md`.

Si propones código, mantén el estilo existente (español en comentarios y mensajes, snake_case en Python, BEM-like en CSS) y no cambies comportamiento contable ni SAT.

# Changelog — Hardening (mejoras totales)

Resumen de fases aplicadas: seguridad, mantenibilidad, robustez. Validación después de cada fase: `./scripts/smoke_portal.sh`, `python -m tests.test_import`.

---

## Fase 1 — CSRF para mutaciones /api/* (H1)

- **Qué cambió:** Los endpoints POST de la API que modifican datos (customers/create, customers/delete, products/create, products/delete, invoices/quick, quotations/create, quotations/update-status, providers/create) exigen el header `X-CSRF-Token` válido. Si falta o es incorrecto → 403 JSON.
- **Dónde:** `services/csrf.py` → `verify_api_csrf(request)`; `routers/api.py` → llamada al inicio de cada endpoint mutador; `static/js/ui.js` → `portalFetchWithTimeout` y `portalFetchJSON` añaden automáticamente `X-CSRF-Token` desde `<meta name="csrf-token">` en peticiones POST/PUT/PATCH/DELETE a `/api/*`.
- **Validar:** Login en portal, crear cliente/producto desde la UI; sin token (ej. curl POST sin header) → 403.

---

## Fase 2 — Whitelist tablas catálogos (M1)

- **Qué cambió:** `database.list_catalog(table)` y `search_catalog(table, ...)` validan `table` contra `ALLOWED_CATALOG_TABLES`. Si el nombre no está permitido → `ValueError`; la API devuelve 400 "Invalid catalog table".
- **Dónde:** `database.py` → `ALLOWED_CATALOG_TABLES`, `_check_catalog_table()`, llamada al inicio de `list_catalog` y `search_catalog`; `routers/api.py` → `except ValueError` → HTTP 400 en endpoints de catálogos; `docs/ARCHITECTURE.md` actualizado.
- **Validar:** Los catálogos del portal (forma pago, uso CFDI, prodserv, unidad) siguen respondiendo 200; no se pasa nunca `table` desde input de usuario.

---

## Fase 3 — Una sola fuente de migraciones (M3)

- **Qué cambió:** Documentación clara: solo `migrations/*.sql` + `migrations_runner.py` son la fuente de verdad. Scripts en `scripts/legacy/` con README que advierte "No ejecutar en producción".
- **Dónde:** `docs/MIGRATIONS.md` (flujo oficial y validación); `scripts/legacy/README.md` con WARNING.
- **Validar:** Arrancar app y comprobar que migraciones se aplican; no ejecutar scripts legacy.

---

## Fase 4 — Wrapper subprocess + timeouts (M4)

- **Qué cambió:** Creado `services/subprocess_safe.py` con `run_cmd()` y `run_php()` que exigen timeout. `_run_fiel_validation` en portal usa `run_php()`. Script `scripts/find_subprocess_without_timeout.py` para auditar que no queden llamadas sin timeout.
- **Dónde:** `services/subprocess_safe.py`; `routers/portal.py` → uso de `run_php` para check_fiel; `scripts/find_subprocess_without_timeout.py`.
- **Validar:** `python scripts/find_subprocess_without_timeout.py` → OK; validar FIEL en portal sigue funcionando.

---

## Fase 5 — Log sanitize (M2)

- **Qué cambió:** Creado `utils/log_sanitize.py` con `mask_token()`, `mask_email()`, `mask_rfc()` para usar en logs cuando se referencien datos sensibles. Documentación en `docs/AUDIT_REPORT.md` (qué se loguea y qué no).
- **Dónde:** `utils/log_sanitize.py`; `docs/AUDIT_REPORT.md` → sección "Logging y datos sensibles".
- **Validar:** Revisar que en nuevos logs no se vuelquen tokens completos ni emails/RFC en claro; usar los helpers donde aplique.

---

## Fase 6 — Test aislamiento tenant descargas

- **Qué cambió:** Añadido `tests/test_tenant_isolation_downloads.py` (pytest) y `tests/helpers.py` con `make_session_cookie()`. El script existente `scripts/test_tenant_downloads.py` ya cubre el mismo flujo (A no puede descargar UUID de B).
- **Dónde:** `tests/test_tenant_isolation_downloads.py`, `tests/helpers.py`.
- **Validar:** `SESSION_SECRET=test python scripts/test_tenant_downloads.py` → OK; o `pytest tests/test_tenant_isolation_downloads.py` si pytest está instalado.

---

## Fase 7 — Frontend: error/empty states unificados (no pantalla blanca)

- **Qué cambió:** Componentes reutilizables en `templates/components/empty_state.html` y `templates/components/error_state.html`. Helper JS `portalShowLoadError(idPrefix, message, onRetry)` y `portalHideLoadError(idPrefix)` en `static/js/ui.js` para mostrar/ocultar el bloque "No se pudo cargar" y enlazar el botón Reintentar. Las listas que ya usan `portal_load_error` siguen funcionando; las nuevas pueden usar el helper o incluir `components/error_state.html`.
- **Dónde:** `templates/components/empty_state.html`, `templates/components/error_state.html`; `static/js/ui.js`.
- **Validar:** Cargar una lista del portal (emitidas, recibidas, etc.); en caso de error de red o 5xx, debe verse el bloque de error y Reintentar, no pantalla en blanco.

---

## Fase 8 — Smoke tests más completos

- **Qué cambió:** `scripts/smoke_portal.sh` ahora hace GET a `/portal/invoices/issued`, `/portal/invoices/received`, `/portal/convertir-edo-cuenta`, `/portal/summary`. Si la respuesta es 200, comprueba que el cuerpo no esté vacío y que contenga algún marcador HTML (`<title`, `<html`, `csrf-token` o `portal`). Cualquier 500 en estas rutas hace fallar el smoke. `docs/SMOKE_TESTS.md` actualizado con la lista de rutas y criterios.
- **Dónde:** `scripts/smoke_portal.sh`, `docs/SMOKE_TESTS.md`.
- **Validar:** `./scripts/smoke_portal.sh` debe pasar con el servidor corriendo.

---

## Fases no aplicadas

- **Fase 9 — Dividir routers/portal.py:** Refactor opcional por dominios (portal_home, portal_invoices, etc.). No aplicado para evitar riesgo de regresión.

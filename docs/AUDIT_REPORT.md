# Informe de auditoría — ContaNeta (Portal contable/fiscal)

**Alcance:** Backend (arquitectura, seguridad, DB, errores), frontend (Jinja/CSS/JS), mantenibilidad, performance, confiabilidad.  
**Reglas:** Sin frameworks nuevos; no cambiar lógica contable/SAT; cambios incrementales con validación.

---

## 1. Resumen ejecutivo

- **Backend:** Arquitectura clara (FastAPI → routers → deps → servicios → DB). Manejo global de errores 404/500/HTTPException ya implementado; logging con request_id; validación de ENV al arranque. SQL parametrizado; uploads con límite de tamaño y `safe_join` para paths.
- **Riesgos identificados:** Principalmente mantenibilidad (duplicación, dos fuentes de verdad en migraciones), algún subprocess sin timeout en scripts, y mejoras menores en frontend (empty states, accesibilidad).
- **Prioridad de fixes:** Observabilidad > Seguridad (uploads/SQL ya razonables) > Mantenibilidad > Performance UX.

---

## 2. Hallazgos (formato: Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo de regresión)

### 2.1 Pantallas blancas / TemplateNotFound

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| Si un template no existe, Jinja lanza y el handler 500 devuelve HTML genérico (no pantalla blanca). | Low | `app.py`: `server_error_handler` retorna `_html_error(500, ...)` según Accept. | Ninguno crítico. Opcional: lista blanca de nombres de template en `_render_portal` para evitar futuros nombres dinámicos erróneos. | Bajo |

**Conclusión:** No hay riesgo actual de pantalla blanca por TemplateNotFound; todos los `template_name` en portal/auth/admin/public/invoicing son literales.

---

### 2.2 Excepciones sin manejo (500 silenciosos)

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| Excepciones no capturadas se loguean y se responde 500 con mensaje genérico. | Med | `app.py` línea 161: `logging.exception("Unhandled error: %s", exc)`. | Mantener; opcional: en prod no incluir stack en respuesta (ya no se incluye). Revisar que ningún router haga `except Exception: pass` sin log. | Bajo |
| Algunos endpoints de portal hacen `except Exception: logger.exception(...); raise` — correcto. | — | `routers/portal.py` p.ej. `_portal_quotations_impl`. | Sin cambio. | — |

---

### 2.3 Variables de entorno / paths

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| Validación al arranque en prod: SESSION_SECRET, SITE_URL, PHP (SAT), storage escribible. | — | `app.py` `_startup_config_check()`. | Ya implementado. Documentar en DEPLOY_GUIDE/README. | Nulo |
| DB_PATH y STATIC_DIR desde config; no hardcodeados en routers. | — | `config.py`, `app.py`. | Sin cambio. | — |

---

### 2.4 SQL e inyección

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| Consultas de negocio usan parámetros (`?`, `params`). | — | `database.db_rows`, `db_execute`; routers pasan tuplas. | Sin cambio. | — |
| Nombres de tabla/columna en f-string solo donde son constantes o listas fijas (PRAGMA, ALTER con lista fija). | Low | `database.py`: `has_column(conn, table, col)` — table/col desde código. `portal.py`: `_ensure_sat_credentials_validation_columns` usa lista fija. | No pasar nunca entrada de usuario como nombre de tabla/columna; documentar en guía de desarrollo. | Bajo |
| `database.search_catalog(table, q, limit)`: `q` va en params (LIKE), `table` desde api con valores fijos. | — | `database.py` líneas 124–139. | Sin cambio. | — |

---

### 2.5 Uploads (PDF / FIEL)

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| PDF bancarios: límite 15MB por archivo, 50MB total multi; content-type; extensión .pdf. | — | `routers/portal.py` MAX_BANK_PDF_SIZE, MAX_BANK_PDF_TOTAL_SIZE, validación content_type. | Sin cambio. | — |
| Rutas de guardado con `safe_join(storage_root, pdf_rel_path)`; nombre de archivo generado en servidor (timestamp + hash). | — | `services/pdf_to_excel.safe_join`, `portal.py` uploads bank. | Sin cambio. | — |
| FIEL: .cer/.key; tamaño máximo 2MB por archivo. | — | `portal.py` MAX_FIEL_SIZE, validación extensiones. | Opcional: sanitizar nombre de archivo en logs (no guardar nombre original en path). | Bajo |

---

### 2.6 Subprocess y timeouts

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| check_fiel.php desde portal con timeout=30. | — | `routers/portal.py` `_run_fiel_validation`. | Sin cambio. | — |
| admin: subprocess.run con timeout=60 y 120. | — | `routers/admin.py`. | Sin cambio. | — |
| sat_worker.py: subprocess con timeout=600. | — | `scripts/sat_worker.py`. | Sin cambio. | — |
| Cualquier otro `subprocess.run` sin timeout en scripts. | Low | `scripts/audit_coverage.py` detecta patrones. | Revisar scripts que invoquen PHP/shell y añadir timeout. | Bajo |

---

### 2.7 Logging

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| request_id en middleware; log record factory con request_id. | — | `app.py` request_id_middleware, _configure_logging. | Sin cambio. | — |
| LOG_FILE opcional; LOG_REQUEST_ID=1 por defecto. | — | `app.py`. | Documentar en .env.example. | Nulo |

---

### 2.8 Multi-tenant / issuer_id

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| issuer siempre desde `get_portal_issuer` (cookie/token); no desde query. Descargas filtran por issuer_id. | — | `routers/deps.py`, rutas /download y listados. | Añadir test manual o automatizado: usuario A no puede acceder a recurso de B (UUID). | Bajo |

---

### 2.9 Auth y CSRF

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| Formularios sensibles usan csrf_token y verify_csrf_token. | — | `services/csrf.py`, routers auth/portal/admin. | Revisar que todo POST que modifique estado tenga CSRF (checklist en FRONTEND_GUIDE). | Bajo |
| Rate limit en login, registro, forgot, reset, FIEL upload. | — | `routers/auth.py`, `services/rate_limit`. | Sin cambio. | — |

---

### 2.10 Mantenibilidad y deuda técnica

| Hallazgo | Severidad | Evidencia | Fix propuesto | Riesgo regresión |
|----------|-----------|-----------|----------------|------------------|
| Scripts db_migrate_*.py en raíz vs migrations/*.sql + migrations_runner. | Med | Varios db_migrate_* en raíz; schema oficial en migrations/. | Mover lógica pendiente a migraciones numeradas; marcar scripts raíz como obsoletos o eliminarlos. | Medio (requiere pruebas de migración) |
| Duplicación de contexto de portal (issuer, active_page, csrf_token, etc.) en cada ruta. | Low | `_render_portal` centraliza; pero cada ruta construye extra a mano. | Extraer helpers por sección (ej. contexto_listado_emitidas) para reducir repetición. | Bajo |
| Dos bases: invoicing.db y catalogs.db; database.py con db() y db_catalogs(). | — | `config.py`, `database.py`. | Documentar en ARCHITECTURE.md. | Nulo |

---

## 3. Frontend (resumen; detalle en FRONTEND_GUIDE.md)

- **Templates:** base_portal.html con blocks e includes; template_name en rutas siempre literal → sin riesgo TemplateNotFound.
- **CSS:** Tokens en portal_tokens.css; componentes en components.css; portal.css y form.css. Evitar !important nuevo; preferir variables.
- **JS:** ui.js (toasts, loading, skeleton); catalog-cache.js. Asegurar que errores de fetch no rompan UI (empty state + Reintentar).
- **Accesibilidad:** aria-label en botones/iconos; focus-visible; prefers-reduced-motion (docs/ACCESSIBILITY.md, MOTION.md).

---

## 4. Plan de implementación sugerido (orden de menor riesgo)

1. **Observabilidad:** Confirmar que no haya `except Exception: pass` sin log; documentar LOG_FILE y request_id en .env.example.
2. **Seguridad:** Revisar que todos los POST de estado tengan CSRF; añadir test de aislamiento tenant (descarga por UUID).
3. **Mantenibilidad:** docs/ARCHITECTURE.md y docs/FRONTEND_GUIDE.md; deprecar db_migrate_*.py de raíz con comentario o migración única.
4. **Performance UX:** CSS sin cambios de lógica; skeletons/empty states donde falten; JS defer donde aplique.
5. **Smoke tests:** scripts/smoke_portal.sh y docs/SMOKE_TESTS.md (Fase 5).

---

## 5. Logging y datos sensibles

- **Qué se loguea:** request_id, issuer_id (numérico), rutas, códigos de estado, mensajes de error genéricos. No se debe loguear en INFO: token completo, contraseña, RFC o email en claro.
- **Helpers:** `utils/log_sanitize.py` expone `mask_token()`, `mask_email()`, `mask_rfc()` para usar en logs cuando se deba referenciar un valor sensible (ej. fallo de login: loguear `mask_email(email)` en lugar del email completo).
- **Trazas principales:** request_id y issuer_id son suficientes para correlacionar; evitar volcar payloads completos con datos personales.

---

## 6. Referencias

- `app.py`: exception handlers, middleware, startup.
- `config.py`: ENV, SESSION_SECRET, DB_PATH, SITE_URL.
- `routers/deps.py`: get_portal_issuer.
- `routers/portal.py`: _render_portal, uploads, safe_join.
- `database.py`: db(), db_rows, db_execute, safe_join en services/pdf_to_excel.
- `AUDIT_REPORT.md` (raíz del proyecto): auditoría previa más extensa de producto y UX.

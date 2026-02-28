# Resume Status — 2026-02-27

## Git Log (últimos 10 commits)

```
8f5e273 feat: bank accounts screen and own-transfer filter
f00c9f8 feat: add matching service facade
07a4702 a11y: add aria-labels to icon actions
111115b ops: add minimal error observability
0e191a2 security: harden file routes and upload validation
6cad76f test: add minimal core suite
03824ed perf: cap list pagination params
7ddb58b refactor: centralize Facturapi invoice payload building
f5ff346 chore: add local check_all script
3512530 test: stabilize tenant isolation fixtures
```

## Working Tree (archivos sin commit)

### Modificados (M)

| Archivo | Cambios |
|---------|---------|
| app.py | Startup: migrations + config validation |
| migrations_runner.py | +90 líneas (lógica robusta) |
| routers/admin.py | +324 líneas (jobs, errors, issuer meta) |
| routers/api.py | +98 líneas (notifications, matching) |
| routers/portal.py | +377 líneas (month-close, matching, notifications) |
| routers/deps.py | +6 (helpers) |
| routers/auth.py | +2 |
| routers/billing.py | +21 (webhook improvements) |
| routers/public.py | +6 |
| services/bank_cfdi_matching.py | +240 líneas (scoring + suggest/confirm/reject) |
| services/error_events.py | +132 líneas (log + list + detail) |
| services/jobs.py | +323 líneas (robust queue, dedupe, lease) |
| services/tenant.py | +22 |
| templates/ (6 archivos) | UI updates: admin dashboard, portal home, bank, received |
| sat_sync/ (4 archivos) | PHP hardening |
| scripts/ (3 archivos) | check_all, backup, sat_worker improvements |
| requirements.txt | +1 dep (cryptography) |

### Nuevos (sin trackear)

| Archivo | Propósito |
|---------|-----------|
| CLAUDE.md | Instrucciones para Claude Code |
| docs/LOCAL_DEV.md | Guía dev local |
| migrations/025_jobs_robust.sql | Schema para job queue robusta |
| migrations/026_month_close_status.sql | Schema cierre mensual |
| migrations/027_notifications.sql | Schema notificaciones |
| migrations/028_admin_issuer_meta.sql | Schema metadata admin por issuer |
| worker.py | Worker de jobs (loop/once) |
| services/invoices_engine.py | Facade sobre invoices_service |
| services/month_close.py | Cierre mensual (status, PDF storage) |
| services/notifications.py | Notificaciones idempotentes + refresh |
| services/admin_issuer.py | Metadata admin por issuer |
| services/crypto_at_rest.py | AES-GCM encryption at rest |
| services/sat_credentials_secure.py | FIEL encrypted storage + context manager |
| scripts/run_php_with_fiel.py | Helper para ejecutar PHP con FIEL |
| templates/admin_jobs.html | Dashboard de jobs |
| templates/admin_job_detail.html | Detalle de job |
| templates/admin_errors.html | Dashboard de errores |
| templates/admin_error_detail.html | Detalle de error |
| templates/portal_month_close.html | Cierre mensual portal |

---

## Feature Status

### COMPLETO

| Feature | Archivos clave |
|---------|---------------|
| Jobs Queue (service) | services/jobs.py, migrations/025 |
| Admin: Jobs Dashboard | routers/admin.py, templates/admin_jobs*.html |
| Admin: Error Events | routers/admin.py, services/error_events.py, templates/admin_error*.html |
| Portal: Month Close | routers/portal.py, services/month_close.py, templates/portal_month_close.html |
| Portal: Notifications | services/notifications.py, routers/portal.py (home widget) |
| Bank Matching (suggest/confirm/reject) | services/bank_cfdi_matching.py, routers/portal.py |
| Crypto at Rest | services/crypto_at_rest.py |
| SAT Credentials Secure | services/sat_credentials_secure.py |
| Billing (Stripe) | routers/billing.py |
| Migrations 025-028 | migrations/ |
| Invoice Engine (facade) | services/invoices_engine.py |

### INCOMPLETO

| Feature | Estado | Qué falta |
|---------|--------|-----------|
| **Admin: Issuer Meta** | ROTO | 1) Syntax error en `admin_issuer.py:62` (falta `)`) — 2) Template `admin_issuer_detail.html` no existe pero la ruta lo referencia |
| **Worker: Job Handlers** | STUB | `_load_handlers()` retorna dict vacío — jobs se encolan pero ninguno se procesa |

### OBSERVACIONES

- Todos los archivos modificados/nuevos están sin commit (2040+ líneas de cambios)
- El código compila excepto `admin_issuer.py` (syntax error)
- El worker es funcional como infraestructura pero sin handlers registrados

# Backlog priorizado — Lanzamiento público + self-serve SAT

**Auditoría ejecutiva (60 min).** Objetivo: backlog accionable para agentes implementadores. Sin cambios de UI/CSS ni refactors grandes; solo lectura y diagnóstico.

**Áreas analizadas:** Self-serve SAT (FIEL, jobs, cron), Auth/sesión, Multi-tenant, UX móvil (390px) y colapsos, Empty states vs errores, Operación (backup, health, migrations, SQLite).

---

## A) Must for public launch (máx 10)

| # | Item | Impacto | Esfuerzo | Riesgo | Cómo verificar |
|---|------|---------|----------|--------|----------------|
| A1 | **ENV=prod + DEV_MODE=0 + ALLOW_DEMO_PORTAL=0 por defecto** | H | S | H | Ya implementado (config.py). Verificar en deploy: `ENV=prod` en .env; sin cookie → redirect /login en portal. |
| A2 | **SESSION_SECRET fijo en producción** | H | S | H | En .env prod debe existir SESSION_SECRET=... (no aleatorio por proceso). Health no debe exponer secretos. |
| A3 | **Aislamiento issuer en descargas XML/PDF** | H | S | H | Revisar que todo GET /download/xml/{uuid} y /download/pdf/{uuid} use `issuer_id` del sesión/token (ya en WHERE issuer_id = ?). Probar con 2 usuarios: A no puede descargar UUID de B. |
| A4 | **FIEL: validación post-upload y mensaje claro** | H | M | M | Tras subir CER/KEY, ejecutar check_fiel.php (o equivalente) y guardar validation_ok/validation_message. Portal debe mostrar “FIEL válida” o mensaje de error legible (no stack trace). |
| A5 | **Sync SAT desde portal solo con FIEL validada** | H | S | M | Ya existe: portal_sat_sync exige validation_ok=1. Verificar que 400 devuelva mensaje “Configura y valida tu FIEL en Ajustes primero.” y que el botón Sync no permita encolar sin FIEL. |
| A6 | **Cron SAT documentado y ejecutable** | H | S | M | cron_sat_sync.sh existe; documentar en DEPLOY/LAUNCH que en prod debe configurarse crontab (ej. */15 * * * *). Verificar que APP_DB_PATH y PHP estén en PATH cuando corre cron. |
| A7 | **Health estable y sin datos sensibles** | M | S | M | GET /health no debe exponer SESSION_SECRET ni rutas internas. Incluir db_readable, migrations_applied, storage_writable. Listo en app.py; revisar que no se añadan secrets. |
| A8 | **Backup DB + storage antes de abrir a usuarios** | H | S | L | LAUNCH_CHECKLIST ya incluye backup_db.sh y backup_storage. Verificar que BACKUP_RETAIN_DAYS esté documentado y que el cron de backup esté en runbook. |
| A9 | **Migrations aplicadas al arranque** | H | S | H | apply_migrations(DB_PATH) en arranque (app.py). /health debe mostrar migrations_applied y migration_version. Probar arranque con DB vacía y con DB ya migrada. |
| A10 | **Rate limit / protección básica en login y FIEL upload** | M | S | M | Revisar que exista rate limit en login (ya en auth) y que FIEL upload tenga _cred_rate_limit (portal.py). Verificar que no se pueda abusar de /portal/sat/validate en bucle. |

---

## B) Should for polish (máx 10)

| # | Item | Impacto | Esfuerzo | Riesgo | Cómo verificar |
|---|------|---------|----------|--------|----------------|
| B1 | **Worker sat_jobs en cron (opcional al cron PHP)** | M | M | L | sat_worker.py procesa sat_jobs; cron_sat_sync.sh usa PHP directo. Documentar que si se usa “Sync” desde portal (cola sat_jobs), un cron debe ejecutar sat_worker.py cada X min. |
| B2 | **Middleware y get_portal_issuer alineados con ALLOW_DEMO_PORTAL** | M | S | M | Middleware (app.py) redirige cuando session_data is None and not DEV_MODE. Con DEV_MODE=1 y ALLOW_DEMO_PORTAL=0, get_portal_issuer hace redirect; comprobar que no haya doble redirect ni fugas a demo. |
| B3 | **Empty states en todas las listas (clientes, productos, proveedores, cotizaciones, emitidas, recibidas)** | M | S | L | Ya hay empty-state en templates; verificar que las APIs devuelvan 200 + [] y que el front no muestre “error” cuando la lista está vacía (solo “No se pudo cargar” cuando res.ok es false). |
| B4 | **Móvil 390px: tablas Clientes/Productos/Proveedores** | M | M | L | MOBILE_CHECKLIST: en 390px puede haber tabla con scroll horizontal en .table-wrap. Opcional: vista en cards para no depender de scroll horizontal. Verificar que no haya scroll horizontal en body. |
| B5 | **Drawer proveedores “Ver facturas”: cierre ESC y focus trap** | M | S | L | Verificar que el drawer tenga overlay, cierre con ESC y que el foco no salga del drawer mientras está abierto (accesibilidad). |
| B6 | **Mensaje único en error de carga (sin toast + bloque)** | M | S | L | Cuando la API falla (4xx/5xx), mostrar solo un bloque “No se pudo cargar” con Reintentar; no duplicar con toast. Revisar JS en listas (emitidas, recibidas, clientes, etc.). |
| B7 | **Logs de auditoría para upload FIEL y sync SAT** | M | S | L | audit.log ya usado en credentials_uploaded y credentials_validated. Verificar que portal_sat_sync (encolar sync) registre acción en audit_log. |
| B8 | **COOKIE_SECURE=1 en producción con HTTPS** | H | S | M | Documentado en .env.example. Verificar que en prod con HTTPS se use COOKIE_SECURE=1 y que session_cookie_params lo respete. |
| B9 | **Paginación y límites en listados API** | M | S | L | Evitar devolver miles de filas (clientes, productos, CFDI). Revisar si hay limit/offset en APIs; si no, añadir límite por defecto (ej. 500) y documentar. |
| B10 | **Página /status o /health legible para soporte** | L | S | L | GET /status ya devuelve HTML con estado. Verificar que sea accesible sin auth y que no filtre información útil para diagnóstico (versión migración, storage). |

---

## C) Later (máx 10)

| # | Item | Impacto | Esfuerzo | Riesgo | Cómo verificar |
|---|------|---------|----------|--------|----------------|
| C1 | **SQLite WAL y busy_timeout en todos los accesos** | M | M | M | migrations_runner y sat_worker usan busy_timeout y WAL. Revisar que database.py (o el módulo db usado por routers) use PRAGMA busy_timeout y journal_mode=WAL para reducir locks. |
| C2 | **Reintentos y timeout en sync SAT (PHP)** | M | M | L | cron_sat_sync.sh usa run_timeout; sync.php puede quedarse colgado ante SAT lento. Documentar tiempos típicos y considerar reintentos en verify_requests. |
| C3 | **Vista móvil en cards para Clientes/Productos/Proveedores** | L | L | L | Opcional: en 390px mostrar lista en cards en lugar de tabla con scroll horizontal. Ver MOBILE_CHECKLIST item 13. |
| C4 | **Alertas cuando sat_requests quedan en error** | L | M | L | Si muchos requests en status=error, notificar o mostrar en portal “Problemas con sincronización SAT”. Requiere definir umbral y canal (email, banner). |
| C5 | **Separar SESSION_SECRET por entorno (dev vs prod)** | L | S | L | Evitar usar el mismo secret en dev y prod. Ya se resuelve con .env distinto; documentar en DEPLOY. |
| C6 | **Backup de storage con compresión por defecto** | L | S | L | BACKUP_STORAGE_ZIP=1 en scripts; documentar en OPS_RUNBOOK y en cron de ejemplo. |
| C7 | **Tests E2E de flujo registro → login → portal → descarga** | M | L | L | smoke_onboarding.py y smoke.sh existen; ampliar con paso “descargar XML” y “sync SAT” (mock o con FIEL de prueba). |
| C8 | **Dashboard admin: conteo de sat_jobs en error** | L | M | L | Panel admin podría mostrar cola sat_jobs (queued, running, error) para soporte. |
| C9 | **Retenciones en sat_cfdi y métricas IVA** | M | M | L | CRON_Y_ERRORES: retenciones se extraen con parse_xml; si hay XMLs viejos sin parsear, re-ejecutar parse_xml --force. Verificar que métricas “IVA recibido (neto)” resten retenciones. |
| C10 | **Documentar flujo self-serve: registro → FIEL → sync → facturas** | M | S | L | Un solo doc (ej. SELF_SERVE_SAT.md) con pasos: 1) Registro, 2) Ajustes → subir FIEL y validar, 3) Emitidas/Recibidas → Sync SAT, 4) Ver listado. Enlazar desde README. |

---

## TOP 5 riesgos que pueden explotar con clientes + mitigación rápida

| Riesgo | Descripción | Mitigación rápida |
|--------|-------------|-------------------|
| **R1** | **Caída a demo en producción** (usuario sin sesión ve datos de otro) | Ya mitigado: ALLOW_DEMO_PORTAL=0 por defecto; sin cookie → redirect /login. En checklist de deploy verificar ENV=prod y que no se defina ALLOW_DEMO_PORTAL=1. |
| **R2** | **Fuga de datos entre tenants** (issuer A ve XML/PDF de issuer B) | Todas las descargas ya filtran por issuer_id (invoicing.py). Revisar cualquier endpoint que devuelva sat_cfdi, customer_profiles, quotations por issuer_id de sesión. Auditoría rápida: grep “issuer_id” en SELECT de APIs. |
| **R3** | **Sesión inválida o secret débil** (sesiones predecibles o rotas) | SESSION_SECRET obligatorio en prod (valor fijo 32+ bytes). COOKIE_SECURE=1 con HTTPS. No usar secret por defecto (secrets.token_hex en cada proceso) en producción. |
| **R4** | **SAT sync bloquea o falla en silencio** (cron no configurado o PHP no encontrado) | Documentar en runbook: crontab con ruta absoluta a cron_sat_sync.sh; PHP en PATH o variable; log a archivo (ej. /tmp/sat_sync.log). Añadir en health (opcional) un indicador “último sync exitoso” por issuer. |
| **R5** | **SQLite locked / timeouts bajo carga** | Usar WAL y busy_timeout (5000 ms) en todas las conexiones. Limitar workers (gunicorn -w 2 o 4). Backups con cp o sqlite3 .backup para no bloquear escrituras. Ver AUDITORIA_SQLITE_DIAGNOSTICO.md. |

---

## Resumen por área

- **Self-serve SAT:** FIEL upload/validate y sync desde portal están; falta asegurar validación post-upload clara (A4), cron documentado (A6) y opcionalmente worker sat_jobs (B1).
- **Auth/sesión:** Default seguro (A1, A2), redirect /login sin demo (A1), COOKIE_SECURE (B8). Middleware y deps alineados (B2).
- **Multi-tenant:** issuer_id en APIs y descargas (A3); revisar ningún SELECT sin filtrar por issuer.
- **UX móvil:** Empty states y “No se pudo cargar” (B3, B6); drawer y tablas en 390px (B4, B5). MOBILE_CHECKLIST y UX_AUDIT ya referencian estado.
- **Operación:** Health (A7), backups (A8), migrations (A9), rate limit (A10). WAL/busy_timeout (C1) para más adelante.

**Prioridad para self-serve y demo móvil estable:** A1–A6 y B2–B3, B6; R1–R3 mitigados primero.

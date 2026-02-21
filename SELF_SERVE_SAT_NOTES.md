# Notas finales — Self-serve SAT (FIEL/CSD) + Sync autónomo

Resumen de lo implementado y qué faltaría para producción real.

---

## Qué se implementó

### Base de datos
- **Migración 014:** columnas `validation_at`, `validation_ok`, `validation_message` en `sat_credentials` (idempotente vía `migrations_runner`). La app ya las usaba en tiempo de ejecución; la migración las deja fijas en el esquema.

### PHP y rutas
- **check_fiel.php** y **sync.php** usan `APP_DB_PATH` del entorno cuando está definido; si no, se usa `invoicing.db` en la raíz del proyecto. Así el cron/worker puede apuntar a la misma DB que la app.

### Página “Conectar SAT” (/portal/config/sat)
- Dropzones para .cer y .key, campo contraseña, botón “Guardar y validar”.
- Panel Estado: Configurado / No configurado; FIEL válida ✓ o Error con mensaje; “Última validación” con fecha; botones “Validar de nuevo” y “Reemplazar archivos”.

### Upload y seguridad
- Validación de extensión (.cer, .key) y tamaño (máx. 2 MB por archivo).
- Guardado en `storage/credentials/{issuer_id}/` con `chmod 0600` para los archivos.
- Rutas construidas en servidor (sin path traversal); contraseña guardada en DB (sin cifrado adicional documentado).

### Validación real
- Tras guardar credenciales se ejecuta `check_fiel.php` (e.firma vigente).
- Se persisten `validation_ok`, `validation_message` y `validation_at` en `sat_credentials`.
- Endpoint `POST /portal/config/sat/validate` reejecuta la validación y devuelve JSON para la UI.

### Sync “solo” (jobs + worker)
- **POST /portal/sat/sync:** solo permite encolar si `validation_ok = 1`; crea dos jobs en `sat_jobs` (issued y received).
- **scripts/sat_worker.py:** toma jobs `queued`, los marca `running`, ejecuta `php sat_sync/sync.php <issuer_id> <direction>`, actualiza `finished_at` y `last_error` (ok/error).
- **OPS_RUNBOOK.md:** cron recomendado cada 10–15 min para `python3 scripts/sat_worker.py`.

### Estado en la UI
- **Inicio:** bloque “SAT” con “Último sync”, estado (OK / Sincronizando… / Error) y botón “Sync SAT”.
- **Emitidas y Recibidas:** barra compacta con lo mismo (meta, estado, botón “Sync SAT”).
- Polling de `GET /portal/sat/status` cada 8 s cuando hay bloque/barra; al pulsar “Sync SAT” se encola y se actualiza la UI.
- En error se muestra un solo bloque con mensaje y enlace “Ver detalle / Revalidar FIEL”.

### Documentación
- **SELF_SERVE_SAT.md:** guía paso a paso para el usuario final.
- **OPS_RUNBOOK.md:** sección 5 actualizada con worker (sat_worker.py) y cron recomendado.
- **QA_STEPS.md:** sección 12b “Conectar SAT self-serve — 10 min” para QA.

---

## Qué faltaría para producción real

1. **Cifrado de contraseña FIEL:** Hoy se guarda en claro en `sat_credentials.fiel_key_password`. Para producción convendría cifrar en reposo (ej. con una clave derivada de `SESSION_SECRET` o una clave dedicada) y desencriptar solo en el proceso que llama a PHP.

2. **Reintentos en el worker:** El worker no reintenta automáticamente los jobs en `error`. Opción: si `attempts < N` y el error es recuperable (timeout, SAT caído), volver a poner el job en `queued` con `next_retry_at` y que el cron lo recoja más tarde.

3. **Límite de jobs por issuer:** Evitar que un usuario encole muchas veces seguidas (p. ej. máximo 1 par issued+received cada X minutos por issuer). Ya existe comprobación “Ya hay una sincronización en curso”; se podría añadir un cooldown adicional.

4. **Logs y auditoría:** Los scripts PHP y el worker escriben a stdout/stderr; en producción conviene redirigir a archivos rotados y, si aplica, registrar en `audit_log` los eventos de sync (encolado, inicio, fin, error).

5. **Monitoreo:** Alertas si muchos jobs quedan en `error` o si el worker no se ejecuta (p. ej. cron fallido). Incluso un endpoint interno `/ops/sat-jobs` (protegido) para ver cola y últimos errores.

6. **APP_DB_PATH en cron:** Asegurar que el cron que ejecuta `sat_worker.py` tenga `APP_DB_PATH` (y opcionalmente `PHP_BIN`) definidos en el entorno, sobre todo si la DB no está en la raíz del proyecto.

7. **Pruebas automatizadas:** Incluir en CI un test que suba .cer/.key de prueba (o mock) y compruebe que la validación y el encolado de sync responden como se espera, sin depender del SAT real.

Con esto, el flujo self-serve (subir FIEL → validar → Sync SAT desde el portal → worker+cron) queda listo para uso; los puntos anteriores son mejoras de robustez y seguridad para producción.

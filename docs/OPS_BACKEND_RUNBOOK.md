# Runbook operativo — Backend ContaNeta

## Cómo correr la aplicación

```bash
# Desde la raíz del proyecto
cd /ruta/al/proyecto

# Opción 1: uvicorn directo
uvicorn app:app --host 0.0.0.0 --port 8000

# Opción 2: con venv
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000

# Opción 3: variable de entorno para puerto
PORT=8000 uvicorn app:app --host 0.0.0.0 --port $PORT
```

Al arrancar, la app ejecuta **migraciones** (`apply_migrations(DB_PATH)`) y el **chequeo de configuración** (SESSION_SECRET, SITE_URL, PHP, storage). Si algo crítico falla en prod, no arranca.

---

## Dónde están los logs

- **Salida estándar**: por defecto los logs van a stdout (formato con `[request_id]` si `LOG_REQUEST_ID=1`).
- **Archivo**: si defines `LOG_FILE=/ruta/al/app.log`, se añade un `FileHandler` a la raíz del logger.
- **Nivel**: `logging.basicConfig(level=logging.INFO)`. Para debug: `LOG_LEVEL=DEBUG` (si la app lo lee) o cambiar en código.
- Cada request puede identificarse por **X-Request-ID** (cabecera de respuesta). Usa ese ID para buscar en logs.

---

## SAT sync (PHP)

- **Scripts**: `sat_sync/check_fiel.php`, `sync.php`, `sync_xml.php`, `parse_xml.php`, etc.
- **Ejecución**: desde el backend (portal) con `services/subprocess_safe.run_php()`, con **timeout** obligatorio.
- **Variables de entorno** que usa el PHP: `APP_DB_PATH` (ruta a la base SQLite).
- **Cron manual** (si lo tienes): desde la raíz, algo como:
  ```bash
  cd sat_sync && php sync.php
  ```
  Asegúrate de exportar `APP_DB_PATH` si el script lo requiere.

---

## Jobs / workers

- El estado de jobs de SAT vive en tablas como `sat_jobs`, `sat_sync_state` (ver `docs/ARCH_BACKEND_MAP.md`).
- No hay un “job runner” genérico obligatorio: el sync se dispara desde la UI (`POST /portal/sat/sync`) y el backend llama a PHP con timeout.
- Si en el futuro se añade un worker externo, documentar aquí cómo arrancarlo y cómo lee/escribe en la misma DB.

---

## Troubleshooting

### DB locked / database is locked

- SQLite usa **WAL** y **busy_timeout** (p. ej. 5000 ms). Si ves locks:
  - No correr dos procesos que escriban fuerte a la vez (migraciones vs app).
  - Reiniciar la app para liberar conexiones.
  - Revisar que no haya scripts externos (backups, cron) abriendo la DB sin timeout.

### Migraciones fallan al arrancar

- Revisar que `migrations/` exista y que los `.sql` estén bien formados.
- Revisar permisos del archivo de DB (`DB_PATH`): debe ser escribible por el usuario que corre la app.
- Si la DB está corrupta: restaurar desde backup; si es desarrollo, a veces se recrea desde cero aplicando migraciones.

### PHP no encontrado / FIEL falla

- En prod, el chequeo de arranque exige PHP si existe `sat_sync/check_fiel.php`.
- Instalar `php-cli` y asegurar que `php` esté en el PATH del usuario que ejecuta la app.
- Si SAT no se usa: no es necesario PHP; el startup solo avisa.

### Errores 500 en API

- Revisar logs con el **request_id** de la respuesta (cabecera `X-Request-ID`).
- Errores de dominio controlados: `AppError` (código y mensaje en `services/errors.py`).
- DB: `sqlite3.Error` se convierte en 500 con mensaje genérico; el detalle va solo al log.

### Respuestas API inconsistentes

- Las rutas `/api/*` deben usar el contrato `{ "ok": true, "data": ... }` en éxito y `{ "ok": false, "error": { "code", "message" }, "meta": { "request_id" } }` en error (ver `services/http.py` y handlers en `app.py`).

---

## Smoke tests

- **General**: `./scripts/smoke.sh` (health, ready, rutas HTML).
- **API**: `./scripts/smoke_api.sh` (health, status, bootstrap, customers, products, etc.; 401 sin sesión es válido).

```bash
BASE_URL=http://127.0.0.1:8000 ./scripts/smoke_api.sh
```

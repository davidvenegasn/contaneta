# Runbook de operación — Conta Invoicing MVP

Pasos para desplegar, respaldar, restaurar y operar el sistema de forma autónoma (backups, health, worker SAT).

---

## 1. Deploy

### 1.1 Requisitos

- Python 3.10+ con dependencias: `pip install -r requirements.txt`
- SQLite (incluido con Python)
- Para sync SAT: PHP 8+ y Composer en `sat_sync/` (ver sat_sync/README si existe)
- Variables de entorno: ver README (SESSION_SECRET, APP_DB_PATH, etc.)

### 1.2 Primera puesta en marcha

```bash
# Opcional: DB en ruta distinta
export APP_DB_PATH=/var/lib/conta/invoicing.db

# Migraciones se aplican solas al arrancar la app
uvicorn app:app --host 0.0.0.0 --port 8000

# O con gunicorn (producción)
gunicorn app:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### 1.3 Comprobar que todo está bien

- `curl -s http://localhost:8000/health` → `{"status":"ok", "db":"ok", "migrations_applied": true, "storage_exists": true, ...}`
- Abrir `/login` o `/register` y verificar que la app responde.

---

## 2. Backups

### 2.1 Backup de la base de datos

Script: **`scripts/backup_db.sh`**

- Copia `invoicing.db` (o `APP_DB_PATH`) a `backup/invoicing_YYYYMMDD_HHMMSS.db`.
- **Retención:** se eliminan copias más antiguas de `BACKUP_RETAIN_DAYS` días (por defecto 30).

```bash
# Desde la raíz del proyecto
./scripts/backup_db.sh

# Con DB y directorio de backup custom
APP_DB_PATH=/var/lib/conta/invoicing.db BACKUP_DIR=/backups BACKUP_RETAIN_DAYS=14 ./scripts/backup_db.sh
```

### 2.2 Backup del storage (XMLs)

Script: **`scripts/backup_storage_xml.sh`**

- Copia el directorio `storage/` a `backup/storage_YYYYMMDD_HHMMSS` (o `.tar.gz` si `BACKUP_STORAGE_ZIP=1`).
- **Retención:** se eliminan backups de storage más antiguos de `BACKUP_RETAIN_DAYS` días (por defecto 30).

```bash
./scripts/backup_storage_xml.sh

# Comprimir a .tar.gz
BACKUP_STORAGE_ZIP=1 ./scripts/backup_storage_xml.sh
```

### 2.3 Cron recomendado para backups

Ejemplo en crontab (ejecutar como usuario que corre la app):

```cron
# Backup DB todos los días a las 02:00
0 2 * * * cd /ruta/al/proyecto && ./scripts/backup_db.sh >> /var/log/conta_backup_db.log 2>&1

# Backup storage (XMLs) cada 3 días a las 03:00
0 3 */3 * * cd /ruta/al/proyecto && ./scripts/backup_storage_xml.sh >> /var/log/conta_backup_storage.log 2>&1
```

---

## 3. Restore

### 3.1 Restaurar la base de datos

1. Detener la aplicación.
2. Opcional: copia de seguridad del archivo actual por si acaso:  
   `cp invoicing.db invoicing.db.before_restore`
3. Sustituir la DB por la copia del backup:  
   `cp backup/invoicing_YYYYMMDD_HHMMSS.db invoicing.db`  
   (o a la ruta que uses en `APP_DB_PATH`).
4. Si usas WAL: opcional limpiar auxiliares antes de arrancar (ver MIGRATIONS.md):  
   `mv invoicing.db-wal invoicing.db-wal.off 2>/dev/null; mv invoicing.db-shm invoicing.db-shm.off 2>/dev/null`
5. Arrancar la aplicación de nuevo y comprobar `/health`.

### 3.2 Restaurar el storage (XMLs)

1. Detener la aplicación (recomendado si la app escribe en `storage/` mientras tanto).
2. Restaurar desde backup:  
   `cp -a backup/storage_YYYYMMDD_HHMMSS storage`  
   o, si fue comprimido:  
   `tar xzf backup/storage_YYYYMMDD_HHMMSS.tar.gz -C /ruta/al/proyecto`
3. Arrancar la aplicación y comprobar `/health` y que el portal muestre XMLs.

---

## 4. Health check

Endpoint: **`GET /health`** (público, sin auth).

Respuesta esperada cuando todo está bien:

```json
{
  "status": "ok",
  "db": "ok",
  "db_readable": true,
  "migrations_applied": true,
  "migration_version": "011",
  "storage_exists": true,
  "storage_writable": true
}
```

- **status:** `ok` si DB legible y migraciones aplicadas; `degraded` en caso contrario.
- **storage_exists:** el directorio `storage/` existe.
- **storage_writable:** el directorio `backup/` existe y es escribible (para backups).

Uso típico: balanceadores, monitoreo (ping cada X minutos) y alertas si `status != "ok"`.

---

## 5. Worker SAT (sync CFDI)

### 5.1 Self-serve: worker que procesa la cola (recomendado)

Cuando los usuarios pulsan **"Sync SAT"** en el portal, se encolan jobs en la tabla `sat_jobs`. El worker **`scripts/sat_worker.py`** procesa esos jobs (ejecuta `php sat_sync/sync.php <issuer_id> <issued|received>`) y actualiza estado (ok/error, last_error, finished_at).

**Cron recomendado:** ejecutar el worker cada **10–15 minutos** para que la sincronización encolada desde el portal se ejecute sin intervención manual.

```bash
# Ejecutar worker (procesa hasta 20 jobs en cola)
APP_DB_PATH=/ruta/al/invoicing.db python3 scripts/sat_worker.py
```

**Crontab ejemplo (cada 10 min):**

```cron
*/10 * * * * cd /ruta/al/proyecto && APP_DB_PATH=/ruta/al/invoicing.db python3 scripts/sat_worker.py >> /var/log/sat_worker.log 2>&1
```

Requisitos: Python 3, PHP en PATH (o `PHP_BIN`), Composer en `sat_sync/`. Opcional: `SAT_SYNC_BACKFILL_DAYS`, `SAT_SYNC_WINDOW_HOURS` (por defecto 7 y 6).

### 5.2 Sync manual / legacy (todos los issuers)

Comando: **`scripts/run_sat_sync.sh`** (o el script que invoque `sat_sync/sync.php` por issuer).

- Sin argumentos: sincroniza todos los issuers con `sat_credentials`.
- Con argumentos: issuer_id y opcionalmente dirección (`issued`|`received`).

Alternativa: **`sat_sync/cron_sat_sync.sh`** (pipeline completo: metadata, XML, verify, parse, cancelaciones). Úsalo si prefieres un cron que no dependa de la cola del portal.

```cron
# Opcional: cron legacy cada 6 h (sync directo por issuer, sin cola)
0 */6 * * * cd /ruta/al/proyecto && ./scripts/run_sat_sync.sh >> /var/log/sat_sync.log 2>&1
```

---

## 6. Logging

- **Request ID:** cada request tiene un `request_id` (generado o tomado de `X-Request-ID`). Si `LOG_REQUEST_ID=1` (por defecto), los logs incluyen `[request_id]` y la respuesta lleva cabecera `X-Request-ID`.
- **Log a archivo:** si defines `LOG_FILE=/ruta/al/app.log`, los logs se escriben también en ese archivo (encoding UTF-8).
- **Desactivar request_id en logs:** `LOG_REQUEST_ID=0`.

Ejemplo:

```bash
LOG_FILE=/var/log/conta/app.log uvicorn app:app --host 0.0.0.0 --port 8000
```

---

## 7. Resumen rápido

| Tarea           | Comando o endpoint |
|----------------|--------------------|
| Health         | `GET /health`      |
| Backup DB      | `./scripts/backup_db.sh` |
| Backup storage | `./scripts/backup_storage_xml.sh` |
| Sync SAT       | `./scripts/run_sat_sync.sh` |
| Restore DB     | Copiar backup sobre `invoicing.db` y reiniciar app |
| Restore storage| Copiar/extraer backup en `storage/` |

Ver **MIGRATIONS.md** para problemas con WAL/SHM y **README** para variables de entorno y seguridad.

# Runbook de operación — Conta Invoicing

> **Consolidado en [OPERATIONS.md](docs/ops/OPERATIONS.md).** Este archivo se mantiene por referencia; para operar (backup, restore, cron SAT, health, checklist de producción) usa **OPERATIONS.md**.

Guía para **operar** el sistema en producción: desplegar, hacer backups, restaurar y revisar que todo funcione. **Operable por ti aunque no seas programador:** los comandos se pueden copiar y pegar; solo sustituye las rutas indicadas por las de tu servidor.

---

## Índice

1. [Glosario rápido](#1-glosario-rápido)
2. [Deploy (puesta en marcha)](#2-deploy-puesta-en-marcha)
3. [Backups](#3-backups)
4. [Restore (restaurar desde backup)](#4-restore-restaurar-desde-backup)
5. [Health y listo para tráfico](#5-health-y-listo-para-tráfico)
6. [Worker SAT (sincronización CFDI)](#6-worker-sat-sincronización-cfdi)
7. [Logging](#7-logging)
8. [Cron: resumen de tareas programadas](#8-cron-resumen-de-tareas-programadas)
9. [Qué hacer si…](#9-qué-hacer-si)

---

## 1. Glosario rápido

| Término | Significado |
|--------|-------------|
| **Proyecto** | Carpeta donde está instalada la aplicación (ej. `/var/www/conta-invoicing`). |
| **DB / base de datos** | Archivo `invoicing.db` (o la ruta que pongas en `APP_DB_PATH`). Guarda usuarios, empresas, facturas, etc. |
| **Storage** | Carpeta `storage/` del proyecto. Contiene XMLs descargados del SAT y credenciales FIEL. |
| **Backup** | Copia de seguridad. Los scripts guardan en la carpeta `backup/` del proyecto (o en `BACKUP_DIR`). |
| **Health** | Comprobación de que la app y la base de datos responden. Se hace con la URL `/health`. |
| **Retención** | Cuántos días se conservan los backups antiguos; los más viejos se borran automáticamente. |

---

## 2. Deploy (puesta en marcha)

### 2.1 Requisitos

- **Python 3.10 o superior** y dependencias instaladas: `pip install -r requirements.txt`
- **SQLite** (viene con Python)
- **Variables de entorno:** al menos `SESSION_SECRET` y, si aplica, `APP_DB_PATH`. Ver `.env.example` y README.
- Para **sincronización SAT (CFDI):** PHP 8+ y Composer en la carpeta `sat_sync/` (ver documentación de sat_sync si existe).

### 2.2 Arrancar la aplicación

Desde la **raíz del proyecto** (donde está `app.py`):

```bash
# Opcional: indicar dónde está la base de datos
export APP_DB_PATH=/var/lib/conta/invoicing.db

# Arrancar (las migraciones se aplican solas al iniciar)
uvicorn app:app --host 0.0.0.0 --port 8000
```

En producción suele usarse **gunicorn**:

```bash
gunicorn app:app -w 1 --threads 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

Si usas **systemd**, el servicio podría llamarse `conta-invoicing`; en ese caso:

- Arrancar: `sudo systemctl start conta-invoicing`
- Parar: `sudo systemctl stop conta-invoicing`
- Ver estado: `sudo systemctl status conta-invoicing`

### 2.3 Comprobar que está bien

- En el navegador: abrir la URL de la app (ej. `https://tu-dominio.com`) y comprobar que carga login o registro.
- Por línea de comandos:  
  `curl -s http://localhost:8000/health`  
  Debe devolver algo como: `"status":"ok", "db":"ok", "migrations_applied": true`.

---

## 3. Backups

Hay dos tipos de backup: **base de datos** y **storage (XMLs y credenciales)**. Conviene hacer ambos de forma periódica (por ejemplo con cron). Los scripts están en `scripts/`; si al ejecutarlos sale "Permission denied", dales permiso de ejecución: `chmod +x scripts/backup_db.sh scripts/backup_storage_xml.sh scripts/backup_all.sh`.

### 3.1 Backup de la base de datos

**Script:** `scripts/backup_db.sh`

- Copia el archivo de la base de datos a `backup/invoicing_YYYYMMDD_HHMMSS.db`.
- **Retención:** se pueden borrar automáticamente los backups más viejos de X días (configurable; por defecto 30). Si pones `BACKUP_RETAIN_DAYS=0`, no se borra ninguno.

**Ejemplo (desde la raíz del proyecto):**

```bash
./scripts/backup_db.sh
```

**Con rutas y retención personalizadas:**

```bash
APP_DB_PATH=/var/lib/conta/invoicing.db BACKUP_DIR=/backups/conta BACKUP_RETAIN_DAYS=14 ./scripts/backup_db.sh
```

### 3.2 Backup del storage (XMLs y FIEL)

**Script:** `scripts/backup_storage_xml.sh`

- Copia la carpeta `storage/` a `backup/storage_YYYYMMDD_HHMMSS` (o a un `.tar.gz` si se indica).
- **Retención:** igual que la DB, con `BACKUP_RETAIN_DAYS` (default 30). `0` = no borrar backups antiguos.

**Ejemplo:**

```bash
./scripts/backup_storage_xml.sh
```

**Comprimido (recomendado si hay mucho contenido):**

```bash
BACKUP_STORAGE_ZIP=1 ./scripts/backup_storage_xml.sh
```

**Con rutas propias:**

```bash
STORAGE_DIR=/var/app/storage BACKUP_DIR=/backups/conta BACKUP_RETAIN_DAYS=14 ./scripts/backup_storage_xml.sh
```

### 3.3 Backup completo (DB + storage en un solo comando)

**Script:** `scripts/backup_all.sh`

Ejecuta primero el backup de la DB y luego el de storage. Usa las mismas variables de entorno (`APP_DB_PATH`, `BACKUP_DIR`, `BACKUP_RETAIN_DAYS`, etc.). Retención se aplica en cada script.

```bash
./scripts/backup_all.sh
```

### 3.4 Variables de entorno para los scripts de backup

| Variable | Uso | Ejemplo |
|----------|-----|--------|
| `APP_DB_PATH` | Ruta del archivo `.db` | `/var/lib/conta/invoicing.db` |
| `BACKUP_DIR` | Carpeta donde guardar backups | `/backups/conta` |
| `BACKUP_RETAIN_DAYS` | Días de retención (borrar más antiguos). `0` = no borrar | `30` o `14` |
| `STORAGE_DIR` | Carpeta a respaldar (solo storage) | `/var/app/storage` |
| `BACKUP_STORAGE_ZIP` | `1` o `yes` = guardar storage como .tar.gz | `1` |

---

## 4. Restore (restaurar desde backup)

Guía rápida en la raíz del proyecto: **`docs/ops/RESTORE.md`**.  
Pasos detallados (comandos copy-paste): **`scripts/restore.md`**.

En ambos se indica:

- Cómo restaurar **solo la DB**
- Cómo restaurar **solo el storage (XMLs y FIEL)**
- Cómo restaurar **ambos**
- Qué hacer si algo falla (volver al estado anterior, revisar logs)

Resumen en 4 pasos:

1. Detener la aplicación.
2. (Opcional) Guardar una copia del estado actual por si hay que volver atrás.
3. Copiar el archivo o carpeta del backup al lugar donde la app espera la DB o `storage/`.
4. Ajustar permisos si hace falta; arrancar la aplicación y comprobar con `GET /health`.

---

## 5. Health y listo para tráfico

### 5.1 GET /health

- **URL:** `GET /health` (pública, sin contraseña).
- **Uso:** Saber si la app está viva y si la base de datos se puede leer. Sirve para monitoreo y balanceadores.

Respuesta típica cuando todo va bien:

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

- **status:** `ok` si la DB es legible y las migraciones están aplicadas; `degraded` si algo falla.
- **storage_exists:** existe la carpeta `storage/`.
- **storage_writable:** se puede escribir en la carpeta de backups.

**Sin secretos:** Este endpoint **nunca devuelve** contraseñas, `SESSION_SECRET`, rutas internas del servidor ni variables de entorno sensibles. Es seguro usarlo en monitoreo y en URLs públicas.

### 5.2 GET /ready

- **URL:** `GET /ready`
- **Uso:** Para balanceadores o Kubernetes: “¿puedo enviar tráfico a esta instancia?”.
- **200** si está listo (migraciones aplicadas y DB legible); **503** si no.
- **Sin secretos:** Igual que `/health`; solo devuelve `ready` y `migration_version` (o `reason` en 503). Nada sensible.

Ejemplo de comprobación:

```bash
curl -s http://localhost:8000/health
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ready
```

(El segundo debería devolver `200`.)

---

## 6. Worker SAT (sincronización CFDI)

Cuando un usuario pulsa **“Sincronizar SAT”** en el portal, se encola un trabajo. El **worker** es el programa que ejecuta esos trabajos (descarga XMLs del SAT, etc.).

**Script del worker:** `scripts/sat_worker.py`

**Ejecución manual (ejemplo):**

```bash
cd /ruta/al/proyecto
APP_DB_PATH=/ruta/al/invoicing.db python3 scripts/sat_worker.py
```

Para que la sincronización se procese sin intervención, se suele programar este comando cada **10–15 minutos** con cron (ver sección 8).

Requisitos: Python 3, PHP en el PATH (o variable `PHP_BIN`), Composer en `sat_sync/`. Opcional: `SAT_SYNC_BACKFILL_DAYS`, `SAT_SYNC_WINDOW_HOURS`.

**Sync manual (todos los issuers, sin cola):** `scripts/run_sat_sync.sh` (ver comentarios dentro del script o documentación de sat_sync).

---

## 7. Logging

### 7.1 Request ID (seguir una petición en los logs)

Cada petición HTTP tiene un **identificador único** (request_id). Así puedes rastrear una petición concreta desde la cabecera de respuesta hasta los logs.

- **Por defecto:** `LOG_REQUEST_ID=1` (activado). Cada línea de log incluye el request_id al inicio, por ejemplo: `[a1b2c3d4e5f6] INFO ...`
- **Cabecera de respuesta:** La respuesta HTTP incluye `X-Request-ID: <id>`. Si el cliente envía `X-Request-ID`, se reutiliza; si no, el servidor genera uno.
- **Buscar en logs:** Si un usuario reporta un error y te pasan el `X-Request-ID` (o lo ves en el navegador con herramientas de red), puedes filtrar todos los logs de esa petición:

```bash
grep "a1b2c3d4e5f6" /var/log/conta/app.log
```

(Sustituye `a1b2c3d4e5f6` por el valor de `X-Request-ID` y la ruta del archivo de log por la tuya.)

- **Desactivar request_id en logs:** `LOG_REQUEST_ID=0` (no recomendado en producción).

### 7.2 Log a archivo

Si defines `LOG_FILE=/ruta/al/app.log`, los logs se escriben también en ese archivo (UTF-8).

```bash
LOG_FILE=/var/log/conta/app.log uvicorn app:app --host 0.0.0.0 --port 8000
```

En `.env` puedes poner, por ejemplo:

- `LOG_FILE=/var/log/conta/app.log`
- `LOG_REQUEST_ID=0` (solo si no quieres el ID en los logs).

---

## 8. Cron: resumen de tareas programadas

Para que los backups y el worker SAT se ejecuten solos, se usan tareas programadas (cron). Sustituye `/ruta/al/proyecto` y las rutas de DB por las tuyas.

**Abrir crontab del usuario que ejecuta la app:**

```bash
crontab -e
```

**Ejemplo de entradas:**

```cron
# Backup de la base de datos: todos los días a las 02:00
0 2 * * * cd /ruta/al/proyecto && APP_DB_PATH=/ruta/al/invoicing.db ./scripts/backup_db.sh >> /var/log/conta_backup_db.log 2>&1

# Backup del storage (XMLs): cada 3 días a las 03:00
0 3 */3 * * cd /ruta/al/proyecto && ./scripts/backup_storage_xml.sh >> /var/log/conta_backup_storage.log 2>&1

# Worker SAT: cada 10 minutos (procesa la cola de sincronización)
*/10 * * * * cd /ruta/al/proyecto && APP_DB_PATH=/ruta/al/invoicing.db python3 scripts/sat_worker.py >> /var/log/sat_worker.log 2>&1
```

Si quieres **retención de 14 días** en los backups:

```cron
0 2 * * * cd /ruta/al/proyecto && APP_DB_PATH=/ruta/al/invoicing.db BACKUP_RETAIN_DAYS=14 ./scripts/backup_db.sh >> /var/log/conta_backup_db.log 2>&1
```

---

## 9. Qué hacer si…

| Situación | Acción |
|-----------|--------|
| La app no arranca | Revisar logs: `sudo journalctl -u conta-invoicing -n 100` (o el nombre de tu servicio). Comprobar que `APP_DB_PATH` y `SESSION_SECRET` estén definidos (ver `.env.example`). |
| `/health` devuelve `degraded` o `db: error` | La base de datos no se lee. Comprobar que el archivo existe, permisos y que no esté corrupto. Opcional: `APP_DB_PATH=/ruta/invoicing.db python3 scripts/check_db.py`. |
| Tras restaurar la DB la app no inicia | Volver al backup anterior: `mv invoicing.db.before-restore invoicing.db` y reiniciar. Ver **scripts/restore.md**. |
| Los XMLs no se ven en el portal | Comprobar que la carpeta `storage/` existe y tiene permisos correctos. Si acabas de restaurar, ver **scripts/restore.md** (restaurar storage). |
| La sincronización SAT no avanza | Asegurarse de que el worker se ejecuta (cron cada 10 min). Revisar `sat_worker.log` y que PHP y Composer estén instalados para `sat_sync/`. |
| Quiero guardar backups para siempre | Usar `BACKUP_RETAIN_DAYS=0` en los scripts de backup (no se borrarán copias antiguas). |

---

## Resumen rápido

| Tarea | Comando o URL |
|-------|----------------|
| ¿Está viva la app? | `GET /health` (sin secretos) |
| ¿Puedo enviar tráfico? | `GET /ready` (sin secretos) |
| Backup base de datos | `./scripts/backup_db.sh` (retención: `BACKUP_RETAIN_DAYS`) |
| Backup storage (XMLs) | `./scripts/backup_storage_xml.sh` (retención: `BACKUP_RETAIN_DAYS`) |
| Backup completo (DB + storage) | `./scripts/backup_all.sh` |
| Restaurar DB o storage | **docs/ops/RESTORE.md** y **scripts/restore.md** |
| Seguir una petición en logs | Cabecera `X-Request-ID` → `grep "<id>" /ruta/app.log` |
| Worker SAT (cola) | `python3 scripts/sat_worker.py` |

Más detalles: migraciones **MIGRATIONS.md**; variables de entorno y seguridad **README**, **.env.example**, **docs/archive/SECURITY_MINIMUM.md**.

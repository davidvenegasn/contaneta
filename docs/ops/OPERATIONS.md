# Operación — Conta Invoicing

**Un solo lugar para operar** el sistema: poner en marcha, backups, restaurar, cron del worker SAT y health. Pensado para que **cualquier persona** pueda seguir los pasos copiando y pegando comandos; solo hay que sustituir las rutas por las de tu servidor.

---

## Índice

1. [Checklist de producción](#1-checklist-de-producción)
2. [Glosario rápido](#2-glosario-rápido)
3. [Primera puesta en marcha](#3-primera-puesta-en-marcha)
4. [Arrancar, parar y comprobar](#4-arrancar-parar-y-comprobar)
5. [Health y listo para tráfico](#5-health-y-listo-para-tráfico)
6. [Backups](#6-backups)
7. [Restaurar desde backup](#7-restaurar-desde-backup)
8. [Worker SAT (sincronización CFDI)](#8-worker-sat-sincronización-cfdi)
9. [Cron: tareas programadas](#9-cron-tareas-programadas)
10. [Logging](#10-logging)
11. [Qué hacer si…](#11-qué-hacer-si)
12. [Resumen rápido](#12-resumen-rápido)

---

## 1. Checklist de producción

Antes de abrir el sistema a usuarios reales, comprueba en tu `.env`:

| Variable | Valor | Por qué |
|----------|--------|--------|
| **ENV** | `prod` | Activa comportamiento de producción (cookies, etc.). |
| **DEV_MODE** | `0` | Si está en `1`, el modo desarrollo puede permitir acceso no deseado. |
| **SESSION_SECRET** | Una cadena larga aleatoria | Obligatorio en producción; sin ella las sesiones no son seguras. |
| **COOKIE_SECURE** | `1` | Si usas HTTPS, la cookie solo se envía por HTTPS. |

**Generar SESSION_SECRET (copiar y pegar en .env):**

```bash
python3 -c "import secrets; print('SESSION_SECRET=' + secrets.token_hex(32))"
```

**Comprobar en el servidor:**

```bash
grep -E "ENV|DEV_MODE|SESSION_SECRET|COOKIE_SECURE" .env
# Debe verse: ENV=prod, DEV_MODE=0, SESSION_SECRET=..., COOKIE_SECURE=1
```

Opcional pero recomendado: **APP_DB_PATH** con ruta absoluta al archivo de base de datos (ej. `/var/lib/conta/invoicing.db`).

---

## 2. Glosario rápido

| Término | Significado |
|--------|-------------|
| **Proyecto** | Carpeta donde está instalada la aplicación (ej. `/var/www/conta-invoicing`). |
| **DB / base de datos** | Archivo `invoicing.db` (o la ruta en `APP_DB_PATH`). Guarda usuarios, empresas, facturas, etc. |
| **Storage** | Carpeta `storage/` del proyecto. Contiene XMLs del SAT y credenciales FIEL. |
| **Backup** | Copia de seguridad. Los scripts guardan en `backup/` (o en `BACKUP_DIR`). |
| **Health** | Comprobación de que la app y la base de datos responden. URL: `/health`. |
| **Retención** | Días que se conservan los backups antiguos; los más viejos se borran automáticamente. |

---

## 3. Primera puesta en marcha

### Requisitos

- **Python 3.10+** y dependencias: `pip install -r requirements.txt`
- **SQLite** (viene con Python)
- Para **sincronización SAT:** PHP 8+ y Composer en `sat_sync/` (ver documentación de sat_sync si existe)

### Código y entorno virtual

Desde la raíz del proyecto:

```bash
cd /ruta/al/proyecto
python3 -m venv venv
source venv/bin/activate   # En Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install gunicorn       # Recomendado para producción
```

### Variables de entorno

Crear `.env` en la raíz (mismo nivel que `app.py`):

```bash
cp .env.example .env
nano .env
```

Mínimo para producción (ver [Checklist de producción](#1-checklist-de-producción)):

```env
ENV=prod
DEV_MODE=0
SESSION_SECRET=<pegar aquí el valor generado con el comando de la sección 1>
COOKIE_SECURE=1
APP_DB_PATH=/ruta/al/proyecto/invoicing.db
```

### Migraciones

Las migraciones se aplican solas al arrancar la app. Si quieres aplicarlas antes:

```bash
cd /ruta/al/proyecto
source venv/bin/activate
python3 scripts/run_migrations.py
```

Debe terminar con mensaje de éxito. Si falla, no arranques la app hasta resolverlo.

### Directorios

```bash
mkdir -p backup storage
chmod 750 backup storage
```

### Servicio systemd (reinicio automático)

Crear el archivo de servicio (como root):

```bash
sudo nano /etc/systemd/system/conta-invoicing.service
```

Contenido de ejemplo (ajusta rutas y usuario):

```ini
[Unit]
Description=Conta Invoicing (FastAPI)
After=network.target

[Service]
Type=notify
User=conta
Group=conta
WorkingDirectory=/var/www/conta-invoicing
Environment="PATH=/var/www/conta-invoicing/venv/bin"
EnvironmentFile=/var/www/conta-invoicing/.env
ExecStart=/var/www/conta-invoicing/venv/bin/gunicorn app:app -k uvicorn.workers.UvicornWorker -w 2 -b 127.0.0.1:8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Activar e iniciar:

```bash
sudo systemctl daemon-reload
sudo systemctl enable conta-invoicing
sudo systemctl start conta-invoicing
sudo systemctl status conta-invoicing
```

---

## 4. Arrancar, parar y comprobar

**Arrancar (sin systemd):**

```bash
cd /ruta/al/proyecto
export APP_DB_PATH=/ruta/al/invoicing.db   # si no usas .env
uvicorn app:app --host 0.0.0.0 --port 8000
```

En producción con gunicorn:

```bash
gunicorn app:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

**Con systemd:**

- Arrancar: `sudo systemctl start conta-invoicing`
- Parar: `sudo systemctl stop conta-invoicing`
- Estado: `sudo systemctl status conta-invoicing`
- Logs: `sudo journalctl -u conta-invoicing -f`

**Comprobar que está bien:**

- Navegador: abrir la URL de la app y comprobar que carga login o registro.
- Línea de comandos: `curl -s http://localhost:8000/health`  
  Debe devolver algo como: `"status":"ok", "db":"ok", "migrations_applied": true`.

---

## 5. Health y listo para tráfico

### GET /health

- **URL:** `GET /health` (pública, sin contraseña).
- **Uso:** Saber si la app está viva y si la base de datos se puede leer (monitoreo, balanceadores).

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

**Sin secretos:** Este endpoint no devuelve contraseñas, SESSION_SECRET ni rutas internas. Es seguro usarlo en monitoreo.

### GET /ready

- **URL:** `GET /ready`
- **Uso:** Para balanceadores: “¿puedo enviar tráfico a esta instancia?”. **200** si está listo, **503** si no.

Comprobar:

```bash
curl -s http://localhost:8000/health
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ready
```

El segundo debería devolver `200`.

---

## 6. Backups

Hay dos tipos: **base de datos** y **storage (XMLs y credenciales)**. Conviene programarlos con cron (sección 9). Si al ejecutar los scripts sale "Permission denied": `chmod +x scripts/backup_db.sh scripts/backup_storage_xml.sh scripts/backup_all.sh`.

### 6.1 Backup de la base de datos

**Script:** `scripts/backup_db.sh`

Copia la DB a `backup/invoicing_YYYYMMDD_HHMMSS.db`. Retención: se pueden borrar automáticamente los backups más viejos de X días (por defecto 30). `BACKUP_RETAIN_DAYS=0` = no borrar ninguno.

```bash
cd /ruta/al/proyecto
./scripts/backup_db.sh
```

Con rutas y retención propias:

```bash
APP_DB_PATH=/var/lib/conta/invoicing.db BACKUP_DIR=/backups/conta BACKUP_RETAIN_DAYS=14 ./scripts/backup_db.sh
```

### 6.2 Backup del storage (XMLs y FIEL)

**Script:** `scripts/backup_storage_xml.sh`

Copia `storage/` a `backup/storage_YYYYMMDD_HHMMSS`. Retención igual que la DB.

```bash
./scripts/backup_storage_xml.sh
```

Comprimido (recomendado si hay mucho contenido):

```bash
BACKUP_STORAGE_ZIP=1 ./scripts/backup_storage_xml.sh
```

### 6.3 Backup completo (DB + storage)

**Script:** `scripts/backup_all.sh`

Ejecuta primero backup de la DB y luego el de storage.

```bash
./scripts/backup_all.sh
```

### Variables de entorno para backups

| Variable | Uso | Ejemplo |
|----------|-----|--------|
| `APP_DB_PATH` | Ruta del archivo `.db` | `/var/lib/conta/invoicing.db` |
| `BACKUP_DIR` | Carpeta donde guardar backups | `/backups/conta` |
| `BACKUP_RETAIN_DAYS` | Días de retención (borrar más antiguos). `0` = no borrar | `30` o `14` |
| `STORAGE_DIR` | Carpeta a respaldar (solo storage) | `/var/app/storage` |
| `BACKUP_STORAGE_ZIP` | `1` = guardar storage como .tar.gz | `1` |

---

## 7. Restaurar desde backup

Resumen en 4 pasos:

1. **Detener la aplicación** (ej. `sudo systemctl stop conta-invoicing`).
2. **(Opcional)** Guardar una copia del estado actual por si hay que volver atrás:  
   `cp invoicing.db invoicing.db.before-restore`
3. **Copiar** el archivo o carpeta del backup al lugar donde la app espera la DB o `storage/`.
4. Ajustar permisos si hace falta; **arrancar** la aplicación y comprobar con `GET /health`.

**Guías detalladas (comandos copy-paste):**

- **RESTORE.md** (en la raíz del proyecto)
- **scripts/restore.md** (pasos detallados con ejemplos)

---

## 8. Worker SAT (sincronización CFDI)

Cuando un usuario pulsa **“Sincronizar SAT”** en el portal, se encola un trabajo. El **worker** es el programa que ejecuta esos trabajos (descarga XMLs del SAT, etc.).

**Script:** `scripts/sat_worker.py`

**Ejecución manual:**

```bash
cd /ruta/al/proyecto
APP_DB_PATH=/ruta/al/invoicing.db python3 scripts/sat_worker.py
```

Para que la sincronización se procese sin intervención, programa este comando cada **10–15 minutos** con cron (sección 9).

Requisitos: Python 3, PHP en el PATH (o variable `PHP_BIN`), Composer en `sat_sync/`.

---

## 9. Cron: tareas programadas

Para que los backups y el worker SAT se ejecuten solos, usa cron. Sustituye `/ruta/al/proyecto` y las rutas de DB por las tuyas.

**Abrir crontab:**

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

Retención de 14 días en backups:

```cron
0 2 * * * cd /ruta/al/proyecto && APP_DB_PATH=/ruta/al/invoicing.db BACKUP_RETAIN_DAYS=14 ./scripts/backup_db.sh >> /var/log/conta_backup_db.log 2>&1
```

---

## 10. Logging

### Request ID (seguir una petición en los logs)

Cada petición HTTP tiene un **identificador único** (request_id). Puedes rastrear una petición desde la cabecera de respuesta hasta los logs.

- Por defecto: `LOG_REQUEST_ID=1`. Cada línea de log incluye el request_id al inicio.
- Cabecera de respuesta: `X-Request-ID: <id>`.
- Buscar en logs: `grep "a1b2c3d4e5f6" /var/log/conta/app.log` (sustituye por el valor de X-Request-ID).

### Log a archivo

Si defines `LOG_FILE=/ruta/al/app.log`, los logs se escriben también en ese archivo (UTF-8).

```bash
LOG_FILE=/var/log/conta/app.log uvicorn app:app --host 0.0.0.0 --port 8000
```

En `.env`: `LOG_FILE=/var/log/conta/app.log`

---

## 11. Qué hacer si…

| Situación | Acción |
|-----------|--------|
| La app no arranca | Revisar logs: `sudo journalctl -u conta-invoicing -n 100`. Comprobar que `APP_DB_PATH` y `SESSION_SECRET` estén definidos (ver `.env.example`). |
| `/health` devuelve `degraded` o `db: error` | La base de datos no se lee. Comprobar que el archivo existe, permisos y que no esté corrupto. Opcional: `APP_DB_PATH=/ruta/invoicing.db python3 scripts/check_db.py`. |
| Tras restaurar la DB la app no inicia | Volver al backup anterior: `mv invoicing.db.before-restore invoicing.db` y reiniciar. Ver **scripts/restore.md**. |
| Los XMLs no se ven en el portal | Comprobar que la carpeta `storage/` existe y tiene permisos correctos. Si acabas de restaurar, ver **scripts/restore.md** (restaurar storage). |
| La sincronización SAT no avanza | Asegurarse de que el worker se ejecuta (cron cada 10 min). Revisar `sat_worker.log` y que PHP y Composer estén instalados para `sat_sync/`. |
| Quiero guardar backups para siempre | Usar `BACKUP_RETAIN_DAYS=0` en los scripts de backup (no se borrarán copias antiguas). |

---

## 12. Resumen rápido

| Tarea | Comando o URL |
|-------|----------------|
| ¿Está viva la app? | `GET /health` (sin secretos) |
| ¿Puedo enviar tráfico? | `GET /ready` (sin secretos) |
| Backup base de datos | `./scripts/backup_db.sh` (retención: `BACKUP_RETAIN_DAYS`) |
| Backup storage (XMLs) | `./scripts/backup_storage_xml.sh` |
| Backup completo (DB + storage) | `./scripts/backup_all.sh` |
| Restaurar DB o storage | **RESTORE.md** y **scripts/restore.md** |
| Seguir una petición en logs | Cabecera `X-Request-ID` → `grep "<id>" /ruta/app.log` |
| Worker SAT (cola) | `python3 scripts/sat_worker.py` |

---

## Documentos relacionados

- **MIGRATIONS.md** — Cómo funcionan las migraciones y cómo crear una nueva.
- **SECURITY_NOTES.md** — Cookies, rate limit, variables críticas.
- **QA_STEPS.md** — Pruebas manuales (registro, login, descargas, health).
- **.env.example** — Variables de entorno y comentarios.

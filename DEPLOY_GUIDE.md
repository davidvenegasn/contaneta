# Guía de despliegue — ContaNeta (producción 24/7)

> **Consolidado en [OPERATIONS.md](OPERATIONS.md).** Para poner en marcha, checklist de producción (ENV, DEV_MODE, SESSION_SECRET, COOKIE_SECURE), systemd, backups y cron usa **OPERATIONS.md**.

Pasos para dejar la aplicación corriendo en un servidor Ubuntu típico, con reinicio automático, HTTPS, backups y health check.

---

## 1. Servidor y usuario

- **Ubuntu:** 20.04 o 22.04 LTS recomendado.
- Crear un usuario dedicado (no root) para la app:

```bash
sudo adduser --disabled-password --gecos "" conta
sudo su - conta
```

El resto de pasos (clonar, venv, variables) se hacen como este usuario en su `$HOME` o en un directorio elegido (p. ej. `/var/www/conta-invoicing` con dueño `conta`).

---

## 2. Dependencias del sistema

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
```

(Opcional, para compilar algunas dependencias: `sudo apt install -y python3-dev build-essential`.)

---

## 3. Código y entorno virtual

```bash
# Como usuario conta (o el que uses)
cd ~
git clone <URL_DEL_REPO> conta-invoicing
cd conta-invoicing
git checkout main   # o la rama que uses en producción

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Si usas **gunicorn** para producción (recomendado):

```bash
pip install gunicorn
```

---

## 4. Variables de entorno

Crear `.env` en la raíz del proyecto (mismo directorio que `app.py`):

```bash
cd /ruta/al/proyecto
nano .env
```

Variables mínimas recomendadas para producción:

```env
# Obligatorias en producción (si SESSION_SECRET falta con ENV=prod, la app emite log CRITICAL al arrancar)
ENV=prod
DEV_MODE=0
SESSION_SECRET=<valor fijo; generar: python3 -c "import secrets; print(secrets.token_hex(32))">
COOKIE_SECURE=1

# Base de datos (por defecto: ./invoicing.db)
APP_DB_PATH=/ruta/al/proyecto/invoicing.db

# Opcionales
SESSION_TTL_DAYS=7
SITE_URL=https://tu-dominio.com
```

- **DEV_MODE=0** desactiva el modo desarrollo (acceso sin login con token demo).
- **COOKIE_SECURE=1** solo envía cookies por HTTPS.
- **SESSION_SECRET** debe ser un valor aleatorio y distinto por entorno.

---

## 5. Migraciones

Aplicar migraciones **antes** de arrancar la app (o en el primer arranque; la app también las aplica al inicio):

```bash
cd /ruta/al/proyecto
source venv/bin/activate
export APP_DB_PATH=/ruta/al/proyecto/invoicing.db   # si no usas .env
python scripts/run_migrations.py
```

Debe terminar con "✓ Migraciones completadas". Si falla, no arranques la app hasta resolverlo.

---

## 6. Directorios y permisos

```bash
mkdir -p backup storage
chmod 750 backup storage
```

La app escribe en `backup/` (health check de escritura) y en `storage/` (XMLs descargados). El usuario que ejecuta la app debe tener permisos de escritura.

---

## 7. Probar que arranca

```bash
cd /ruta/al/proyecto
source venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8000
```

En otra terminal (o desde el servidor):

```bash
curl -s http://127.0.0.1:8000/health
```

Debe devolver JSON con `"status": "ok"`, `db_readable: true`, `migrations_applied: true`. Detener con Ctrl+C y seguir con systemd.

---

## 8. systemd: servicio que reinicia solo

Crear el archivo de servicio (como root o con sudo):

```bash
sudo nano /etc/systemd/system/conta-invoicing.service
```

Contenido de ejemplo (ajusta rutas y usuario):

```ini
[Unit]
Description=ContaNeta Invoicing (FastAPI)
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

- **Restart=always** y **RestartSec=5**: si el proceso cae, systemd lo reinicia a los 5 segundos.
- **-w 2**: 2 workers; ajusta según CPUs.
- **-b 127.0.0.1:8000**: escucha solo en localhost; el proxy inverso (Nginx/Caddy) se conecta aquí.

Si no usas gunicorn:

```ini
ExecStart=/var/www/conta-invoicing/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

Activar e iniciar:

```bash
sudo systemctl daemon-reload
sudo systemctl enable conta-invoicing
sudo systemctl start conta-invoicing
sudo systemctl status conta-invoicing
```

Logs:

```bash
sudo journalctl -u conta-invoicing -f
```

---

## 9. Reverse proxy y HTTPS (Nginx + Let's Encrypt)

Instalar Nginx y Certbot:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

Crear configuración para el sitio (sustituir `tu-dominio.com`):

```bash
sudo nano /etc/nginx/sites-available/conta-invoicing
```

```nginx
server {
    listen 80;
    server_name tu-dominio.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Activar sitio y obtener certificado:

```bash
sudo ln -s /etc/nginx/sites-available/conta-invoicing /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d tu-dominio.com
```

Certbot modifica la config para escuchar en 443 y usar el certificado. Renovación automática:

```bash
sudo certbot renew --dry-run
```

---

## 10. Reverse proxy y HTTPS (Caddy)

Instalar Caddy (ver caddy.com) y crear Caddyfile:

```bash
sudo nano /etc/caddy/Caddyfile
```

```caddy
tu-dominio.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy obtiene y renueva Let's Encrypt solo. Reiniciar:

```bash
sudo systemctl reload caddy
```

---

## 11. Backups y rotación

- **Base de datos:** `scripts/backup_db.sh` (copia `invoicing.db` a `backup/` con timestamp).
- **Storage (XML):** `scripts/backup_storage.sh` (copia `storage/` a `backup/` con timestamp).

Ambos scripts incluyen **rotación**: mantienen solo los últimos N días (por defecto 30). Configuración:

- `BACKUP_RETAIN_DAYS=30` (export o en cron).

Ejemplo cron (backup diario a las 2:00):

```cron
0 2 * * * /var/www/conta-invoicing/scripts/backup_db.sh
5 2 * * * /var/www/conta-invoicing/scripts/backup_storage.sh
```

Ajusta rutas y asegura `APP_DB_PATH` y `BACKUP_DIR` si no usas los valores por defecto.

Restaurar: ver **scripts/restore_notes.md**.

---

## 12. Logging

- **systemd:** La salida estándar del servicio se captura en journald. Ver logs con `journalctl -u conta-invoicing -f`. No hace falta logrotate para la app si solo usas journald.
- **Rotación de journald:** Por defecto el journal tiene límite de tamaño; en Ubuntu suele estar bien. Si quieres límites explícitos, configura en `/etc/systemd/journald.conf` (SystemMaxUse, etc.).
- **Log a archivo:** Si en el futuro la app escribe a un archivo de log, se puede añadir un config de logrotate en `deploy/logrotate-conta.example`.

---

## 13. Health check

El endpoint **GET /health** (sin autenticación) devuelve JSON:

- **status:** "ok" o "degraded"
- **db_readable:** si la base de datos es accesible
- **migrations_applied:** si existe la tabla de migraciones y se aplicaron
- **migration_version:** última versión aplicada (para monitoreo)
- **storage_writable:** si se puede escribir en el directorio de backups

Uso en balanceadores o monitoreo:

```bash
curl -s http://127.0.0.1:8000/health
```

En producción, el proxy suele exponer `https://tu-dominio.com/health`; comprueba que devuelve 200 y `"status": "ok"`.

---

## Resumen rápido

1. Usuario y deps del sistema.
2. Clonar repo, venv, `pip install -r requirements.txt` (+ gunicorn si usas systemd con gunicorn).
3. `.env` con DEV_MODE=0, SESSION_SECRET, COOKIE_SECURE=1, APP_DB_PATH si aplica.
4. `python scripts/run_migrations.py`.
5. systemd: `conta-invoicing.service` con Restart=always.
6. Nginx o Caddy como reverse proxy + HTTPS (Let's Encrypt).
7. Cron para backups con rotación (backup_db.sh, backup_storage.sh).
8. Monitorear con GET /health.

Con esto el servidor puede correr 24/7, reiniciar solo ante fallos, tener HTTPS, backups rotados y health check listo.

# Restaurar desde backup (DB + storage/XMLs)

Pasos exactos para restaurar la base de datos y/o el directorio de XMLs. Puedes copiar y pegar los comandos sustituyendo las rutas por las de tu servidor.

---

## Antes de empezar

- **Ruta del proyecto:** en los ejemplos se usa `PROYECTO` como la carpeta donde está la aplicación (por ejemplo `/var/www/conta-invoicing` o `/home/conta/app`).
- **Base de datos:** la app usa el archivo definido en `APP_DB_PATH` (o por defecto `invoicing.db` dentro del proyecto).
- **Backups:** se asume que los backups están en la carpeta `backup/` del proyecto (o en la ruta que hayas usado con `BACKUP_DIR` al hacer el backup).

Sustituye en los comandos:

- `PROYECTO` → ruta real del proyecto (ej. `/var/www/conta-invoicing`)
- `invoicing_20250118_020000.db` → nombre real del archivo de backup que quieras restaurar (fecha/hora)
- `storage_20250118_030000` o `storage_20250118_030000.tar.gz` → nombre real del backup de storage

---

## 1. Restaurar solo la base de datos

### 1.1 Detener la aplicación

Para que nadie escriba en la DB mientras restauramos:

```bash
sudo systemctl stop conta-invoicing
```

(Si usas otro nombre de servicio, cámbialo. Si la app se ejecuta a mano, detén el proceso.)

### 1.2 Copia de seguridad del estado actual (recomendado)

Por si necesitas volver atrás:

```bash
cp PROYECTO/invoicing.db PROYECTO/invoicing.db.before-restore
```

Con DB en ruta distinta:

```bash
cp /ruta/donde/esta/invoicing.db /ruta/donde/esta/invoicing.db.before-restore
```

### 1.3 Sustituir la DB por el backup

```bash
cp PROYECTO/backup/invoicing_20250118_020000.db PROYECTO/invoicing.db
```

Si tu DB está en otra ruta (APP_DB_PATH):

```bash
cp PROYECTO/backup/invoicing_20250118_020000.db /ruta/absoluta/invoicing.db
```

### 1.4 Permisos (si el servidor usa un usuario concreto)

Ajusta `usuario` y `grupo` al que ejecuta la app:

```bash
sudo chown usuario:grupo PROYECTO/invoicing.db
sudo chmod 640 PROYECTO/invoicing.db
```

### 1.5 Arrancar la aplicación

```bash
sudo systemctl start conta-invoicing
```

### 1.6 Comprobar

```bash
curl -s http://127.0.0.1:8000/health
```

Deberías ver algo como: `"status":"ok","db":"ok"`. Si no, revisa logs: `sudo journalctl -u conta-invoicing -n 100`.

---

## 2. Restaurar solo el directorio storage (XMLs y credenciales FIEL)

### 2.1 (Opcional) Detener la aplicación

Recomendado para que no se escriba en `storage/` durante la restauración:

```bash
sudo systemctl stop conta-invoicing
```

### 2.2 Guardar el storage actual (opcional)

Por si necesitas volver al estado anterior:

```bash
mv PROYECTO/storage PROYECTO/storage.old
```

### 2.3 Restaurar desde backup

**Si el backup es una carpeta** (sin comprimir):

```bash
cp -a PROYECTO/backup/storage_20250118_030000 PROYECTO/storage
```

**Si el backup es .tar.gz:**

```bash
cd PROYECTO
tar xzf backup/storage_20250118_030000.tar.gz
```

(Esto deja la carpeta `storage` dentro del proyecto.)

### 2.4 Permisos

```bash
sudo chown -R usuario:grupo PROYECTO/storage
```

### 2.5 Si detuviste la app, arrancarla de nuevo

```bash
sudo systemctl start conta-invoicing
```

### 2.6 Comprobar

```bash
curl -s http://127.0.0.1:8000/health
```

Entra al portal y comprueba que se ven los XMLs / datos que esperas.

---

## 3. Restaurar DB y storage (todo)

Sigue primero **toda** la sección 1 (restaurar DB) y luego **toda** la sección 2 (restaurar storage). Orden recomendado: DB primero, luego storage.

---

## 4. Si algo sale mal

- **La app no arranca tras restaurar la DB:**  
  Revisar logs: `sudo journalctl -u conta-invoicing -n 100`.  
  Volver al estado anterior:  
  `mv PROYECTO/invoicing.db.before-restore PROYECTO/invoicing.db`  
  y reiniciar el servicio.

- **Comprobar la DB sin levantar la app:**  
  `APP_DB_PATH=PROYECTO/invoicing.db python3 PROYECTO/scripts/check_db.py`

- **Restaurar el storage anterior:**  
  `mv PROYECTO/storage PROYECTO/storage.failed`  
  `mv PROYECTO/storage.old PROYECTO/storage`  
  y reiniciar la app.

Más detalles de operación en **docs/ops/OPERATIONS.md** (deploy, backup, cron, health).

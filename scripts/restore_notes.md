# Cómo restaurar desde backup

## Restaurar la base de datos (invoicing.db)

1. **Detener la aplicación** para evitar escrituras durante la restauración:
   ```bash
   sudo systemctl stop conta-invoicing
   ```

2. **Hacer una copia de seguridad del estado actual** (por si acaso):
   ```bash
   cp /var/www/conta-invoicing/invoicing.db /var/www/conta-invoicing/invoicing.db.before-restore
   ```

3. **Copiar el backup elegido** sobre el archivo de la DB:
   ```bash
   cp /var/www/conta-invoicing/backup/invoicing_YYYYMMDD_HHMMSS.db /var/www/conta-invoicing/invoicing.db
   ```
   Ajusta la ruta del backup a la que quieras restaurar (por fecha/hora).

4. **Ajustar dueño y permisos** (si aplica):
   ```bash
   chown conta:conta /var/www/conta-invoicing/invoicing.db
   chmod 640 /var/www/conta-invoicing/invoicing.db
   ```

5. **Arrancar de nuevo la aplicación**:
   ```bash
   sudo systemctl start conta-invoicing
   ```

6. **Comprobar**:
   ```bash
   curl -s http://127.0.0.1:8000/health
   ```

---

## Restaurar el directorio storage (XMLs)

1. **Opcional:** detener la app si quieres que nada escriba en `storage/` durante la restauración:
   ```bash
   sudo systemctl stop conta-invoicing
   ```

2. **Renombrar o borrar** el `storage/` actual (si existe):
   ```bash
   mv /var/www/conta-invoicing/storage /var/www/conta-invoicing/storage.old
   ```

3. **Copiar el backup** como nuevo `storage/`:
   ```bash
   cp -a /var/www/conta-invoicing/backup/storage_YYYYMMDD_HHMMSS /var/www/conta-invoicing/storage
   ```

4. **Ajustar dueño** (usuario de la app):
   ```bash
   chown -R conta:conta /var/www/conta-invoicing/storage
   ```

5. **Si paraste la app**, arrancarla de nuevo:
   ```bash
   sudo systemctl start conta-invoicing
   ```

---

## Si algo sale mal

- Si tras restaurar la DB la app no arranca, revisa logs: `sudo journalctl -u conta-invoicing -n 100`.
- Puedes volver al estado anterior: `mv invoicing.db.before-restore invoicing.db` y reiniciar el servicio.
- Para comprobar la DB sin levantar la app: `APP_DB_PATH=/ruta/invoicing.db python scripts/check_db.py`.

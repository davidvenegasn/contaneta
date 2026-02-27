# Recovery Playbook — ContaNeta

Pasos cortos: si falla X, revisa Y.

| Si falla… | Revisa… |
|-----------|--------|
| **Login / acceso al portal** | Que la base de datos exista y sea legible (`/status`). Si `db_readable` es No, revisar que `invoicing.db` exista y que el proceso tenga permisos de lectura. |
| **Panel admin (403)** | Que el usuario tenga una membership con rol `admin` u `owner`. En SQL: `SELECT * FROM memberships WHERE user_id = X AND role IN ('admin','owner');` |
| **Migraciones** | `/status`: si `migrations_applied` es No, ejecutar “Correr migraciones” en `/admin/ops` o, con acceso al servidor, `APP_DB_PATH=invoicing.db python scripts/run_migrations.py`. |
| **Backup desde /admin/ops** | Que existan `scripts/backup_db.sh` y, si aplica, `scripts/backup_storage_xml.sh`, y que el directorio `backup/` sea escribible. Probar escritura en `backup/` (en `/status` se comprueba `storage_writable`). |
| **Base de datos dañada o bloqueada** | Dejar de escribir (reiniciar app si hace falta). Copiar `invoicing.db` a un respaldo antes de tocar nada. Para diagnóstico: `APP_DB_PATH=invoicing.db python scripts/check_db.py`. |
| **Impersonation no aparece o no sale** | Que la cookie de sesión sea la correcta (mismo dominio). Revisar en `audit_log` las acciones `impersonate` y `stop_impersonate` para ese usuario. |

---

*Documento mínimo para recuperación rápida. Detalles operativos en ADMIN_GUIDE.md.*

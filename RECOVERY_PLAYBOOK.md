# Recovery Playbook — ContaNeta

Pasos cortos: si falla X, revisa Y.

| Si falla… | Revisa… |
|-----------|--------|
| **Login / acceso al portal** | Que la base de datos exista y sea legible (`/status`). Si `db_readable` es No, revisar que `invoicing.db` exista y que el proceso tenga permisos de lectura. |
| **Panel admin (403)** | Que el usuario tenga una membership con rol `admin` u `owner`. En SQL: `SELECT * FROM memberships WHERE user_id = X AND role IN ('admin','owner');` |
| **Migraciones** | `/status`: si `migrations_applied` es No, ejecutar “Correr migraciones” en `/admin/ops` o, con acceso al servidor, `APP_DB_PATH=invoicing.db python scripts/run_migrations.py`. |
| **Backup desde /admin/ops** | Que existan `scripts/backup_db.sh` y, si aplica, `scripts/backup_storage_xml.sh`, y que el directorio `backup/` sea escribible. El backup de DB se genera como `backup/invoicing_YYYYMMDD_HHMMSS.db.gz`. En `/status` se comprueba `storage_writable`. |
| **Base de datos dañada o bloqueada** | Dejar de escribir (reiniciar app si hace falta). Copiar `invoicing.db` a un respaldo antes de tocar nada. Para diagnóstico: `APP_DB_PATH=invoicing.db python scripts/check_db.py`. |
| **Impersonation no aparece o no sale** | Que la cookie de sesión sea la correcta (mismo dominio). Revisar en `audit_log` las acciones `impersonate` y `stop_impersonate` para ese usuario. |

---

## Restore rápido (desde `backup/*.db.gz`)

1) **Detén** el proceso (para evitar escrituras durante el restore).  
2) **Restaura** el archivo:

```bash
gunzip -c backup/invoicing_YYYYMMDD_HHMMSS.db.gz > invoicing.db
```

3) Arranca la app y verifica:
- `GET /ready` debe devolver **200**
- `GET /status` debe mostrar `db_readable = Sí` y `migrations_applied = Sí`

*Documento mínimo para recuperación rápida. Detalles operativos en ADMIN_GUIDE.md.*

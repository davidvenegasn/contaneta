#!/usr/bin/env bash
# Ejemplo de cron para backups. Este script NO ejecuta backups; solo muestra líneas de ejemplo.
# Copia las líneas que necesites a crontab -e (crontab -e) y ajusta rutas.
#
# Retención: los scripts backup_db.sh y backup_storage_xml.sh ya borran backups antiguos
# según BACKUP_RETAIN_DAYS (default 30). Poner 0 para no borrar.
#
# Ver OPS_RUNBOOK.md sección 8 para cron completo (backups + worker SAT).

echo "Ejemplo de cron; no hace backup. Ver comentarios en este script y OPS_RUNBOOK.md."

# Ejemplo crontab:
# 0 2 * * * cd /ruta/al/proyecto && APP_DB_PATH=/ruta/al/invoicing.db BACKUP_RETAIN_DAYS=30 ./scripts/backup_db.sh >> /var/log/conta_backup_db.log 2>&1
# 0 3 */3 * * cd /ruta/al/proyecto && ./scripts/backup_storage_xml.sh >> /var/log/conta_backup_storage.log 2>&1

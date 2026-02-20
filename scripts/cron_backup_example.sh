#!/usr/bin/env bash
# Ejemplo de cron para backups diarios. No ejecuta nada por defecto.
# Copia a crontab -e o configura en tu sistema:
#
#   # Backup DB y storage a las 2:00 (ajusta PATH y APP_DB_PATH)
#   0 2 * * * APP_DB_PATH=/var/app/invoicing.db BACKUP_DIR=/var/backups/conta /ruta/al/proyecto/scripts/backup_db.sh >> /var/log/conta_backup_db.log 2>&1
#   15 2 * * * STORAGE_DIR=/var/app/storage BACKUP_DIR=/var/backups/conta /ruta/al/proyecto/scripts/backup_storage_xml.sh >> /var/log/conta_backup_storage.log 2>&1
#
# Retención: borrar backups antiguos fuera de este script (ej. find backup/ -name 'invoicing_*.db' -mtime +30 -delete).

echo "Ejemplo de cron; no hace backup. Ver comentarios en este script."

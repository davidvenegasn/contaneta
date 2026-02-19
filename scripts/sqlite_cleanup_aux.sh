#!/usr/bin/env bash
# Mueve invoicing.db-wal e invoicing.db-shm a sqlite_aux_backup/ con timestamp.
# No borra nada; solo crea la carpeta y mueve si los archivos existen.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/sqlite_aux_backup"
TS="$(date +%Y-%m-%d_%H-%M-%S)"

mkdir -p "$BACKUP_DIR"

for f in "invoicing.db-wal" "invoicing.db-shm"; do
  SRC="$PROJECT_ROOT/$f"
  if [ -f "$SRC" ]; then
    mv "$SRC" "$BACKUP_DIR/${f}.${TS}"
    echo "Movido: $f -> sqlite_aux_backup/${f}.${TS}"
  fi
done

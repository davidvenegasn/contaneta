#!/usr/bin/env bash
# Cambia entre DB "actual" y "antigua" solo renombrando archivos (nunca borra).
# Siempre ejecuta sqlite_cleanup_aux.sh antes de cambiar.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Siempre limpiar auxiliares WAL/SHM antes de tocar la DB
"$SCRIPT_DIR/sqlite_cleanup_aux.sh"

case "${1:-}" in
  --use-old)
    if [ -f "$PROJECT_ROOT/invoicing.db" ]; then
      mv "$PROJECT_ROOT/invoicing.db" "$PROJECT_ROOT/invoicing_new_empty.db"
      echo "Renombrado: invoicing.db -> invoicing_new_empty.db"
    fi
    if [ -f "$PROJECT_ROOT/invoicing_old.db" ]; then
      mv "$PROJECT_ROOT/invoicing_old.db" "$PROJECT_ROOT/invoicing.db"
      echo "Renombrado: invoicing_old.db -> invoicing.db"
    fi
    ;;
  --use-new)
    if [ -f "$PROJECT_ROOT/invoicing.db" ]; then
      mv "$PROJECT_ROOT/invoicing.db" "$PROJECT_ROOT/invoicing_old.db"
      echo "Renombrado: invoicing.db -> invoicing_old.db"
    fi
    if [ -f "$PROJECT_ROOT/invoicing_new_empty.db" ]; then
      mv "$PROJECT_ROOT/invoicing_new_empty.db" "$PROJECT_ROOT/invoicing.db"
      echo "Renombrado: invoicing_new_empty.db -> invoicing.db"
    fi
    ;;
  *)
    echo "Uso: $0 --use-old | --use-new"
    echo "  --use-old  activa la DB antigua (invoicing_old.db -> invoicing.db)"
    echo "  --use-new  revierte a la DB nueva (invoicing_new_empty.db -> invoicing.db)"
    exit 1
    ;;
esac

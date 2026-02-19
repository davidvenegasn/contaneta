#!/usr/bin/env python3
"""
Ejecuta apply_migrations(DB_PATH) manualmente sin levantar uvicorn.
Útil para aplicar migraciones en producción o antes de arrancar la app.
Uso: APP_DB_PATH=invoicing.db python scripts/run_migrations.py
"""
import os
import sys
import logging
from pathlib import Path

# Agregar raíz del proyecto al path para importar migrations_runner
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from migrations_runner import apply_migrations

# Misma lógica que app.py para DB_PATH
DB_PATH = os.getenv("APP_DB_PATH") or str(BASE_DIR / "invoicing.db")

# Configurar logging básico
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)

def main() -> None:
    print(f"Ejecutando migraciones en: {DB_PATH}")
    try:
        apply_migrations(DB_PATH)
        print("✓ Migraciones completadas")
        sys.exit(0)
    except Exception as e:
        print(f"✗ Error al aplicar migraciones: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

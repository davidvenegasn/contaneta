#!/usr/bin/env python3
"""
Backfill de clientes (y sugerencias de productos) desde facturas emitidas ya descargadas.
Lee sat_cfdi con direction='issued' y xml_path, extrae Receptor y Conceptos del XML
y upserta en clients y product_observations.

Se puede invocar manualmente o desde cron_sat_sync.sh después de parse_xml.php.
Uso:
  python scripts/backfill_clients_from_sat.py
  python scripts/backfill_clients_from_sat.py --issuer=11
"""
from __future__ import annotations

import argparse
import os
import sys

# Raíz del proyecto para importar app/services
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.chdir(BASE_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill clientes desde CFDI emitidos (SAT)")
    parser.add_argument("--issuer", type=int, default=None, help="Solo este issuer_id (omitir = todos con sat_credentials)")
    parser.add_argument("--limit", type=int, default=None, help="Máximo CFDI a procesar por issuer")
    args = parser.parse_args()

    import sqlite3
    from services.invoices.catalog_from_cfdi import backfill_catalog_from_existing_cfdi

    db_path = os.environ.get("APP_DB_PATH") or os.path.join(BASE_DIR, "invoicing.db")
    if not os.path.isfile(db_path):
        print("No existe base de datos:", db_path, file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if args.issuer is not None:
            cur = conn.execute(
                "SELECT 1 FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
                (args.issuer,),
            )
            if cur.fetchone() is None:
                print("Issuer", args.issuer, "no tiene sat_credentials.", file=sys.stderr)
                sys.exit(1)
            issuer_ids = [args.issuer]
        else:
            cur = conn.execute(
                "SELECT issuer_id FROM sat_credentials GROUP BY issuer_id ORDER BY issuer_id"
            )
            issuer_ids = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    if not issuer_ids:
        print("No hay issuers con sat_credentials.")
        return

    total_clients = 0
    total_obs = 0
    total_processed = 0
    for iid in issuer_ids:
        result = backfill_catalog_from_existing_cfdi(
            iid,
            limit=args.limit,
        )
        total_processed += result.processed
        total_clients += result.clients_upserted
        total_obs += result.observations_upserted
        if result.processed or result.clients_upserted or result.observations_upserted:
            print(
                f"issuer_id={iid} processed={result.processed} clients={result.clients_upserted} observations={result.observations_upserted}"
            )
        if result.errors:
            for err in result.errors[:3]:
                print(f"  error: {err}", file=sys.stderr)

    print(f"Total: {total_processed} CFDI · {total_clients} clientes · {total_obs} sugerencias productos")


if __name__ == "__main__":
    main()

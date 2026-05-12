"""Recalcula tipo_cambio y monto_mxn de TODOS los foreign_invoices usando TCs reales del DOF de Banxico.

Usage:
    python scripts/backfill_foreign_invoices_rates.py          # dry-run (preview only)
    python scripts/backfill_foreign_invoices_rates.py --apply   # apply changes to DB
"""
import logging
import sys
from pathlib import Path

# Ensure project root is in path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO)

from database import db_execute, db_rows
from services.invoices.banxico_client import get_rate


def main(dry_run: bool = True):
    invoices = db_rows(
        "SELECT id, fecha, moneda, monto_original, tipo_cambio, monto_mxn "
        "FROM foreign_invoices ORDER BY fecha DESC"
    )
    print(f"Total invoices a auditar: {len(invoices)}")
    changes, missing, skipped = 0, 0, 0
    for inv in invoices:
        moneda = (inv["moneda"] or "").upper()
        if moneda == "MXN":
            skipped += 1
            continue
        rate = get_rate(inv["fecha"], moneda)
        if rate is None:
            print(
                f"  [MISSING] id={inv['id']} fecha={inv['fecha']} "
                f"{moneda} → no rate available"
            )
            missing += 1
            continue
        new_mxn = round(inv["monto_original"] * rate, 2)
        old_mxn = inv["monto_mxn"] or 0
        old_tc = inv["tipo_cambio"] or 0
        if abs(new_mxn - old_mxn) > 0.5 or abs(rate - old_tc) > 0.01:
            print(
                f"  [UPDATE] id={inv['id']} {moneda} "
                f"{inv['monto_original']:.2f}: "
                f"tc {old_tc:.4f}→{rate:.4f}, "
                f"MXN {old_mxn:.2f}→{new_mxn:.2f}"
            )
            if not dry_run:
                db_execute(
                    "UPDATE foreign_invoices SET tipo_cambio = ?, monto_mxn = ? "
                    "WHERE id = ?",
                    (rate, new_mxn, inv["id"]),
                )
            changes += 1
    mode = "DRY RUN" if dry_run else "APPLIED"
    print(
        f"\n{mode}: {changes} updates, {missing} missing rates, "
        f"{skipped} skipped (MXN)."
    )


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    main(dry_run=dry_run)

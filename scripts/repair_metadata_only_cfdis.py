#!/usr/bin/env python3
"""Detect and repair metadata-only CFDIs (have metadata but no parsed XML).

Usage:
    scripts/repair_metadata_only_cfdis.py --issuer 8
    scripts/repair_metadata_only_cfdis.py --all
    scripts/repair_metadata_only_cfdis.py --issuer 8 --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env before importing app modules
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from database import db, db_rows
from services.sat.sat_metadata_only_repair import (
    count_metadata_only,
    find_metadata_only_cfdis,
    reset_checkpoint_for_repair,
)


def _get_all_issuer_ids() -> list[int]:
    """Return all active issuer IDs with validated FIEL."""
    rows = db_rows(
        "SELECT DISTINCT sc.issuer_id FROM sat_credentials sc "
        "JOIN issuers i ON i.id = sc.issuer_id AND i.active = 1 "
        "WHERE sc.validation_ok = 1 "
        "ORDER BY sc.issuer_id",
    )
    return [r["issuer_id"] for r in rows]


def main():
    parser = argparse.ArgumentParser(description="Detect and repair metadata-only CFDIs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--issuer", type=int, help="Specific issuer ID")
    group.add_argument("--all", action="store_true", help="All issuers with validated FIEL")
    parser.add_argument("--dry-run", action="store_true", help="Only report, don't reset checkpoint")
    parser.add_argument("--backfill-days", type=int, default=180, help="Days to backfill (default 180)")
    args = parser.parse_args()

    issuer_ids = [args.issuer] if args.issuer else _get_all_issuer_ids()
    if not issuer_ids:
        print("No issuers found.")
        return

    total_metadata_only = 0
    for iid in issuer_ids:
        counts = count_metadata_only(iid)
        mo = counts["issued_metadata_only"] + counts["received_metadata_only"]
        parsed = counts["issued_parsed"] + counts["received_parsed"]
        total_metadata_only += mo
        print(f"Issuer {iid}: {parsed} parsed, {mo} metadata-only "
              f"(issued: {counts['issued_metadata_only']}, received: {counts['received_metadata_only']})")

        if mo > 0 and not args.dry_run:
            from datetime import datetime, timedelta, timezone
            from_date = (datetime.now(timezone.utc) - timedelta(days=args.backfill_days)).strftime("%Y-%m-%d %H:%M:%S")
            reset_checkpoint_for_repair(iid, from_date)
            print(f"  -> Checkpoint reset to {from_date}")

    print(f"\nTotal metadata-only across all issuers: {total_metadata_only}")
    if args.dry_run:
        print("(dry-run: no changes made)")


if __name__ == "__main__":
    main()

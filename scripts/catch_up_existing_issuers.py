#!/usr/bin/env python3
"""One-time backfill for issuers that uploaded FIEL before the new wizard.

Triggers a 6-month historical sync for any issuer with:
- FIEL validation_ok = 1
- sat_credentials.created_at < 2026-06-01 (before wizard rollout)
- No catch-up flag set

Usage:
    python scripts/catch_up_existing_issuers.py [--dry-run] [--issuer ID]
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db, db_execute, db_rows  # noqa: E402
from services.sat.sat_autosync import enqueue_sat_sync  # noqa: E402
from services.sat.sat_priority import compute_priority  # noqa: E402

CATCH_UP_TABLE = "issuer_catch_up_done"


def ensure_table():
    """Create tracking table if it doesn't exist."""
    db_execute(
        "CREATE TABLE IF NOT EXISTS issuer_catch_up_done "
        "(issuer_id INTEGER PRIMARY KEY, done_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )


def find_pending() -> list[int]:
    """Find issuers that need catch-up (FIEL before wizard, not yet caught up)."""
    ensure_table()
    rows = db_rows(
        "SELECT sc.issuer_id FROM sat_credentials sc "
        "WHERE sc.validation_ok = 1 "
        "AND datetime(sc.created_at) < datetime('2026-06-01') "
        "AND sc.issuer_id NOT IN (SELECT issuer_id FROM issuer_catch_up_done)"
    )
    return [r["issuer_id"] for r in rows]


def catch_up_one(issuer_id: int, dry_run: bool = False) -> int:
    """Enqueue 6-month backfill for one issuer. Returns job count."""
    from services.sat.sat_autosync import _ym_range

    yms = _ym_range(6)
    count = 0

    for ym in yms:
        prio = compute_priority(issuer_id, ym, user_active_recently=True)
        for direction in ("issued", "received"):
            if dry_run:
                print(f"  [dry-run] issuer={issuer_id} ym={ym} dir={direction} prio={prio}")
                count += 1
            else:
                jid = enqueue_sat_sync(issuer_id, direction, priority=prio)
                if jid and jid > 0:
                    count += 1

    if not dry_run and count > 0:
        db_execute(
            "INSERT OR IGNORE INTO issuer_catch_up_done (issuer_id) VALUES (?)",
            (issuer_id,),
        )

    return count


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Catch-up sync for pre-wizard issuers")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be enqueued")
    parser.add_argument("--issuer", type=int, help="Only process this issuer ID")
    args = parser.parse_args()

    ensure_table()

    if args.issuer:
        print(f"Processing single issuer: {args.issuer}")
        n = catch_up_one(args.issuer, args.dry_run)
        print(f"  Enqueued {n} jobs" + (" [dry-run]" if args.dry_run else ""))
        return

    pending = find_pending()
    print(f"Found {len(pending)} issuers pending catch-up")

    total = 0
    for iid in pending:
        n = catch_up_one(iid, args.dry_run)
        print(f"  Issuer {iid}: {n} jobs" + (" [dry-run]" if args.dry_run else ""))
        total += n

    print(f"\nTotal: {total} jobs enqueued for {len(pending)} issuers")


if __name__ == "__main__":
    main()

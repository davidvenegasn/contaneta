#!/usr/bin/env python3
"""
SAT auto-sync scheduler — enqueues sat_jobs for eligible issuers.

Usage:
  python scripts/sat_scheduler.py --batch 50 --cooldown-hours 8
  python scripts/sat_scheduler.py --dry-run           # preview only
  python scripts/sat_scheduler.py --directions issued  # only issued

Designed to run via cron every 5-10 minutes.  Idempotent: won't
duplicate jobs thanks to dedupe logic in sat_autosync.
"""
import argparse
import logging
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sat_scheduler")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SAT auto-sync scheduler (enqueue only).")
    p.add_argument("--batch-size", "--batch", type=int, default=50, dest="batch", help="Max issuers to enqueue per run.")
    p.add_argument("--cooldown-hours", type=int, default=8, help="Min hours between syncs per direction.")
    p.add_argument("--active-days", type=int, default=30, help="Only sync issuers active within this many days.")
    p.add_argument("--directions", default="issued,received", help="Comma-separated directions.")
    p.add_argument("--dry-run", action="store_true", help="Print what would be enqueued without doing it.")
    args = p.parse_args(argv)

    directions = [d.strip() for d in args.directions.split(",") if d.strip()]

    from services.sat_autosync import get_eligible_issuers, enqueue_sat_sync

    eligible = get_eligible_issuers(
        cooldown_hours=args.cooldown_hours,
        batch=args.batch,
        active_days=args.active_days,
        directions=directions,
    )

    if not eligible:
        logger.info("No eligible issuers for auto-sync.")
        return 0

    logger.info("%d eligible issuer/direction pairs found.", len(eligible))
    enqueued = 0
    skipped = 0
    for item in eligible:
        rfc = item.get("rfc", "?")
        jid = enqueue_sat_sync(
            item["issuer_id"],
            item["direction"],
            dry_run=args.dry_run,
        )
        if jid:
            enqueued += 1
            logger.info("  %s issuer=%s (%s) dir=%s job=%s",
                        "[dry-run]" if args.dry_run else "enqueued",
                        item["issuer_id"], rfc, item["direction"], jid)
        else:
            skipped += 1
            logger.debug("  skipped issuer=%s (%s) dir=%s (dedup)", item["issuer_id"], rfc, item["direction"])

    if args.dry_run:
        logger.info("[dry-run] Would enqueue %d jobs, skipped %d (dedup).", enqueued, skipped)
    else:
        logger.info("Enqueued %d jobs, skipped %d (dedup).", enqueued, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

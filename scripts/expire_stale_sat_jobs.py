#!/usr/bin/env python3
"""Mark stale sat_jobs as expired so they stop showing in sync progress banner.

Run via cron daily at 4am:
    0 4 * * * cd /app && .venv/bin/python scripts/expire_stale_sat_jobs.py >> /var/log/conta/cleanup.log 2>&1
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db_execute, db_rows  # noqa: E402


def expire_queued(max_age_hours: int = 2, dry_run: bool = False) -> dict:
    """Mark sat_jobs queued > max_age_hours as error (auto-expired)."""
    counts = db_rows(
        "SELECT issuer_id, COUNT(*) AS c FROM sat_jobs "
        "WHERE status = 'queued' "
        "AND datetime(created_at) <= datetime('now', '-' || ? || ' hours') "
        "GROUP BY issuer_id",
        (max_age_hours,),
    )
    total = sum(r["c"] for r in counts)
    if not dry_run and total > 0:
        db_execute(
            "UPDATE sat_jobs SET status = 'error', "
            "finished_at = datetime('now'), "
            "last_error = 'Auto-expired: stale queued job (>' || ? || 'h)' "
            "WHERE status = 'queued' "
            "AND datetime(created_at) <= datetime('now', '-' || ? || ' hours')",
            (max_age_hours, max_age_hours),
        )
    return {"affected_issuers": len(counts), "total": total}


def expire_running(max_age_hours: int = 1, dry_run: bool = False) -> dict:
    """Mark sat_jobs running > max_age_hours as error (stuck worker)."""
    counts = db_rows(
        "SELECT issuer_id, COUNT(*) AS c FROM sat_jobs "
        "WHERE status = 'running' "
        "AND datetime(COALESCE(updated_at, created_at)) <= datetime('now', '-' || ? || ' hours') "
        "GROUP BY issuer_id",
        (max_age_hours,),
    )
    total = sum(r["c"] for r in counts)
    if not dry_run and total > 0:
        db_execute(
            "UPDATE sat_jobs SET status = 'error', "
            "finished_at = datetime('now'), "
            "last_error = 'Auto-expired: stuck running job (>' || ? || 'h)' "
            "WHERE status = 'running' "
            "AND datetime(COALESCE(updated_at, created_at)) <= datetime('now', '-' || ? || ' hours')",
            (max_age_hours, max_age_hours),
        )
    return {"affected_issuers": len(counts), "total": total}


def main():
    parser = argparse.ArgumentParser(description="Expire stale SAT sync jobs")
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't modify")
    parser.add_argument("--max-queued-hours", type=int, default=2)
    parser.add_argument("--max-running-hours", type=int, default=1)
    args = parser.parse_args()

    q = expire_queued(args.max_queued_hours, args.dry_run)
    r = expire_running(args.max_running_hours, args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Queued expired: {q['total']} ({q['affected_issuers']} issuers)")
    print(f"{prefix}Running expired: {r['total']} ({r['affected_issuers']} issuers)")


if __name__ == "__main__":
    main()

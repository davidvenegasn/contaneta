"""Process account deletion queue — purge accounts whose 30-day grace period has elapsed.

Run via cron (daily recommended):
    .venv/bin/python scripts/process_deletion_queue.py
    .venv/bin/python scripts/process_deletion_queue.py --dry-run   # preview only

LFPDPPP Art. 26 compliance: accounts are deleted after 30-day grace period.
"""
import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import db  # noqa: E402

logger = logging.getLogger(__name__)

# Tables that reference user_id and need explicit cleanup.
# Order matters: children first, then parent.
_USER_CLEANUP_TABLES = [
    "account_deletion_requests",
    "audit_log",
    "email_verifications",
    "password_resets",
    "staff_roles",
    "subscriptions",
    "memberships",
    "notifications",
]


def find_due_deletions():
    """Return list of pending deletion requests whose scheduled_for has passed.

    Returns:
        List of dicts with keys: id, user_id, scheduled_for, requested_at.
    """
    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT adr.id, adr.user_id, adr.scheduled_for, adr.requested_at
            FROM account_deletion_requests adr
            JOIN users u ON u.id = adr.user_id
            WHERE adr.status = 'pending'
              AND adr.scheduled_for IS NOT NULL
              AND adr.scheduled_for <= datetime('now')
            ORDER BY adr.scheduled_for ASC
            """,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_user_data(user_id, *, dry_run=False):
    """Purge all data for a user from the database.

    Args:
        user_id: The user ID to purge.
        dry_run: If True, log what would be deleted but don't execute.

    Returns:
        Dict with table names as keys and row counts deleted as values.
    """
    conn = db()
    deleted = {}
    try:
        for table in _USER_CLEANUP_TABLES:
            # Check table exists
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            # Check table has user_id column
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "user_id" not in cols:
                continue
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?",  # noqa: S608
                (user_id,),
            ).fetchone()
            count = row["n"] if row else 0
            if count > 0:
                if dry_run:
                    logger.info("[DRY RUN] Would delete %d rows from %s for user %d", count, table, user_id)
                else:
                    conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))  # noqa: S608
                deleted[table] = count

        # Delete the user record itself
        user_exists = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if user_exists:
            if dry_run:
                logger.info("[DRY RUN] Would delete user %d from users table", user_id)
            else:
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            deleted["users"] = 1

        if not dry_run:
            conn.commit()
    except Exception:
        if not dry_run:
            conn.rollback()
        raise
    finally:
        conn.close()
    return deleted


def process_queue(*, dry_run=False):
    """Find and process all due deletion requests.

    Args:
        dry_run: If True, log what would happen without making changes.

    Returns:
        List of dicts describing each processed deletion.
    """
    due = find_due_deletions()
    if not due:
        logger.info("No pending deletions due for processing.")
        return []

    logger.info("Found %d deletion(s) due for processing.", len(due))
    results = []
    for req in due:
        user_id = req["user_id"]
        request_id = req["id"]
        logger.info("Processing deletion request #%d for user %d (scheduled: %s)",
                     request_id, user_id, req["scheduled_for"])
        try:
            deleted = delete_user_data(user_id, dry_run=dry_run)
            results.append({"request_id": request_id, "user_id": user_id, "deleted": deleted, "ok": True})
            logger.info("Completed deletion for user %d: %s", user_id, deleted)
        except Exception as e:
            logger.error("Failed to process deletion for user %d: %s", user_id, e, exc_info=True)
            results.append({"request_id": request_id, "user_id": user_id, "error": str(e), "ok": False})
    return results


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Process account deletion queue")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions without executing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    results = process_queue(dry_run=args.dry_run)
    ok_count = sum(1 for r in results if r["ok"])
    fail_count = sum(1 for r in results if not r["ok"])

    if results:
        print(f"Processed: {ok_count} OK, {fail_count} failed")
    else:
        print("No deletions to process.")

    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()

"""Smart priority scoring for SAT sync jobs.

Lower score = higher priority (processed first).

Scoring tiers:
  1-9   = current month + active user (urgent)
  10-19 = current month + inactive user
  20-29 = last month + active user
  30-39 = last month + inactive user
  40-49 = M-2 + active user
  100+  = backfill histórico
"""
from __future__ import annotations

from datetime import date

from database import db_rows


def compute_priority(
    issuer_id: int,
    ym: str,
    *,
    user_active_recently: bool = False,
) -> int:
    """Compute priority score for a sat_job. Lower = higher priority.

    Args:
        issuer_id: Tenant ID.
        ym: Year-month string (YYYY-MM).
        user_active_recently: True if any owner has logged in within 7 days.

    Returns:
        Integer priority score (1 = most urgent, 100+ = backfill).
    """
    today = date.today()

    try:
        target_y, target_m = int(ym[:4]), int(ym[5:7])
        months_ago = (today.year - target_y) * 12 + (today.month - target_m)
    except Exception:
        months_ago = 999

    active_bonus = 0 if user_active_recently else 5

    if months_ago == 0:
        return 1 + active_bonus
    if months_ago == 1:
        return 20 + active_bonus
    if months_ago == 2:
        return 40 + active_bonus
    if months_ago == 3:
        return 60 + active_bonus
    return 100 + months_ago  # histórico


def is_user_active_recently(issuer_id: int, days: int = 7) -> bool:
    """Check if any user linked to this issuer has been active recently.

    Uses audit_log to detect recent activity (login, page views, etc.).

    Args:
        issuer_id: Tenant ID.
        days: Lookback window in days.

    Returns:
        True if at least one linked user has recent activity.
    """
    try:
        rows = db_rows(
            "SELECT 1 FROM audit_log al "
            "JOIN memberships m ON m.user_id = al.user_id AND m.issuer_id = ? "
            "WHERE al.created_at > datetime('now', '-' || ? || ' days') "
            "LIMIT 1",
            (issuer_id, days),
        )
        return bool(rows)
    except Exception:
        return False

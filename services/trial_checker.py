"""Check and notify users whose trial is expiring."""
import logging
from datetime import datetime, timedelta

from database import db_rows
from services.email.queue import enqueue_send_email

logger = logging.getLogger(__name__)

NOTIFY_DAYS = [7, 3, 1]


def check_and_notify_trial_expiring():
    """Run daily: notify users whose trial expires in 7, 3, or 1 day.

    Queries issuers with trial_expires_at within those windows and
    enqueues trial_expiring emails. Skips if already notified.
    """
    now = datetime.now()
    total_notified = 0

    for days in NOTIFY_DAYS:
        target_date = (now + timedelta(days=days)).strftime("%Y-%m-%d")
        # Find issuers with trial expiring on target_date
        issuers = db_rows(
            """SELECT i.id, i.rfc, i.razon_social, i.trial_expires_at
               FROM issuers i
               WHERE i.active = 1
                 AND i.trial_expires_at IS NOT NULL
                 AND DATE(i.trial_expires_at) = ?""",
            (target_date,),
        )
        for issuer in issuers:
            issuer_id = issuer["id"]
            # Find the owner user
            users = db_rows(
                """SELECT u.email, u.id AS user_id
                   FROM users u
                   JOIN memberships m ON m.user_id = u.id
                   WHERE m.issuer_id = ? AND m.role = 'owner'
                   LIMIT 1""",
                (issuer_id,),
            )
            if not users:
                continue

            user = users[0]
            # Check if we already sent this notification
            already_sent = db_rows(
                """SELECT 1 FROM jobs
                   WHERE name = 'send_email'
                     AND issuer_id = ?
                     AND payload_json LIKE '%trial_expiring%'
                     AND payload_json LIKE ?
                     AND created_at > datetime('now', '-2 days')
                   LIMIT 1""",
                (issuer_id, f'%"days_left": {days}%'),
            )
            if already_sent:
                continue

            try:
                enqueue_send_email(
                    to_email=user["email"],
                    template="trial_expiring",
                    context={
                        "days_left": days,
                        "expires_at": issuer.get("trial_expires_at", ""),
                        "issuer_name": issuer.get("razon_social", ""),
                        "brand_name": "ContaNeta",
                    },
                    email_type="trial_expiring",
                    issuer_id=issuer_id,
                    user_id=user["user_id"],
                )
                total_notified += 1
            except Exception as exc:
                logger.warning("Trial notification failed for issuer %d: %s", issuer_id, exc)

    logger.info("Trial checker: notified %d users", total_notified)
    return total_notified

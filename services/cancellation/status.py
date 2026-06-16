"""Poll SAT/Facturapi for cancellation status updates."""
import logging
from datetime import datetime, timedelta, timezone

from database import db
from facturapi_client import get_invoice as facturapi_get_invoice
from services.cancellation.log import insert_log
from services.cancellation.types import CancellationStatus

logger = logging.getLogger(__name__)


def poll_pending_cancellations(limit: int = 100) -> dict:
    """Check all CFDI with cancellation_status='pending' against Facturapi.

    Should be invoked from a cron job (every 1 hour is reasonable).
    Returns counts of how many were updated.
    """
    conn = db()
    try:
        rows = conn.execute(
            """SELECT s.id, s.issuer_id, s.uuid, s.cancellation_requested_at,
                      s.cancellation_requested_by_user_id,
                      i.facturapi_invoice_id, iss.facturapi_org_id
                 FROM sat_cfdi s
                 JOIN invoices i ON LOWER(TRIM(i.uuid)) = LOWER(TRIM(s.uuid))
                      AND i.issuer_id = s.issuer_id
                 JOIN issuers iss ON iss.id = s.issuer_id
                WHERE s.cancellation_status = 'pending'
                LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    stats = {"checked": 0, "accepted": 0, "rejected": 0, "expired": 0, "still_pending": 0}
    for r in rows:
        r = dict(r)
        stats["checked"] += 1
        try:
            resp = facturapi_get_invoice(
                r["issuer_id"], r["facturapi_org_id"], r["facturapi_invoice_id"]
            )
        except Exception as exc:
            logger.warning("poll failed uuid=%s: %s", r["uuid"], exc)
            continue

        sat_status = (resp.get("status") or "").lower()
        new_status = _map_sat_status(sat_status, r["cancellation_requested_at"])

        if new_status == CancellationStatus.PENDING:
            stats["still_pending"] += 1
            continue

        _update_cancellation_state(r["issuer_id"], r["uuid"], new_status)
        insert_log(
            issuer_id=r["issuer_id"],
            user_id=r.get("cancellation_requested_by_user_id") or 0,
            cfdi_uuid=r["uuid"],
            motivo="",
            event=new_status.value,
            provider_response_json=str(resp),
        )
        stats[new_status.value] = stats.get(new_status.value, 0) + 1
    return stats


def _map_sat_status(sat_status: str, requested_at: str | None) -> CancellationStatus:
    """Map Facturapi status to our CancellationStatus enum."""
    if sat_status in ("canceled", "cancelled"):
        return CancellationStatus.ACCEPTED
    if sat_status == "rejected":
        return CancellationStatus.REJECTED
    # If >72h since request, SAT auto-accepts (expired)
    if requested_at:
        try:
            req = datetime.fromisoformat(requested_at)
            if req.tzinfo is None:
                req = req.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - req) > timedelta(hours=72):
                return CancellationStatus.EXPIRED
        except Exception:
            pass
    return CancellationStatus.PENDING


def _update_cancellation_state(issuer_id: int, uuid: str, status: CancellationStatus) -> None:
    """Persist the final cancellation status from polling."""
    now = datetime.now(timezone.utc).isoformat()
    cancelled_flag = 1 if status in (CancellationStatus.ACCEPTED, CancellationStatus.EXPIRED) else 0

    conn = db()
    try:
        conn.execute(
            """UPDATE sat_cfdi
                  SET cancellation_status = ?,
                      cancellation_finalized_at = ?,
                      updated_at = datetime('now')
                WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = 'issued'""",
            (status.value, now, issuer_id, uuid),
        )
        if status in (CancellationStatus.ACCEPTED, CancellationStatus.EXPIRED):
            conn.execute(
                "UPDATE sat_cfdi SET status = 'C', updated_at = datetime('now') WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = 'issued'",
                (issuer_id, uuid),
            )
        conn.execute(
            """UPDATE invoices SET cancelled = ?, cancel_status = ?
                WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)""",
            (cancelled_flag,
             "accepted" if cancelled_flag else "rejected",
             issuer_id, uuid),
        )
        conn.commit()
    finally:
        conn.close()

"""Facturapi webhook verification, idempotency, and dispatch.

Wire-level shape (verified against Facturapi dashboard sample events):
  - Body: raw bytes (JSON)
  - Signature header: Facturapi-Signature
  - Signature value: hex-encoded HMAC-SHA256 of the raw body using the
    endpoint signing secret. Compared with constant-time equality.

Dispatch table updates local DB. Handlers must be idempotent — Facturapi may
retry on 5xx, and we may re-dispatch the same payload during testing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from database import db

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "Facturapi-Signature"


def verify_signature(body: bytes, header_value: str | None, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verification of the raw request body."""
    if not header_value or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value.strip())


def is_duplicate(event_id: str) -> bool:
    if not event_id:
        return False
    conn = db()
    try:
        row = conn.execute(
            "SELECT 1 FROM facturapi_webhook_events WHERE event_id = ? LIMIT 1",
            (event_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def record_received(event_id: str, event_type: str, payload: dict) -> int:
    """Insert the event row, return the local PK. Raises if event_id duplicates."""
    conn = db()
    try:
        cur = conn.execute(
            """INSERT INTO facturapi_webhook_events
               (event_id, event_type, payload_json)
               VALUES (?, ?, ?)""",
            (event_id, event_type, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def mark_processed(row_id: int, error: str | None = None) -> None:
    conn = db()
    try:
        if error:
            conn.execute(
                "UPDATE facturapi_webhook_events SET process_error = ? WHERE id = ?",
                (error[:2000], row_id),
            )
        else:
            conn.execute(
                "UPDATE facturapi_webhook_events SET processed_at = datetime('now'), process_error = NULL WHERE id = ?",
                (row_id,),
            )
        conn.commit()
    finally:
        conn.close()


# ── Dispatch handlers ────────────────────────────────────────────────────────


def _handle_invoice_cancellation_accepted(payload: dict) -> None:
    """SAT accepted the cancellation. Mark local invoice as canceled."""
    invoice_id = (payload.get("data") or {}).get("id") or payload.get("id")
    if not invoice_id:
        logger.warning("invoice.cancellation_accepted without invoice id: %s", payload)
        return
    conn = db()
    try:
        conn.execute(
            """UPDATE invoices
               SET status = 'canceled', cancelled = 1
               WHERE facturapi_invoice_id = ?""",
            (invoice_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _handle_invoice_cancellation_rejected(payload: dict) -> None:
    """SAT rejected the cancellation. Reason is preserved in the event payload
    table for later inspection; we do not surface it in the invoices row yet
    because the schema has no column for it (avoid scope creep)."""
    data = payload.get("data") or {}
    invoice_id = data.get("id") or payload.get("id")
    if not invoice_id:
        logger.warning("invoice.cancellation_rejected without invoice id: %s", payload)
        return
    logger.warning(
        "Facturapi cancellation rejected for invoice %s: %s",
        invoice_id,
        data.get("cancellation_status") or data.get("reason") or "unknown",
    )


def _handle_invoice_status_updated(payload: dict) -> None:
    """Generic status change. Persist whatever Facturapi tells us."""
    data = payload.get("data") or {}
    invoice_id = data.get("id") or payload.get("id")
    status = data.get("status")
    if not invoice_id or not status:
        return
    conn = db()
    try:
        conn.execute(
            "UPDATE invoices SET status = ? WHERE facturapi_invoice_id = ?",
            (str(status)[:50], invoice_id),
        )
        conn.commit()
    finally:
        conn.close()


def _handle_manifest_signed(payload: dict) -> None:
    """Tenant signed their carta manifiesto. Mark the issuer ready for emission."""
    data = payload.get("data") or {}
    org_id = data.get("organization_id") or data.get("id") or payload.get("organization_id")
    if not org_id:
        logger.warning("manifest.signed without organization id: %s", payload)
        return
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET manifest_signed_at = datetime('now') WHERE facturapi_org_id = ?",
            (org_id,),
        )
        conn.commit()
    finally:
        conn.close()


_DISPATCH: dict[str, Any] = {
    "invoice.cancellation_accepted": _handle_invoice_cancellation_accepted,
    "invoice.cancellation_rejected": _handle_invoice_cancellation_rejected,
    "invoice.status_updated": _handle_invoice_status_updated,
    "manifest.signed": _handle_manifest_signed,
}


def dispatch(event: dict) -> None:
    """Route by event type. Unknown types are persisted but not processed."""
    event_type = (event.get("type") or "").strip()
    handler = _DISPATCH.get(event_type)
    if handler is None:
        logger.info("Facturapi webhook unhandled event type: %s", event_type)
        return
    handler(event)

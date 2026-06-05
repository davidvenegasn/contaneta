"""Facturapi webhook receiver.

Mirrors the Stripe pattern in routers/billing.py:
  - 503 if signing secret not configured
  - 400 if signature header missing or invalid
  - 200 on duplicate event (idempotent ack)
  - 200 on successful dispatch
  - 500 on handler exception so Facturapi retries (the row is kept with
    process_error set)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import HTTPException, Header, Request

from config import FACTURAPI_WEBHOOK_SECRET
from routers.api.webhooks import router
from services.facturapi import webhooks as fpi_webhooks

logger = logging.getLogger(__name__)


@router.post("/facturapi")
async def receive_facturapi_event(
    request: Request,
    signature: Optional[str] = Header(None, alias=fpi_webhooks.SIGNATURE_HEADER),
):
    if not FACTURAPI_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook no configurado")

    body = await request.body()

    if not fpi_webhooks.verify_signature(body, signature, FACTURAPI_WEBHOOK_SECRET):
        raise HTTPException(status_code=400, detail="Firma inválida")

    try:
        event = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Payload inválido")

    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Evento sin id o type")

    if fpi_webhooks.is_duplicate(event_id):
        return {"ok": True, "duplicate": True}

    row_id = fpi_webhooks.record_received(event_id, event_type, event)

    try:
        fpi_webhooks.dispatch(event)
    except Exception as e:
        logger.exception("Facturapi webhook dispatch failed (type=%s id=%s)", event_type, event_id)
        fpi_webhooks.mark_processed(row_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error procesando evento")

    fpi_webhooks.mark_processed(row_id)
    return {"ok": True}

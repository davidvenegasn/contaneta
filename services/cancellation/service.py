"""Public API for CFDI cancellation flow."""
import logging
from datetime import datetime, timezone
from typing import Optional

from database import db
from facturapi_client import FacturapiError
from facturapi_client import cancel_invoice as facturapi_cancel
from services.cancellation.log import insert_log
from services.cancellation.types import CancellationStatus, Motivo

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cancel_invoice(
    *,
    issuer_id: int,
    user_id: int,
    cfdi_uuid: str,
    motivo: Motivo,
    substitute_uuid: Optional[str] = None,
) -> dict:
    """Cancel a CFDI against SAT via Facturapi.

    For motivo "01", substitute_uuid is REQUIRED and must already be a timbered
    CFDI. The caller is responsible for emitting the substitute BEFORE calling
    this function.

    Returns dict with keys:
      - status: CancellationStatus value
      - sat_status: raw status from Facturapi response
      - requires_receptor_acceptance: bool

    Raises ValueError for invalid input, FacturapiError for SAT errors.
    """
    if motivo == Motivo.ERROR_CON_RELACION and not substitute_uuid:
        raise ValueError("Motivo 01 requiere folio de sustitución (substitute_uuid).")

    conn = db()
    try:
        inv = conn.execute(
            """SELECT id, uuid, total, facturapi_invoice_id, customer_rfc
                 FROM invoices
                WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1""",
            (issuer_id, cfdi_uuid.strip()),
        ).fetchone()
    finally:
        conn.close()

    if not inv:
        raise ValueError(f"CFDI {cfdi_uuid} no encontrado para emisor {issuer_id}.")
    inv = dict(inv)

    facturapi_id = inv.get("facturapi_invoice_id")
    if not facturapi_id:
        raise ValueError("Factura sin ID de FacturAPI — no se puede cancelar.")

    # Get org_id from issuer
    conn = db()
    try:
        issuer_row = conn.execute(
            "SELECT facturapi_org_id FROM issuers WHERE id = ?", (issuer_id,)
        ).fetchone()
    finally:
        conn.close()

    if not issuer_row or not dict(issuer_row).get("facturapi_org_id"):
        raise ValueError("Configuración de facturación no disponible.")
    org_id = dict(issuer_row)["facturapi_org_id"]

    insert_log(
        issuer_id=issuer_id, user_id=user_id, cfdi_uuid=cfdi_uuid,
        motivo=motivo.value, substitute_uuid=substitute_uuid, event="requested",
    )

    try:
        provider_resp = facturapi_cancel(
            issuer_id, org_id, facturapi_id, motivo.value,
            substitution=substitute_uuid,
        )
    except FacturapiError as exc:
        insert_log(
            issuer_id=issuer_id, user_id=user_id, cfdi_uuid=cfdi_uuid,
            motivo=motivo.value, event="failed", error_message=str(exc),
        )
        raise

    # Determine local status from provider response
    sat_status = (provider_resp.get("status") or "").lower()
    fa_cancel_status = (provider_resp.get("cancellation_status") or "").lower()
    requires_acceptance = float(inv.get("total") or 0) > 5000.0

    if sat_status in ("canceled", "cancelled"):
        new_status = CancellationStatus.ACCEPTED
    elif fa_cancel_status == "pending" or sat_status in ("pending", "in_process"):
        new_status = CancellationStatus.PENDING
    else:
        new_status = CancellationStatus.PENDING if requires_acceptance else CancellationStatus.ACCEPTED

    _persist_status(
        issuer_id=issuer_id,
        cfdi_uuid=cfdi_uuid,
        motivo=motivo.value,
        substitute_uuid=substitute_uuid,
        status=new_status,
        user_id=user_id,
    )

    if new_status == CancellationStatus.ACCEPTED:
        insert_log(
            issuer_id=issuer_id, user_id=user_id, cfdi_uuid=cfdi_uuid,
            motivo=motivo.value, event="accepted",
            provider_response_json=str(provider_resp),
        )

    return {
        "status": new_status.value,
        "sat_status": sat_status,
        "requires_receptor_acceptance": requires_acceptance,
    }


def substitute_and_cancel(
    *,
    issuer_id: int,
    user_id: int,
    original_uuid: str,
    new_cfdi_payload: dict,
) -> dict:
    """Two-step flow for motivo 01.

    1. Emit new CFDI with CfdiRelacionados TipoRelacion=04 pointing to original.
    2. Cancel original with motivo 01 referencing the new UUID.

    Returns dict with keys:
      - substitute_uuid: UUID of the newly timbered CFDI
      - cancellation_status: status of the original after cancellation
      - sat_status: raw response
    """
    from facturapi_client import create_invoice

    conn = db()
    try:
        orig = conn.execute(
            """SELECT facturapi_org_id FROM issuers WHERE id = ?""",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()
    if not orig:
        raise ValueError(f"Emisor {issuer_id} no encontrado.")
    org_id = dict(orig)["facturapi_org_id"]

    # Ensure substitution relationship is present
    rel = new_cfdi_payload.get("related_documents") or []
    has_sub = any(r.get("relationship") == "04" for r in rel)
    if not has_sub:
        new_cfdi_payload["related_documents"] = rel + [{
            "relationship": "04",
            "documents": [{"uuid": original_uuid}],
        }]

    # Step 1: emit substitute
    try:
        new_invoice = create_invoice(issuer_id, org_id, new_cfdi_payload)
    except FacturapiError:
        logger.exception("Substitute emission failed for original=%s", original_uuid)
        raise

    substitute_uuid = (new_invoice.get("uuid") or "").lower()
    if not substitute_uuid:
        raise RuntimeError("Facturapi no devolvió UUID para la sustitución.")

    # Step 2: cancel original referencing the new one
    try:
        cancel_result = cancel_invoice(
            issuer_id=issuer_id,
            user_id=user_id,
            cfdi_uuid=original_uuid,
            motivo=Motivo.ERROR_CON_RELACION,
            substitute_uuid=substitute_uuid,
        )
    except Exception as exc:
        logger.exception(
            "Substitute timbered (uuid=%s) but cancel of original failed", substitute_uuid
        )
        return {
            "substitute_uuid": substitute_uuid,
            "cancellation_status": "failed",
            "error": str(exc),
        }

    return {
        "substitute_uuid": substitute_uuid,
        "cancellation_status": cancel_result["status"],
        "sat_status": cancel_result["sat_status"],
        "requires_receptor_acceptance": cancel_result["requires_receptor_acceptance"],
    }


def _persist_status(
    *,
    issuer_id: int,
    cfdi_uuid: str,
    motivo: str,
    substitute_uuid: Optional[str],
    status: CancellationStatus,
    user_id: int,
) -> None:
    """Update sat_cfdi and invoices tables with cancellation status."""
    now = _now_iso()
    final_ts = now if status == CancellationStatus.ACCEPTED else None
    cancelled_flag = 1 if status == CancellationStatus.ACCEPTED else 0

    conn = db()
    try:
        conn.execute(
            """UPDATE sat_cfdi
                  SET cancellation_status = ?,
                      cancellation_motivo = ?,
                      cancellation_substitute_uuid = ?,
                      cancellation_requested_at = COALESCE(cancellation_requested_at, ?),
                      cancellation_finalized_at = COALESCE(cancellation_finalized_at, ?),
                      cancellation_requested_by_user_id = COALESCE(cancellation_requested_by_user_id, ?),
                      updated_at = datetime('now')
                WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = 'issued'""",
            (status.value, motivo, substitute_uuid, now, final_ts, user_id,
             issuer_id, cfdi_uuid),
        )
        if status == CancellationStatus.ACCEPTED:
            conn.execute(
                "UPDATE sat_cfdi SET status = 'C', updated_at = datetime('now') WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = 'issued'",
                (issuer_id, cfdi_uuid),
            )
        conn.execute(
            """UPDATE invoices
               SET cancelled = ?, cancel_status = ?, cancel_motive = ?,
                   cancelled_at = COALESCE(cancelled_at, ?),
                   replacement_uuid = COALESCE(replacement_uuid, ?)
               WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)""",
            (cancelled_flag,
             "accepted" if status == CancellationStatus.ACCEPTED else "pending",
             motivo, now, substitute_uuid, issuer_id, cfdi_uuid),
        )
        conn.commit()
    finally:
        conn.close()

"""Invoice cancellation route."""
import logging
from datetime import datetime

from fastapi import Body, Depends, HTTPException, Request

from database import db
from facturapi_client import FacturapiError
from facturapi_client import cancel_invoice as facturapi_cancel
from routers.api._helpers import _api_rate_check
from routers.deps import get_portal_issuer
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.http import ok

logger = logging.getLogger(__name__)


def register_invoices_cancel_routes(router):
    """Register invoice cancel route."""

    @router.post("/invoices/{invoice_uuid}/cancel")
    def api_invoices_cancel(
        request: Request,
        invoice_uuid: str,
        payload: dict = Body(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Cancel a stamped invoice via FacturAPI."""
        csrf_service.verify_api_csrf(request)
        _api_rate_check(request, "api_invoice_cancel", max_attempts=5, window=60.0)

        motive = (payload.get("motive") or "").strip()
        if motive not in ("01", "02", "03", "04"):
            raise HTTPException(status_code=400, detail="Motivo de cancelacion invalido.")

        issuer_id = issuer["id"]
        uuid_clean = (invoice_uuid or "").strip()
        if not uuid_clean:
            raise HTTPException(status_code=400, detail="UUID requerido.")

        conn = db()
        try:
            row = conn.execute(
                "SELECT id, facturapi_invoice_id, uuid, cancelled FROM invoices WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
                (issuer_id, uuid_clean),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Factura no encontrada en registros locales.")
        row = dict(row)
        if row.get("cancelled"):
            raise HTTPException(status_code=400, detail="Esta factura ya fue cancelada.")
        facturapi_id = row.get("facturapi_invoice_id")
        if not facturapi_id:
            raise HTTPException(status_code=400, detail="Factura sin ID de FacturAPI -- no se puede cancelar.")

        org_id = issuer.get("facturapi_org_id")
        if not org_id:
            raise HTTPException(status_code=400, detail="Configuracion de facturacion no disponible.")

        try:
            result = facturapi_cancel(issuer_id, org_id, facturapi_id, motive)
        except FacturapiError as fe:
            logger.warning("api_invoices_cancel FacturapiError: issuer_id=%s uuid=%s %s", issuer_id, uuid_clean, fe)
            raise HTTPException(status_code=400, detail=f"Error al cancelar en FacturAPI: {fe}")

        # Determine cancel status from FacturAPI response
        fa_status = (result.get("status") or "").lower()
        fa_cancel_status = (result.get("cancellation_status") or "").lower()

        if fa_status == "canceled":
            cancel_status = "accepted"
            cancelled_flag = 1
        elif fa_cancel_status == "pending":
            cancel_status = "pending"
            cancelled_flag = 0
        else:
            cancel_status = "accepted"
            cancelled_flag = 1

        now_iso = datetime.utcnow().isoformat(timespec="seconds")
        conn = db()
        try:
            conn.execute(
                """UPDATE invoices
                   SET cancelled = ?, cancel_status = ?, cancel_motive = ?, cancelled_at = ?
                   WHERE id = ? AND issuer_id = ?""",
                (cancelled_flag, cancel_status, motive, now_iso, row["id"], issuer_id),
            )
            if cancel_status == "accepted":
                conn.execute(
                    "UPDATE sat_cfdi SET status = 'C', updated_at = datetime('now') WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = 'issued'",
                    (issuer_id, uuid_clean),
                )
            conn.commit()
        finally:
            conn.close()

        log_action(request, "invoice_cancelled", issuer_id=issuer_id, uuid=uuid_clean[:36], motive=motive, cancel_status=cancel_status)
        return ok({"cancel_status": cancel_status, "uuid": uuid_clean})

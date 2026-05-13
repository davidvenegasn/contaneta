"""Foreign invoice CRUD routes."""
import logging
import os

from fastapi import Body, Depends, HTTPException, Query, Request
from typing import Optional

from database import db, db_rows
from routers.deps import get_portal_issuer
from services.auth import csrf as csrf_service
from services.http import ok, ok_list

logger = logging.getLogger(__name__)


def register_invoices_foreign_routes(router):
    """Register foreign invoice routes."""

    @router.post("/movements/invoice")
    def api_foreign_invoice_create(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        body: dict = Body(...),
    ):
        """Create a foreign invoice record."""
        csrf_service.verify_api_csrf(request)
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        from services.invoices import foreign_invoices as fi
        fi.ensure_table()
        tipo = (body.get("tipo") or "").strip().upper()
        fecha = (body.get("fecha") or "").strip()
        invoice_number = (body.get("invoice_number") or "").strip()
        empresa = (body.get("empresa") or "").strip()
        descripcion = (body.get("descripcion") or "").strip()
        moneda = (body.get("moneda") or "USD").strip()
        monto_original = body.get("monto_original")
        tipo_cambio = body.get("tipo_cambio")
        if not all([tipo, fecha, invoice_number, empresa, descripcion, monto_original, tipo_cambio]):
            raise HTTPException(status_code=422, detail="Campos requeridos: tipo, fecha, invoice_number, empresa, descripcion, monto_original, tipo_cambio")
        try:
            monto_original = float(monto_original)
            tipo_cambio = float(tipo_cambio)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="monto_original y tipo_cambio deben ser numericos")
        if monto_original <= 0 or tipo_cambio <= 0:
            raise HTTPException(status_code=422, detail="monto y tipo de cambio deben ser mayores a 0")
        pais = (body.get("pais") or "").strip() or None
        tax_id = (body.get("tax_id") or "").strip() or None
        forma_pago = (body.get("forma_pago") or "").strip() or None
        referencia_pago = (body.get("referencia_pago") or "").strip() or None
        notas = (body.get("notas") or "").strip() or None
        row = fi.create(
            issuer_id, tipo, fecha, invoice_number, empresa, descripcion,
            moneda, monto_original, tipo_cambio, forma_pago=forma_pago,
            pais=pais, tax_id=tax_id, referencia_pago=referencia_pago, notas=notas,
        )
        return ok(row)


    @router.get("/invoices/foreign")
    def api_foreign_invoices_list(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: Optional[str] = Query(None),
        tipo: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        """List foreign invoices for the current issuer."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        from services.invoices import foreign_invoices as fi
        fi.ensure_table()
        items = fi.list_invoices(issuer_id, period_month=ym, tipo=tipo, limit=limit, offset=offset)
        total = fi.count_invoices(issuer_id, period_month=ym)
        return ok_list(items, total)


    @router.delete("/invoices/foreign/{invoice_id}")
    def api_foreign_invoice_delete(invoice_id: int, request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Delete a foreign invoice."""
        csrf_service.verify_api_csrf(request)
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        from services.invoices import foreign_invoices as fi
        fi.ensure_table()
        conn = db()
        try:
            cur = conn.execute("DELETE FROM foreign_invoices WHERE id = ? AND issuer_id = ?", (invoice_id, issuer_id))
            conn.commit()
            deleted = cur.rowcount > 0
        finally:
            conn.close()
        if not deleted:
            raise HTTPException(status_code=404, detail="Invoice no encontrado")
        return ok({"deleted": True})


    @router.get("/invoices/foreign/{invoice_id}/pdf")
    def api_foreign_invoice_pdf(invoice_id: int, request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Serve the stored PDF for a foreign invoice (opens in browser)."""
        from fastapi.responses import FileResponse
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        rows = db_rows("SELECT archivo FROM foreign_invoices WHERE id = ? AND issuer_id = ?", (invoice_id, issuer_id))
        if not rows or not rows[0].get("archivo"):
            raise HTTPException(status_code=404, detail="PDF no disponible")
        archivo_rel = rows[0]["archivo"]
        storage_root = os.environ.get("APP_STORAGE_PATH", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")
        abs_path = os.path.normpath(os.path.join(storage_root, archivo_rel))
        # Security: ensure path is under storage_root
        if not abs_path.startswith(os.path.normpath(storage_root)):
            raise HTTPException(status_code=403, detail="Acceso denegado")
        if not os.path.isfile(abs_path):
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        from services import file_access_log
        file_access_log.log_file_access(
            request=request, action="view_foreign_invoice_pdf",
            issuer_id=issuer_id, user_id=getattr(getattr(request, "state", None), "user_id", None),
            file_path=archivo_rel,
            entity="foreign_invoice", entity_id=str(invoice_id),
        )
        return FileResponse(abs_path, media_type="application/pdf", headers={"Content-Disposition": "inline"})

"""Audit log UI — paginated view of action_log entries (owner/admin only)."""
import csv
import io
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.action_log import get_audit_log, get_distinct_actions

logger = logging.getLogger(__name__)

# Human-readable labels for common actions
ACTION_LABELS = {
    "login": "Inicio de sesión",
    "invoice_created": "Factura creada",
    "invoice_cancelled": "Factura cancelada",
    "egreso_created": "Nota de crédito",
    "rep_created": "REP creado",
    "download_xml": "Descarga XML",
    "download_pdf": "Descarga PDF",
    "credentials_uploaded": "FIEL subida",
    "credentials_validated": "FIEL validada",
    "sat_sync_started": "Sincronización SAT",
    "sat_full_resync": "Resync SAT completo",
    "sat_history_sync": "Sync histórico SAT",
    "plan_checkout_started": "Checkout iniciado",
    "plan_changed": "Plan cambiado",
    "plan_period_updated": "Periodo renovado",
    "payment_failed": "Pago fallido",
    "month_close_status_change": "Cierre mensual",
    "month_close_upload": "Carga cierre mensual",
    "bank_statement_ingest": "Estado de cuenta",
    "bank_reconcile_run": "Conciliación bancaria",
    "bank_preview_commit": "Movimientos confirmados",
    "bank_pdf_to_excel": "PDF a Excel",
    "quotation_pdf": "Cotización PDF",
    "product_converted_from_observation": "Producto convertido",
}

# Icon SVGs (small, inline) for common action categories
ACTION_ICONS = {
    "login": "user",
    "invoice_created": "file-plus",
    "invoice_cancelled": "file-x",
    "egreso_created": "file-minus",
    "rep_created": "credit-card",
    "download_xml": "download",
    "download_pdf": "download",
    "credentials_uploaded": "key",
    "credentials_validated": "shield",
    "sat_sync_started": "refresh",
    "plan_changed": "star",
    "payment_failed": "alert",
    "month_close_status_change": "lock",
    "bank_statement_ingest": "upload",
    "bank_reconcile_run": "check-circle",
}

PAGE_SIZE = 30


def register_audit_log_routes(router: APIRouter, templates):
    """Register GET /audit-log and GET /audit-log/csv routes."""

    @router.get("/audit-log")
    async def portal_audit_log(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        action: str = Query(None),
        user_id: int = Query(None),
        date_from: str = Query(None),
        date_to: str = Query(None),
        page: int = Query(1, ge=1),
    ):
        role = getattr(request.state, "membership_role", "")
        if role not in ("owner", "admin"):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Solo owner/admin puede ver el audit log")

        issuer_id = issuer["id"]
        offset = (page - 1) * PAGE_SIZE

        rows, total = get_audit_log(
            issuer_id,
            action=action,
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            limit=PAGE_SIZE,
            offset=offset,
        )

        # Enrich rows with labels and icons
        for row in rows:
            row["action_label"] = ACTION_LABELS.get(row["action"], row["action"])
            row["icon_type"] = ACTION_ICONS.get(row["action"], "activity")
            # Parse details from meta_json or details column
            details = {}
            if row.get("meta_json"):
                try:
                    details = json.loads(row["meta_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if not details and row.get("details"):
                details = {"info": row["details"]}
            if row.get("entity_id"):
                details["entity_id"] = row["entity_id"]
            row["details"] = details
            row["ip_address"] = row.get("ip", "")

        distinct_actions = get_distinct_actions(issuer_id)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

        return render_portal(
            templates,
            request,
            issuer=issuer,
            template_name="portal_audit_log.html",
            active_page="audit_log",
            title="Registro de actividad",
            entries=rows,
            total=total,
            page=page,
            total_pages=total_pages,
            distinct_actions=distinct_actions,
            action_labels=ACTION_LABELS,
            current_action=action,
            current_user_id=user_id,
            current_date_from=date_from or "",
            current_date_to=date_to or "",
        )

    @router.get("/audit-log/csv")
    async def portal_audit_log_csv(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        action: str = Query(None),
        user_id: int = Query(None),
        date_from: str = Query(None),
        date_to: str = Query(None),
    ):
        role = getattr(request.state, "membership_role", "")
        if role not in ("owner", "admin"):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Solo owner/admin")

        issuer_id = issuer["id"]
        rows, _ = get_audit_log(
            issuer_id,
            action=action,
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            limit=5000,
            offset=0,
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Fecha", "Acción", "Usuario", "IP", "Detalles"])
        for row in rows:
            details = row.get("meta_json") or row.get("details") or ""
            writer.writerow([
                row.get("created_at", ""),
                ACTION_LABELS.get(row.get("action", ""), row.get("action", "")),
                row.get("user_email", ""),
                row.get("ip", ""),
                details,
            ])

        output.seek(0)
        filename = f"audit_log_{issuer_id}_{datetime.now().strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

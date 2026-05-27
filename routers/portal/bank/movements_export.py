"""Bank movements export and reconcile routes."""
import io
import logging
from typing import Optional

from fastapi import Depends, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException

from database import db, has_column
from routers.deps import get_portal_issuer
from routers.portal._helpers import _strip_date_from_description, ym_now
from routers.portal.bank._bank_helpers import ensure_bank_movements_table
from services import audit
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.auth import rate_limit as rate_limit_service
from services.ym_helpers import sanitize_ym

logger = logging.getLogger(__name__)


def register_bank_movements_export_routes(router, templates):
    """Register bank movements export and reconcile routes."""

    @router.get("/bank/movements/export")
    def portal_bank_movements_export(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: Optional[str] = Query(None),
        statement_id: Optional[str] = Query(None),
        tipo: Optional[str] = Query(None),
        categoria: Optional[str] = Query(None),
        cfdi_match_status: Optional[str] = Query(None),
        match_filter: Optional[str] = Query(None),
        search: Optional[str] = Query(None),
        hide_own_transfers: Optional[int] = Query(None),
        hide_financial: Optional[int] = Query(None),
        only_real_expenses: Optional[int] = Query(None),
    ):
        """Export filtered movements to XLSX."""
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        period_month = sanitize_ym(ym or "", ym_now())
        conn = db()
        conn.row_factory = lambda cursor, row: dict(zip([c[0] for c in cursor.description], row))
        try:
            ensure_bank_movements_table(conn)
            params: list = [issuer_id]
            where_clauses = ["issuer_id = ?"]
            if has_column(conn, "bank_movements", "period_month"):
                where_clauses.append("period_month = ?")
                params.append(period_month)
            if statement_id:
                sid = statement_id.strip()
                if sid.startswith("stmt_"):
                    try:
                        bid = int(sid.replace("stmt_", ""))
                        if has_column(conn, "bank_movements", "bank_statement_id"):
                            where_clauses.append("bank_statement_id = ?")
                            params.append(bid)
                        else:
                            where_clauses.append("statement_file_id = ?")
                            params.append(sid)
                    except ValueError:
                        where_clauses.append("statement_file_id = ?")
                        params.append(sid)
                else:
                    if has_column(conn, "bank_movements", "statement_file_id"):
                        where_clauses.append("statement_file_id = ?")
                        params.append(sid)
            if tipo:
                where_clauses.append("tipo = ?")
                params.append(tipo.strip().upper())
            if hide_own_transfers:
                where_clauses.append("COALESCE(categoria,'') != 'CUENTA_PROPIA'")
            if hide_financial:
                where_clauses.append("COALESCE(categoria,'') NOT IN ('FINANCIERO_PAGO_TARJETA','MOVIMIENTO_FINANCIERO','COMISIONES BANCARIAS','COMISIONES_BANCARIAS','COMISION_BANCARIA')")
            if only_real_expenses:
                where_clauses.append(
                    "COALESCE(categoria,'') NOT IN ('CUENTA_PROPIA','FINANCIERO_PAGO_TARJETA','MOVIMIENTO_FINANCIERO','COMISIONES BANCARIAS','COMISIONES_BANCARIAS','COMISION_BANCARIA','TRASPASO_PROPIO')"
                )
            if cfdi_match_status and has_column(conn, "bank_movements", "cfdi_match_status"):
                where_clauses.append("cfdi_match_status = ?")
                params.append(cfdi_match_status.strip().lower())
            if search and search.strip():
                from services.db_utils import escape_like
                q = f"%{escape_like(search.strip())}%"
                if has_column(conn, "bank_movements", "raw_description"):
                    where_clauses.append("(descripcion LIKE ? ESCAPE '\\' OR contraparte_hint LIKE ? ESCAPE '\\' OR raw_description LIKE ? ESCAPE '\\')")
                    params.extend([q, q, q])
                else:
                    where_clauses.append("(descripcion LIKE ? ESCAPE '\\' OR contraparte_hint LIKE ? ESCAPE '\\')")
                    params.extend([q, q])
            where_sql = " AND ".join(where_clauses)
            rows = conn.execute(
                f"SELECT fecha, descripcion, tipo, deposito, retiro, saldo, categoria, contraparte_hint, rfc_encontrado FROM bank_movements WHERE {where_sql} ORDER BY fecha DESC, id DESC",
                params,
            ).fetchall()
        finally:
            conn.close()

        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Movimientos"
        headers = ["Fecha", "Descripcion", "Tipo", "Deposito", "Retiro", "Saldo", "Categoria", "Contraparte", "RFC"]
        ws.append(headers)
        for r in rows:
            ws.append([
                r.get("fecha"),
                _strip_date_from_description(r.get("descripcion")) or r.get("descripcion", ""),
                r.get("tipo"),
                r.get("deposito"),
                r.get("retiro"),
                r.get("saldo"),
                r.get("categoria"),
                r.get("contraparte_hint"),
                r.get("rfc_encontrado"),
            ])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        filename = f"movimientos_{period_month}.xlsx"
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/bank/movements/reconcile", response_class=RedirectResponse)
    def portal_bank_movements_reconcile(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Form(...),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF invalido o expirado")
        if rate_limit_service.is_rate_limited(request, "bank_reconcile"):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un minuto.")
        issuer_id = int(issuer.get("id") or 0)
        from services.bank import bank_cfdi_matching as bank_cfdi_matching_service

        bank_cfdi_matching_service.refresh_suggestions_for_month(issuer_id, ym)
        audit.log(
            action="bank_reconcile_run",
            user_id=getattr(request.state, "user_id", 0) or 0,
            issuer_id=issuer_id,
            request=request,
            entity="bank_movements",
            entity_id=ym,
        )
        log_action(request, "bank_reconcile_run", issuer_id=issuer_id, ym=ym)
        return RedirectResponse(url=f"/portal/bank/movements?ym={ym}", status_code=302)

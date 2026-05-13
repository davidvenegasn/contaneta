"""Bank statements list page."""
import json
import logging

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException

from database import db, has_column, table_exists
from routers.deps import get_portal_issuer
from routers.portal._helpers import _db_row_to_dict, render_portal
from routers.portal.bank._bank_helpers import ensure_bank_exports_table, ensure_bank_movements_table

logger = logging.getLogger(__name__)


def register_bank_statements_list_routes(router, templates):
    """Register bank statements list routes."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/bank/statements", response_class=HTMLResponse)
    def portal_bank_statements(request: Request, issuer: dict = Depends(get_portal_issuer)):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        statements: list = []
        conn = None
        try:
            conn = db()
            conn.row_factory = lambda cursor, row: dict(zip([c[0] for c in cursor.description], row))
            ensure_bank_exports_table(conn)
            ensure_bank_movements_table(conn)
            rows = conn.execute(
                "SELECT file_id, pdf_path, xlsx_path, meta_json, created_at FROM bank_pdf_exports WHERE issuer_id = ? ORDER BY created_at DESC",
                (issuer_id,),
            ).fetchall()
            statements = []
            for r in rows:
                r = _db_row_to_dict(r)
                meta = {}
                if r.get("meta_json"):
                    try:
                        meta = json.loads(r["meta_json"] or "{}")
                    except Exception:
                        pass
                period_start = meta.get("period_start") or ""
                period_end = meta.get("period_end") or ""
                bank_name = meta.get("bank_name") or "\u2014"
                account_last4 = meta.get("account_last4") or "\u2014"
                movements_count = int(meta.get("movements_count") or 0)
                total_gastos = float(meta.get("gastos_total") or meta.get("total_gastos") or 0)
                total_ingresos = float(meta.get("ingresos_total") or meta.get("total_ingresos") or 0)
                period_label = f"{period_start} \u2013 {period_end}" if (period_start or period_end) else "\u2014"
                statements.append({
                    "file_id": r["file_id"],
                    "statement_key": r["file_id"],
                    "created_at": r["created_at"] or "",
                    "period_label": period_label,
                    "bank_name": bank_name,
                    "account_last4": account_last4,
                    "movements_count": movements_count,
                    "total_gastos": total_gastos,
                    "total_ingresos": total_ingresos,
                    "source": "export",
                })
            if table_exists(conn, "bank_statements"):
                has_pm = has_column(conn, "bank_statements", "period_month")
                has_tm = has_column(conn, "bank_statements", "total_movements")
                if has_pm and has_tm:
                    st_rows = conn.execute(
                        "SELECT id, period_month, bank_name, account_last4, total_movements, status, created_at FROM bank_statements WHERE issuer_id = ? ORDER BY created_at DESC",
                        (issuer_id,),
                    ).fetchall()
                else:
                    st_rows = conn.execute(
                        "SELECT id, bank_name, account_last4, period_start, period_end, created_at FROM bank_statements WHERE issuer_id = ? ORDER BY created_at DESC",
                        (issuer_id,),
                    ).fetchall()
                for r in st_rows:
                    r = _db_row_to_dict(r)
                    if has_pm:
                        pm = r.get("period_month") or ""
                    else:
                        pm = (r.get("period_start") or "")[:7]
                    period_label = pm if pm else ((r.get("created_at") or "")[:7] or "\u2014")
                    statements.append({
                        "file_id": None,
                        "statement_key": f"stmt_{r['id']}",
                        "statement_id": r["id"],
                        "created_at": r.get("created_at") or "",
                        "period_label": period_label,
                        "bank_name": r.get("bank_name") or "\u2014",
                        "account_last4": r.get("account_last4") or "\u2014",
                        "movements_count": int(r.get("total_movements") or 0) if has_tm else 0,
                        "total_gastos": 0,
                        "total_ingresos": 0,
                        "source": "ingest",
                    })
            statements.sort(key=lambda x: (x.get("created_at") or ""), reverse=True)
        except Exception as e:
            logger.warning("portal bank/statements: error cargando lista (%s), mostrando vacio", e)
            statements = []
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_bank_statements.html",
            active_page="bank_statements",
            title="Estados de cuenta",
            statements=statements,
        )

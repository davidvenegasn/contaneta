"""Bank movements list page — the main movements view with filters and KPIs."""
import json
import logging
from typing import Optional

from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException

from database import db, has_column, table_exists
from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    MAX_LIST_OFFSET,
    _db_row_to_dict,
    _strip_date_from_description,
    render_portal,
    ym_now,
)
from routers.portal.bank._bank_helpers import ensure_bank_exports_table, ensure_bank_movements_table
from services.auth import csrf as csrf_service
from services.bank.bank_own_accounts import reclassify_own_transfers_by_rfc
from services.ym_helpers import sanitize_ym, shift_ym, ym_to_label

logger = logging.getLogger(__name__)


def register_bank_movements_list_routes(router, templates):
    """Register bank movements list routes."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.get("/movimientos", response_class=HTMLResponse)
    @router.get("/bank/movements", response_class=HTMLResponse)
    def portal_bank_movements(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        ym: Optional[str] = Query(None, description="Mes YYYY-MM (selector como emitidas/recibidas)"),
        statement_id: Optional[str] = Query(None, description="Filtrar por estado de cuenta (file_id o stmt_N)"),
        period_month: Optional[str] = Query(None, description="YYYY-MM (legacy, usa ym si no viene)"),
        tipo: Optional[str] = Query(None, description="INGRESO, GASTO, INFO"),
        categoria: Optional[str] = Query(None),
        cfdi_match_status: Optional[str] = Query(None, description="pending, suggested, confirmed, rejected"),
        match_filter: Optional[str] = Query(None, description="none|probable (conciliacion)"),
        min_confidence: Optional[int] = Query(None, ge=0, le=100),
        search: Optional[str] = Query(None),
        hide_own_transfers: Optional[int] = Query(None, description="1 para ocultar traspasos propios"),
        hide_financial: Optional[int] = Query(None, description="1 para ocultar pagos/cargos financieros"),
        only_real_expenses: Optional[int] = Query(None, description="1 para solo gastos reales"),
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0, le=MAX_LIST_OFFSET),
    ):
        issuer_id = int(issuer.get("id") or 0)
        if issuer_id <= 0:
            raise HTTPException(status_code=401, detail="Sesion invalida")
        # Mes: prioridad ym (selector) > period_month (legacy) > mes actual
        explicit_ym = sanitize_ym(ym or period_month or "", "")
        period_month = explicit_ym or ym_now()
        movements: list = []
        total_count = 0
        sum_ingresos = 0.0
        sum_gastos = 0.0
        cuenta_propia_entradas = 0.0
        cuenta_propia_salidas = 0.0
        statements_opt: list = []
        months_with_movements: list[dict] = []
        conn = None
        try:
            conn = db()
            conn.row_factory = lambda cursor, row: dict(zip([c[0] for c in cursor.description], row))
            ensure_bank_movements_table(conn)
            ensure_bank_exports_table(conn)
            # Heal pass: reclassify old movements matching issuer RFC
            _heal_rfc = (issuer.get("rfc") or "").strip().upper()
            if _heal_rfc:
                reclassify_own_transfers_by_rfc(conn, issuer_id, _heal_rfc)
            has_matches = table_exists(conn, "bank_invoice_matches") and table_exists(conn, "sat_cfdi")

            params: list = [issuer_id]
            where_clauses = ["issuer_id = ?"]

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
            if has_column(conn, "bank_movements", "period_month"):
                where_clauses.append("period_month = ?")
                params.append(period_month)
            if tipo:
                where_clauses.append("tipo = ?")
                params.append(tipo.strip().upper())
            if categoria:
                where_clauses.append("categoria = ?")
                params.append(categoria.strip())
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
            if match_filter and has_matches:
                mf = (match_filter or "").strip().lower()
                if mf == "probable":
                    where_clauses.append(
                        """EXISTS (
                             SELECT 1 FROM bank_invoice_matches bim
                             WHERE bim.issuer_id = bank_movements.issuer_id
                               AND bim.bank_movement_id = bank_movements.id
                               AND bim.status IN ('suggested','confirmed')
                               AND COALESCE(bim.score,0) >= 80
                           )"""
                    )
                elif mf == "revisar":
                    where_clauses.append(
                        """EXISTS (
                             SELECT 1 FROM bank_invoice_matches bim
                             WHERE bim.issuer_id = bank_movements.issuer_id
                               AND bim.bank_movement_id = bank_movements.id
                               AND bim.status IN ('suggested','confirmed')
                               AND COALESCE(bim.score,0) BETWEEN 50 AND 79
                           )"""
                    )
                elif mf == "none":
                    where_clauses.append(
                        """NOT EXISTS (
                             SELECT 1 FROM bank_invoice_matches bim
                             WHERE bim.issuer_id = bank_movements.issuer_id
                               AND bim.bank_movement_id = bank_movements.id
                               AND bim.status IN ('suggested','confirmed')
                               AND COALESCE(bim.score,0) >= 50
                           )"""
                    )
            if min_confidence is not None:
                where_clauses.append("confidence_score >= ?")
                params.append(min_confidence)
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

            total_count_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM bank_movements WHERE {where_sql}",
                params,
            ).fetchone()
            total_count = int(_db_row_to_dict(total_count_row).get("c", 0) or 0)

            if has_column(conn, "bank_movements", "impacta_contabilidad"):
                _impacta_filter = " AND COALESCE(impacta_contabilidad, 1) = 1"
            elif has_column(conn, "bank_movements", "categoria"):
                _impacta_filter = " AND COALESCE(categoria,'') != 'CUENTA_PROPIA'"
            else:
                _impacta_filter = ""
            sum_row = conn.execute(
                f"SELECT COALESCE(SUM(deposito), 0) AS ing, COALESCE(SUM(retiro), 0) AS gas FROM bank_movements WHERE {where_sql}{_impacta_filter}",
                params,
            ).fetchone()
            sum_row_d = _db_row_to_dict(sum_row)
            sum_ingresos = float(sum_row_d.get("ing", 0) or 0)
            sum_gastos = float(sum_row_d.get("gas", 0) or 0)

            # Conciliation stats (always for full period, ignoring user filters)
            concil_stats = {"matched": 0, "unmatched": 0, "total_real": 0}
            try:
                if has_column(conn, "bank_movements", "impacta_contabilidad"):
                    _concil_base = "issuer_id = ? AND COALESCE(impacta_contabilidad, 1) = 1"
                elif has_column(conn, "bank_movements", "categoria"):
                    _concil_base = "issuer_id = ? AND COALESCE(categoria,'') != 'CUENTA_PROPIA'"
                else:
                    _concil_base = "issuer_id = ?"
                _concil_params: list = [issuer_id]
                if has_column(conn, "bank_movements", "period_month"):
                    _concil_base += " AND period_month = ?"
                    _concil_params.append(period_month)
                if table_exists(conn, "bank_invoice_matches"):
                    matched_row = conn.execute(
                        f"""SELECT COUNT(*) AS n FROM bank_movements
                            WHERE {_concil_base}
                            AND EXISTS (
                              SELECT 1 FROM bank_invoice_matches bim
                              WHERE bim.issuer_id = bank_movements.issuer_id
                                AND bim.bank_movement_id = bank_movements.id
                                AND bim.status IN ('suggested','confirmed')
                                AND COALESCE(bim.score,0) >= 80
                            )""",
                        _concil_params,
                    ).fetchone()
                    concil_stats["matched"] = int(_db_row_to_dict(matched_row).get("n", 0) or 0)
                total_real_row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM bank_movements WHERE {_concil_base}",
                    _concil_params,
                ).fetchone()
                concil_stats["total_real"] = int(_db_row_to_dict(total_real_row).get("n", 0) or 0)
                concil_stats["unmatched"] = concil_stats["total_real"] - concil_stats["matched"]
            except Exception:
                pass

            # Cuenta propia sums (always for issuer + period, ignoring other filters)
            _cp_where = "issuer_id = ? AND COALESCE(categoria,'') = 'CUENTA_PROPIA'"
            _cp_params: list = [issuer_id]
            if has_column(conn, "bank_movements", "period_month"):
                _cp_where += " AND period_month = ?"
                _cp_params.append(period_month)
            cp_row = conn.execute(
                f"SELECT COALESCE(SUM(deposito), 0) AS cp_ing, COALESCE(SUM(retiro), 0) AS cp_gas FROM bank_movements WHERE {_cp_where}",
                _cp_params,
            ).fetchone()
            cp_row_d = _db_row_to_dict(cp_row)
            cuenta_propia_entradas = float(cp_row_d.get("cp_ing", 0) or 0)
            cuenta_propia_salidas = float(cp_row_d.get("cp_gas", 0) or 0)

            # Construir SELECT solo con columnas que existan (compatibilidad con distintos esquemas)
            sel = ["id"]
            if has_column(conn, "bank_movements", "statement_file_id"):
                sel.append("statement_file_id")
            elif has_column(conn, "bank_movements", "statement_id"):
                sel.append("statement_id AS statement_file_id")
            sel.append("fecha")
            if has_column(conn, "bank_movements", "descripcion"):
                sel.append("descripcion")
            elif has_column(conn, "bank_movements", "descripcion_norm"):
                sel.append("descripcion_norm AS descripcion")
            else:
                sel.append("descripcion_raw AS descripcion")
            sel.extend(["deposito", "retiro", "saldo", "tipo", "categoria", "metodo_hint", "contraparte_hint"])
            if has_column(conn, "bank_movements", "rfc_encontrado"):
                sel.append("rfc_encontrado")
            elif has_column(conn, "bank_movements", "rfc_detectado"):
                sel.append("rfc_detectado AS rfc_encontrado")
            sel.append("confidence_score")
            if has_column(conn, "bank_movements", "bank_statement_id"):
                sel.append("bank_statement_id")
                sel.append("(SELECT bs.bank_name FROM bank_statements bs WHERE bs.id = bank_movements.bank_statement_id LIMIT 1) AS statement_bank_name")
            if has_column(conn, "bank_movements", "cfdi_match_status"):
                sel.append("cfdi_match_status")
            if has_matches:
                sel.append(
                    """(
                        SELECT sc.uuid
                        FROM bank_invoice_matches bim
                        JOIN sat_cfdi sc ON sc.id = bim.cfdi_id
                        WHERE bim.issuer_id = bank_movements.issuer_id
                          AND bim.bank_movement_id = bank_movements.id
                          AND bim.status IN ('suggested','confirmed')
                        ORDER BY bim.score DESC, bim.id DESC
                        LIMIT 1
                    ) AS probable_cfdi_uuid"""
                )
                sel.append(
                    """(
                        SELECT bim.score
                        FROM bank_invoice_matches bim
                        WHERE bim.issuer_id = bank_movements.issuer_id
                          AND bim.bank_movement_id = bank_movements.id
                          AND bim.status IN ('suggested','confirmed')
                        ORDER BY bim.score DESC, bim.id DESC
                        LIMIT 1
                    ) AS probable_cfdi_score"""
                )
                sel.append(
                    """(
                        SELECT bim.status
                        FROM bank_invoice_matches bim
                        WHERE bim.issuer_id = bank_movements.issuer_id
                          AND bim.bank_movement_id = bank_movements.id
                          AND bim.status IN ('suggested','confirmed')
                        ORDER BY bim.score DESC, bim.id DESC
                        LIMIT 1
                    ) AS probable_cfdi_status"""
                )
            select_cols = ", ".join(sel)
            params_ext = params + [limit, offset]
            movements = conn.execute(
                f"SELECT {select_cols} FROM bank_movements WHERE {where_sql} ORDER BY fecha DESC, id DESC LIMIT ? OFFSET ?",
                params_ext,
            ).fetchall()
            movements = [_db_row_to_dict(r) for r in movements]
            for row in movements:
                row.setdefault("fecha", None)
                row.setdefault("descripcion", None)
                row.setdefault("deposito", None)
                row.setdefault("retiro", None)
                row.setdefault("saldo", None)
                row.setdefault("tipo", None)
                row.setdefault("categoria", None)
                row.setdefault("metodo_hint", None)
                row.setdefault("contraparte_hint", None)
                row.setdefault("rfc_encontrado", None)
                row.setdefault("confidence_score", None)
                row.setdefault("cfdi_match_status", None)
                row.setdefault("bank_statement_id", None)
                row.setdefault("statement_bank_name", None)
                row.setdefault("probable_cfdi_uuid", None)
                row.setdefault("probable_cfdi_score", None)
                row.setdefault("probable_cfdi_status", None)
                # Asegurar que montos sean numericos para el formato en plantilla
                for key in ("deposito", "retiro", "saldo", "confidence_score", "probable_cfdi_score"):
                    if row.get(key) is not None and row[key] != "":
                        try:
                            if key == "confidence_score":
                                row[key] = int(float(row[key]))
                            elif key == "probable_cfdi_score":
                                row[key] = int(float(row[key]))
                            else:
                                row[key] = float(row[key])
                        except (TypeError, ValueError):
                            row[key] = None if key != "confidence_score" else 0
                # Concepto = descripcion sin prefijo de fecha (igual que en convertir edo. de cuenta)
                row["concepto"] = _strip_date_from_description(row.get("descripcion")) or (row.get("descripcion") or "").strip()

            statements_opt = []
            for r in conn.execute(
                "SELECT file_id, meta_json, created_at FROM bank_pdf_exports WHERE issuer_id = ? ORDER BY created_at DESC",
                (issuer_id,),
            ).fetchall():
                r = _db_row_to_dict(r)
                meta = {}
                if r.get("meta_json"):
                    try:
                        meta = json.loads(r["meta_json"] or "{}")
                    except Exception:
                        pass
                p_start = meta.get("period_start") or ""
                p_end = meta.get("period_end") or ""
                if p_start or p_end:
                    label = f"{p_start} \u2013 {p_end}"
                else:
                    label = (r.get("created_at") or "")[:16] or (r["file_id"][:12] + "\u2026")
                statements_opt.append({"statement_id": r["file_id"], "label": label})
            if table_exists(conn, "bank_statements"):
                has_pm = has_column(conn, "bank_statements", "period_month")
                if has_pm:
                    st_opt_rows = conn.execute(
                        "SELECT id, period_month, total_movements FROM bank_statements WHERE issuer_id = ? ORDER BY created_at DESC",
                        (issuer_id,),
                    ).fetchall()
                else:
                    st_opt_rows = conn.execute(
                        "SELECT id, period_start FROM bank_statements WHERE issuer_id = ? ORDER BY created_at DESC",
                        (issuer_id,),
                    ).fetchall()
                for r in st_opt_rows:
                    r = _db_row_to_dict(r)
                    if has_pm:
                        pm = r.get("period_month") or ""
                    else:
                        pm = (r.get("period_start") or "")[:7]
                    label = pm if pm else f"Estado #{r['id']}"
                    statements_opt.append({"statement_id": f"stmt_{r['id']}", "label": label})
            # Meses con movimientos (para el selector como emitidas/recibidas)
            if has_column(conn, "bank_movements", "period_month"):
                months_rows = conn.execute(
                    """SELECT period_month AS ym, COUNT(*) AS n FROM bank_movements
                       WHERE issuer_id = ? AND period_month IS NOT NULL AND TRIM(period_month) != ''
                       GROUP BY period_month ORDER BY period_month DESC""",
                    (issuer_id,),
                ).fetchall()
                for r in months_rows:
                    r = _db_row_to_dict(r)
                    ym_val = r.get("ym") or ""
                    if ym_val:
                        months_with_movements.append({"ym": ym_val, "n": int(r.get("n") or 0), "label": ym_to_label(ym_val)})
            else:
                # Sin columna period_month: usar meses de bank_statements si existen
                if table_exists(conn, "bank_statements") and has_column(conn, "bank_statements", "period_month"):
                    months_rows = conn.execute(
                        """SELECT period_month AS ym, COALESCE(SUM(total_movements), 0) AS n FROM bank_statements
                           WHERE issuer_id = ? AND period_month IS NOT NULL AND TRIM(period_month) != ''
                           GROUP BY period_month ORDER BY period_month DESC""",
                        (issuer_id,),
                    ).fetchall()
                    for r in months_rows:
                        r = _db_row_to_dict(r)
                        ym_val = r.get("ym") or ""
                        if ym_val:
                            months_with_movements.append({"ym": ym_val, "n": int(r.get("n") or 0), "label": ym_to_label(ym_val)})
            # Balance mismatch banner data
            balance_mismatch_info = None
            if table_exists(conn, "bank_statements") and has_column(conn, "bank_statements", "has_balance_mismatch"):
                _bm_rows = conn.execute(
                    "SELECT id, has_balance_mismatch, opening_balance, closing_balance, computed_closing_balance, balance_diff FROM bank_statements WHERE issuer_id = ? AND period_month = ? AND has_balance_mismatch = 1",
                    (issuer_id, period_month),
                ).fetchall()
                if _bm_rows:
                    _bm = _db_row_to_dict(_bm_rows[0])
                    balance_mismatch_info = {
                        "statement_id": _bm["id"],
                        "opening": float(_bm.get("opening_balance") or 0),
                        "expected_closing": float(_bm.get("closing_balance") or 0),
                        "computed_closing": float(_bm.get("computed_closing_balance") or 0),
                        "diff": float(_bm.get("balance_diff") or 0),
                    }
        except Exception as e:
            logger.warning("portal movimientos: error cargando datos (%s), mostrando lista vacia", e)
            balance_mismatch_info = None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        ym_safe = sanitize_ym(period_month or "", ym_now())

        # Auto-run matching on page load (lightweight -- skips if already done)
        if total_count > 0:
            try:
                from services.bank import bank_cfdi_matching as _bcm
                _bcm.refresh_suggestions_for_month(issuer_id, ym_safe)
            except Exception as _me:
                logger.debug("auto-matching on movimientos page: %s", _me)

        try:
            return _render_portal(
                request,
                issuer=issuer,
                template_name="portal_bank_movements.html",
                active_page="bank_movements",
                title="Movimientos",
                movements=movements,
                total_count=total_count,
                sum_ingresos=sum_ingresos,
                sum_gastos=sum_gastos,
                cuenta_propia_entradas=cuenta_propia_entradas,
                cuenta_propia_salidas=cuenta_propia_salidas,
                limit=limit,
                offset=offset,
                statement_id=statement_id or "",
                period_month=ym_safe,
                ym=ym_safe,
                ym_label=ym_to_label(ym_safe),
                prev_ym=shift_ym(ym_safe, -1),
                next_ym=shift_ym(ym_safe, +1),
                months=months_with_movements,
                tipo=tipo or "",
                categoria=categoria or "",
                cfdi_match_status=cfdi_match_status or "",
                match_filter=(match_filter or ""),
                min_confidence=min_confidence,
                search=search or "",
                hide_own_transfers=1 if hide_own_transfers else 0,
                hide_financial=1 if hide_financial else 0,
                only_real_expenses=1 if only_real_expenses else 0,
                statements_opt=statements_opt,
                concil_stats=concil_stats,
                balance_mismatch=balance_mismatch_info,
                csrf_token=csrf_service.generate_csrf_token(),
            )
        except Exception as e:
            logger.exception("portal movimientos (render): %s", e)
            raise HTTPException(status_code=500, detail=f"Error al mostrar la pagina: {e!s}")

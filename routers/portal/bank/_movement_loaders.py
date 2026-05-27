"""Data loaders for bank movements list — statement options, months, balance mismatch, row normalization."""
import json

from database import has_column, table_exists
from routers.portal._helpers import _db_row_to_dict, _strip_date_from_description
from services.ym_helpers import ym_to_label


def normalize_movement_row(row: dict) -> dict:
    """Ensure all expected keys exist and numeric values are properly typed."""
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
    for key in ("deposito", "retiro", "saldo", "confidence_score", "probable_cfdi_score"):
        if row.get(key) is not None and row[key] != "":
            try:
                if key in ("confidence_score", "probable_cfdi_score"):
                    row[key] = int(float(row[key]))
                else:
                    row[key] = float(row[key])
            except (TypeError, ValueError):
                row[key] = None if key != "confidence_score" else 0
    row["concepto"] = _strip_date_from_description(row.get("descripcion")) or (row.get("descripcion") or "").strip()
    return row


def load_statement_options(conn, issuer_id: int) -> list[dict]:
    """Load statement dropdown options from bank_pdf_exports and bank_statements."""
    statements_opt: list[dict] = []
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
    return statements_opt


def load_months_with_movements(conn, issuer_id: int) -> list[dict]:
    """Load list of months that have movements for the month selector."""
    months: list[dict] = []
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
                months.append({"ym": ym_val, "n": int(r.get("n") or 0), "label": ym_to_label(ym_val)})
    else:
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
                    months.append({"ym": ym_val, "n": int(r.get("n") or 0), "label": ym_to_label(ym_val)})
    return months


def load_balance_mismatch(conn, issuer_id: int, period_month: str) -> dict | None:
    """Load balance mismatch info for a given period, if any."""
    if not (table_exists(conn, "bank_statements") and has_column(conn, "bank_statements", "has_balance_mismatch")):
        return None
    _bm_rows = conn.execute(
        "SELECT id, has_balance_mismatch, opening_balance, closing_balance, computed_closing_balance, balance_diff FROM bank_statements WHERE issuer_id = ? AND period_month = ? AND has_balance_mismatch = 1",
        (issuer_id, period_month),
    ).fetchall()
    if not _bm_rows:
        return None
    _bm = _db_row_to_dict(_bm_rows[0])
    return {
        "statement_id": _bm["id"],
        "opening": float(_bm.get("opening_balance") or 0),
        "expected_closing": float(_bm.get("closing_balance") or 0),
        "computed_closing": float(_bm.get("computed_closing_balance") or 0),
        "diff": float(_bm.get("balance_diff") or 0),
    }

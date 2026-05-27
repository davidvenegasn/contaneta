"""Filter builder for bank movements list queries."""
from database import has_column, table_exists


def build_movement_filters(
    conn,
    issuer_id: int,
    *,
    statement_id: str | None,
    period_month: str,
    tipo: str | None,
    categoria: str | None,
    hide_own_transfers: int | None,
    hide_financial: int | None,
    only_real_expenses: int | None,
    cfdi_match_status: str | None,
    match_filter: str | None,
    min_confidence: int | None,
    search: str | None,
    has_matches: bool,
) -> tuple[list[str], list]:
    """Build WHERE clauses and params for bank_movements queries.

    Returns:
        Tuple of (where_clauses, params) ready for ``" AND ".join()``.
    """
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

    return where_clauses, params

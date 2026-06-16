"""Issued invoices list API route."""
import logging
from datetime import datetime

from fastapi import Depends, HTTPException, Query

from database import db, db_rows
from routers.api._helpers import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, _load_fixture
from routers.deps import get_portal_issuer
from services.ym_helpers import sanitize_ym, ym_sql_filter

logger = logging.getLogger(__name__)


def register_invoices_issued_routes(router):
    """Register issued invoices list route."""

    @router.get("/invoices/issued")
    def api_invoices_issued(
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Query(None, description="Year-month (YYYY-MM)"),
        search: str = Query("", description="Search UUID/RFC/nombre/concepto"),
        status: str = Query("", description="Status filter: vigente, cancelada, all"),
        min_amount: float = Query(None, description="Minimum amount"),
        max_amount: float = Query(None, description="Maximum amount"),
        metodo_pago: str = Query("", description="PUE or PPD"),
        page: int = Query(1, ge=1, description="Page number"),
        per_page: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Items per page"),
    ):
        """API endpoint para facturas emitidas con filtros y paginacion."""
        fixture = _load_fixture("issued")
        if fixture is not None:
            return fixture
        issuer_id = issuer["id"]
        if not ym:
            ym = datetime.now().strftime("%Y-%m")
        ym = sanitize_ym(ym, datetime.now().strftime("%Y-%m"))
        _ym_filt = ym_sql_filter(ym)

        # Build WHERE clause
        where_parts = [
            "issuer_id = ?",
            "direction = 'issued'",
            "fecha_emision IS NOT NULL",
            _ym_filt,
            "(xml_status = 'parsed' OR total IS NULL OR total >= 0.01)",
        ]
        params = [issuer_id, ym]

        # Deduplicate subquery (same as portal route)
        dedup_subquery = f"""
            id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                        ORDER BY (CASE WHEN COALESCE(total,0) >= 0.01 THEN 0 ELSE 1 END), id
                    ) AS rn
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'issued' AND fecha_emision IS NOT NULL
                      AND {_ym_filt} AND (xml_status = 'parsed' OR total IS NULL OR total >= 0.01)
                ) WHERE rn = 1
            )
        """
        where_parts.append(dedup_subquery)
        params.extend([issuer_id, ym])

        # Search filter
        if search:
            from services.db_utils import escape_like
            search_term = f"%{escape_like(search.upper())}%"
            where_parts.append(
                "(UPPER(COALESCE(uuid,'')) LIKE ? ESCAPE '\\' OR UPPER(COALESCE(rfc_receptor,'')) LIKE ? ESCAPE '\\' "
                "OR UPPER(COALESCE(nombre_receptor,'')) LIKE ? ESCAPE '\\' OR UPPER(COALESCE(concepto,'')) LIKE ? ESCAPE '\\')"
            )
            params.extend([search_term, search_term, search_term, search_term])

        # Status filter
        if status and status.lower() in ("vigente", "cancelada"):
            if status.lower() == "vigente":
                where_parts.append("(status = '1' OR UPPER(TRIM(COALESCE(status,''))) = 'V' OR UPPER(TRIM(COALESCE(status,''))) = 'VIGENTE')")
            elif status.lower() == "cancelada":
                where_parts.append("(status = '0' OR UPPER(TRIM(COALESCE(status,''))) = 'C' OR UPPER(TRIM(COALESCE(status,''))) LIKE 'CANCEL%')")

        # Amount filters
        if min_amount is not None:
            where_parts.append("COALESCE(total, 0) >= ?")
            params.append(min_amount)
        if max_amount is not None:
            where_parts.append("COALESCE(total, 0) <= ?")
            params.append(max_amount)

        # Metodo pago filter
        if metodo_pago and metodo_pago.upper() in ("PUE", "PPD"):
            where_parts.append("UPPER(TRIM(COALESCE(metodo_pago,''))) = ?")
            params.append(metodo_pago.upper())

        where_clause = " AND ".join(where_parts)

        # Count total (row_factory devuelve dict; la clave es el nombre de columna, no el indice)
        try:
            conn = db()
            count_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM sat_cfdi WHERE {where_clause}",
                tuple(params)
            ).fetchone()
            total_count = int(count_row.get("c", 0)) if count_row else 0
            conn.close()
        except Exception as e:
            logger.exception("Error counting invoices")
            raise HTTPException(status_code=500, detail="Error al contar facturas")

        # Fetch paginated results (solo columnas usadas en el listado para payload pequeno)
        try:
            offset = (page - 1) * per_page
            rows = db_rows(
                f"""
                SELECT uuid, fecha_emision, rfc_receptor, nombre_receptor, concepto, total, moneda,
                       COALESCE(impuestos, 0) AS impuestos, COALESCE(retenciones, 0) AS retenciones,
                       metodo_pago, forma_pago, tipo_comprobante, status, xml_path, xml_status,
                       cancellation_status
                FROM sat_cfdi
                WHERE {where_clause}
                ORDER BY fecha_emision DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params) + (per_page, offset)
            )
        except Exception as e:
            logger.exception("Error fetching invoices")
            raise HTTPException(status_code=500, detail="Error al obtener facturas")

        return {
            "data": rows,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_count,
                "pages": (total_count + per_page - 1) // per_page if total_count > 0 else 0,
            },
            "filters": {
                "ym": ym,
                "search": search,
                "status": status,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "metodo_pago": metodo_pago,
            }
        }

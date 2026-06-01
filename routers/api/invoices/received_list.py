"""Received invoices list API route."""
import logging
from datetime import datetime

from fastapi import Depends, HTTPException, Query

from database import db, db_rows
from routers.api._helpers import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, _load_fixture
from routers.deps import get_portal_issuer
from services.ym_helpers import sanitize_ym, ym_sql_filter

logger = logging.getLogger(__name__)


def register_invoices_received_routes(router):
    """Register received invoices list route."""

    @router.get("/invoices/received")
    def api_invoices_received(
        issuer: dict = Depends(get_portal_issuer),
        ym: str = Query(None, description="Year-month (YYYY-MM)"),
        search: str = Query("", description="Search UUID/RFC/nombre/concepto"),
        status: str = Query("", description="Status filter: vigente, cancelada, all"),
        min_amount: float = Query(None, description="Minimum amount"),
        max_amount: float = Query(None, description="Maximum amount"),
        metodo_pago: str = Query("", description="PUE or PPD"),
        match_filter: str = Query("", description="Conciliacion: none|probable"),
        page: int = Query(1, ge=1, description="Page number"),
        per_page: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Items per page"),
    ):
        """API endpoint para facturas recibidas con filtros y paginacion."""
        fixture = _load_fixture("received")
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
            "direction = 'received'",
            "fecha_emision IS NOT NULL",
            _ym_filt,
            "total IS NOT NULL AND total >= 0.01",
            "(tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')",
        ]
        params = [issuer_id, ym]

        # Deduplicate subquery
        dedup_subquery = f"""
            id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY issuer_id, direction, LOWER(TRIM(uuid))
                        ORDER BY id
                    ) AS rn
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'received' AND fecha_emision IS NOT NULL
                      AND {_ym_filt} AND total IS NOT NULL AND total >= 0.01
                      AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
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
                "(UPPER(COALESCE(uuid,'')) LIKE ? ESCAPE '\\' OR UPPER(COALESCE(rfc_emisor,'')) LIKE ? ESCAPE '\\' "
                "OR UPPER(COALESCE(nombre_emisor,'')) LIKE ? ESCAPE '\\' OR UPPER(COALESCE(concepto,'')) LIKE ? ESCAPE '\\')"
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

        # Conciliacion (mismo modelo que bank/movements)
        mf = (match_filter or "").strip().lower()
        if mf in ("none", "probable"):
            # Solo si existe tabla; si no existe, no filtrar (degrada a 'todos')
            try:
                conn0 = db()
                has_matches = ("bank_invoice_matches" in {r[0] for r in conn0.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()})
                conn0.close()
            except Exception:
                has_matches = False
            if has_matches:
                if mf == "probable":
                    where_parts.append(
                        """EXISTS (
                             SELECT 1 FROM bank_invoice_matches bim
                             WHERE bim.issuer_id = sat_cfdi.issuer_id
                               AND bim.cfdi_id = sat_cfdi.id
                               AND bim.status IN ('suggested','confirmed')
                               AND COALESCE(bim.score,0) >= 80
                           )"""
                    )
                elif mf == "none":
                    where_parts.append(
                        """NOT EXISTS (
                             SELECT 1 FROM bank_invoice_matches bim
                             WHERE bim.issuer_id = sat_cfdi.issuer_id
                               AND bim.cfdi_id = sat_cfdi.id
                               AND bim.status IN ('suggested','confirmed')
                               AND COALESCE(bim.score,0) >= 50
                           )"""
                    )

        where_clause = " AND ".join(where_parts)

        # Count total (row_factory devuelve dict)
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

        # Fetch paginated results
        try:
            offset = (page - 1) * per_page
            rows = db_rows(
                f"""
                SELECT uuid, fecha_emision, rfc_emisor, nombre_emisor, concepto, total, moneda,
                       COALESCE(impuestos, 0) AS impuestos, COALESCE(retenciones, 0) AS retenciones,
                       metodo_pago, status, xml_path, xml_status,
                       (
                         SELECT bm.id
                         FROM bank_invoice_matches bim
                         JOIN bank_movements bm ON bm.id = bim.bank_movement_id AND bm.issuer_id = bim.issuer_id
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_id,
                       (
                         SELECT bm.fecha
                         FROM bank_invoice_matches bim
                         JOIN bank_movements bm ON bm.id = bim.bank_movement_id AND bm.issuer_id = bim.issuer_id
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_fecha,
                       (
                         SELECT COALESCE(bm.deposito, 0) - COALESCE(bm.retiro, 0)
                         FROM bank_invoice_matches bim
                         JOIN bank_movements bm ON bm.id = bim.bank_movement_id AND bm.issuer_id = bim.issuer_id
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_amount,
                       (
                         SELECT bm.descripcion
                         FROM bank_invoice_matches bim
                         JOIN bank_movements bm ON bm.id = bim.bank_movement_id AND bm.issuer_id = bim.issuer_id
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_desc,
                       (
                         SELECT bim.score
                         FROM bank_invoice_matches bim
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_score,
                       (
                         SELECT bim.status
                         FROM bank_invoice_matches bim
                         WHERE bim.issuer_id = sat_cfdi.issuer_id
                           AND bim.cfdi_id = sat_cfdi.id
                           AND bim.status IN ('suggested','confirmed')
                         ORDER BY bim.score DESC, bim.id DESC
                         LIMIT 1
                       ) AS probable_movement_status
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

        # Enrich with deductibility data
        try:
            from services.fiscal.deductibility import get_deductibility_map
            uuids = [r["uuid"] for r in rows if r.get("uuid")]
            deduct_map = get_deductibility_map(issuer_id, uuids) if uuids else {}
            enriched = []
            for r in rows:
                d = dict(r)
                dd = deduct_map.get(d.get("uuid"), {"percentage": 100.0, "source": "default", "auto_reason": ""})
                d["deductibility_pct"] = dd["percentage"]
                d["deductibility_source"] = dd["source"]
                enriched.append(d)
            rows = enriched
        except Exception:
            logger.debug("Could not enrich deductibility", exc_info=True)

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
                "match_filter": match_filter,
            }
        }

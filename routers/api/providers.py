"""Providers API routes."""
import logging

from fastapi import Body, Depends, HTTPException, Query, Request

from database import db, db_rows, table_exists
from routers.api._helpers import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
)
from routers.deps import get_portal_issuer

logger = logging.getLogger(__name__)

try:
    from cfdi_pdf import CLAVE_UNIDAD, FORMA_PAGO, MONEDA, REGIMEN_FISCAL, USO_CFDI
except Exception:
    USO_CFDI = {"G03": "Gastos en general", "G01": "Adquisición de mercancías", "CN01": "Nómina"}
    REGIMEN_FISCAL = {"601": "General de Ley Personas Morales", "612": "Personas Físicas con Actividades Empresariales", "616": "Sin obligaciones fiscales", "626": "Régimen Simplificado de Confianza"}
    FORMA_PAGO = {"03": "Transferencia electrónica", "01": "Efectivo", "99": "Por definir"}
    MONEDA = {"MXN": "Peso Mexicano", "USD": "Dólar Americano"}
    CLAVE_UNIDAD = {"E48": "Unidad de servicio", "EA": "Cada uno", "H87": "Pieza"}

from services.auth import csrf as csrf_service
from services.http import ok


def register_providers_routes(router):
    """Register Providers routes on the API router."""

    @router.get("/provider-invoices")
    @router.get("/providers/invoices")
    def api_provider_invoices(
        issuer: dict = Depends(get_portal_issuer),
        rfc: str = "",
        limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Máximo de registros"),
        offset: int = Query(0, ge=0, description="Registros a saltar"),
    ):
        try:
            iid = issuer["id"]
            rfc_norm = (rfc or "").strip().upper()
            if not rfc_norm:
                return {"items": [], "total": 0}
        except (ValueError, KeyError, TypeError):
            logger.exception("api cfdi issued list: issuer inválido")
            raise HTTPException(status_code=401, detail="Sesión inválida")
        try:
            base_where = """
                issuer_id = ? AND direction = 'received'
                AND UPPER(TRIM(COALESCE(rfc_emisor,''))) = ?
                AND (tipo_comprobante IS NULL OR UPPER(TRIM(COALESCE(tipo_comprobante,''))) != 'N')
                AND total IS NOT NULL AND total >= 0.01
            """
            total_row = db_rows(
                f"SELECT COUNT(*) AS c FROM sat_cfdi WHERE {base_where}",
                (iid, rfc_norm),
            )
            total = total_row[0]["c"] if total_row else 0
            rows = db_rows(
                f"""
                SELECT uuid, fecha_emision, total, moneda, status, xml_path, concepto
                FROM sat_cfdi
                WHERE {base_where}
                ORDER BY fecha_emision DESC LIMIT ? OFFSET ?
                """,
                (iid, rfc_norm, limit, offset),
            )
            items = [{"uuid": r.get("uuid"), "fecha_emision": r.get("fecha_emision"),
                      "concepto": (r.get("concepto") or "")[:80] + ("…" if len(r.get("concepto") or "") > 80 else ""),
                      "total": float(r.get("total") or 0), "moneda": r.get("moneda") or "MXN",
                      "status": r.get("status"), "has_pdf": bool(r.get("xml_path"))} for r in rows]
            return {"items": items, "total": total}
        except Exception:
            logger.exception("api cfdi issued list: issuer_id=%s", issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos cargar la lista. Intenta de nuevo.",
            )


    @router.get("/provider-invoices/report")
    def api_provider_invoices_report(
        issuer: dict = Depends(get_portal_issuer),
        rfc: str = Query(...),
        format: str = Query("pdf", alias="format"),
    ):
        if format not in ("pdf", "xlsx"):
            raise HTTPException(status_code=400, detail="format debe ser pdf o xlsx")
        try:
            rfc_norm = (rfc or "").strip().upper()
            if not rfc_norm:
                raise HTTPException(status_code=400, detail="RFC de proveedor requerido")
            rows = _provider_report_rows(issuer["id"], rfc_norm)
            provider_name = (rows[0].get("nombre_emisor") or "").strip() if rows else ""
            if not provider_name:
                provider_name = rfc_norm
            if format == "pdf":
                content = _build_provider_report_pdf(issuer, provider_name, rows)
                filename = f"facturas-recibidas-{rfc_norm[:8]}.pdf"
                media_type = "application/pdf"
            else:
                content = _build_provider_report_xlsx(issuer, provider_name, rows)
                filename = f"facturas-recibidas-{rfc_norm[:8]}.xlsx"
                media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            from fastapi.responses import Response
            return Response(
                content=content,
                media_type=media_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}"', "Content-Length": str(len(content))},
            )
        except HTTPException:
            raise
        except (ValueError, KeyError, TypeError):
            logger.exception("api provider report: issuer inválido")
            raise HTTPException(status_code=401, detail="Sesión inválida")
        except Exception:
            logger.exception("api provider report: issuer_id=%s", issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos generar el reporte. Intenta de nuevo.",
            )


    @router.get("/providers")
    def api_providers(
        issuer: dict = Depends(get_portal_issuer),
        limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Máximo de registros"),
        offset: int = Query(0, ge=0, description="Registros a saltar"),
    ):
        try:
            iid = issuer["id"]
            saved = {}
            conn = db()
            try:
                if table_exists(conn, "supplier_profiles"):
                    for r in db_rows("SELECT rfc, legal_name, email, alias FROM supplier_profiles WHERE issuer_id = ?", (iid,)):
                        rfc_norm = (r["rfc"] or "").strip().upper()
                        if rfc_norm:
                            saved[rfc_norm] = {"rfc": rfc_norm, "legal_name": r["legal_name"] or "", "email": r.get("email"),
                                               "alias": r.get("alias"), "facturas_count": 0, "total_recibido": 0.0, "source": "saved"}
            finally:
                conn.close()
            from_sat = db_rows(
                """
                SELECT UPPER(TRIM(rfc_emisor)) AS rfc, MAX(nombre_emisor) AS legal_name,
                       COUNT(*) AS facturas_count, COALESCE(SUM(total), 0) AS total_recibido
                FROM sat_cfdi
                WHERE issuer_id = ? AND direction = 'received' AND rfc_emisor IS NOT NULL AND TRIM(rfc_emisor) != ''
                  AND total IS NOT NULL AND total >= 0.01
                  AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')
                GROUP BY UPPER(TRIM(rfc_emisor))
                """,
                (iid,),
            )
            for r in from_sat:
                rfc = (r["rfc"] or "").strip()
                if not rfc:
                    continue
                if rfc in saved:
                    saved[rfc]["facturas_count"] = r["facturas_count"]
                    saved[rfc]["total_recibido"] = float(r["total_recibido"] or 0)
                    saved[rfc]["source"] = "both"
                else:
                    saved[rfc] = {"rfc": rfc, "legal_name": r["legal_name"] or "", "email": None, "alias": None,
                                  "facturas_count": r["facturas_count"], "total_recibido": float(r["total_recibido"] or 0), "source": "sat"}
            out = sorted(saved.values(), key=lambda x: (-x["facturas_count"], -x["total_recibido"], (x.get("alias") or x["rfc"]).lower()))
            total = len(out)
            items = out[offset : offset + limit]
            return {"items": items, "total": total}
        except Exception as e:
            logger.warning("api_providers: %s", e, exc_info=True)
            return {"items": [], "total": 0}


    @router.post("/providers/create")
    def api_providers_create(request: Request, payload: dict = Body(...), issuer: dict = Depends(get_portal_issuer)):
        csrf_service.verify_api_csrf(request)
        try:
            rfc = (payload.get("rfc") or "").strip().upper()
            legal_name = (payload.get("legal_name") or "").strip()
            if not rfc or not legal_name:
                raise HTTPException(status_code=400, detail="RFC y razón social son obligatorios")
            zip_val = (payload.get("zip") or "").strip() or None
            tax_val = (payload.get("tax_system") or "").strip() or None
            email = (payload.get("email") or "").strip() or None
            alias = (payload.get("alias") or "").strip() or None
            conn = db()
            conn.execute(
                """
                INSERT INTO supplier_profiles (issuer_id, rfc, legal_name, zip, tax_system, email, alias, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(issuer_id, rfc) DO UPDATE SET legal_name = excluded.legal_name, zip = excluded.zip,
                    tax_system = excluded.tax_system, email = excluded.email, alias = excluded.alias, updated_at = CURRENT_TIMESTAMP
                """,
                (issuer["id"], rfc, legal_name, zip_val, tax_val, email, alias),
            )
            conn.commit()
            conn.close()
            return ok({"rfc": rfc})
        except HTTPException:
            raise
        except Exception:
            logger.exception("api providers create: issuer_id=%s", issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos guardar el proveedor. Intenta de nuevo.",
            )



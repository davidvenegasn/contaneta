"""Quotations API routes."""
import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime
from io import BytesIO
from typing import Optional

from fastapi import Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from config import BASE_DIR, DEV_FIXTURES
from database import db, db_rows, has_column, list_catalog, search_catalog, table_exists
from routers.api._helpers import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    MAX_LIST_OFFSET,
    QUOTATION_STATUSES,
    _api_rate_check,
    _get_month_totals_safe,
    _load_fixture,
)
from routers.deps import get_portal_issuer
from validators import validate_customer, validate_product

logger = logging.getLogger(__name__)

try:
    from cfdi_pdf import CLAVE_UNIDAD, FORMA_PAGO, MONEDA, REGIMEN_FISCAL, USO_CFDI
except Exception:
    USO_CFDI = {"G03": "Gastos en general", "G01": "Adquisición de mercancías", "CN01": "Nómina"}
    REGIMEN_FISCAL = {"601": "General de Ley Personas Morales", "612": "Personas Físicas con Actividades Empresariales", "616": "Sin obligaciones fiscales", "626": "Régimen Simplificado de Confianza"}
    FORMA_PAGO = {"03": "Transferencia electrónica", "01": "Efectivo", "99": "Por definir"}
    MONEDA = {"MXN": "Peso Mexicano", "USD": "Dólar Americano"}
    CLAVE_UNIDAD = {"E48": "Unidad de servicio", "EA": "Cada uno", "H87": "Pieza"}

from facturapi_client import FacturapiError, create_invoice, download_invoice
from facturapi_client import cancel_invoice as facturapi_cancel
from services import clients_service, products_service
from services import jobs as jobs_service
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.billing import subscription as subscription_service
from services.http import ok, ok_list
from services.invoices import invoices_engine
from services.sat.sat_sync import get_month_totals as _get_month_totals_raw
from services.schemas import ClientCreate, ProductCreate
from services.ym_helpers import is_annual, sanitize_ym, ym_sql_filter


def register_quotations_routes(router):
    """Register Quotations routes on the API router."""

    @router.get("/quotations")
    def api_quotations_list(
        issuer: dict = Depends(get_portal_issuer),
        limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT, description="Máximo de registros"),
        offset: int = Query(0, ge=0, le=MAX_LIST_OFFSET, description="Registros a saltar"),
    ):
        try:
            issuer_id = issuer["id"]
        except (ValueError, KeyError, TypeError):
            logger.exception("api quotations list: issuer inválido")
            raise HTTPException(status_code=401, detail="Sesión inválida")
        try:
            conn = db()
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM quotations WHERE issuer_id = ?",
                (issuer_id,),
            ).fetchone()
            total = total_row["c"] if total_row else 0
            rows = conn.execute(
                """
                SELECT q.id, q.folio, q.customer_rfc, q.customer_legal_name, q.customer_email,
                       q.status, q.public_token, q.valid_until, q.notes, q.responded_at, q.created_at, q.updated_at,
                       (SELECT COALESCE(SUM((qi.quantity * qi.unit_price) * (1 + COALESCE(qi.iva_rate, 0))), 0)
                        FROM quotation_items qi WHERE qi.quotation_id = q.id) AS total
                FROM quotations q WHERE q.issuer_id = ? ORDER BY q.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (issuer_id, limit, offset),
            ).fetchall()
            conn.close()
            items = [{"id": r["id"], "folio": r.get("folio"), "customer_rfc": r["customer_rfc"],
                      "customer_legal_name": r["customer_legal_name"], "customer_email": r["customer_email"],
                      "status": r["status"], "public_token": r["public_token"], "valid_until": r["valid_until"],
                      "notes": r["notes"], "responded_at": r["responded_at"], "created_at": r["created_at"],
                      "updated_at": r["updated_at"], "total": float(r["total"] or 0)} for r in rows]
            return {"items": items, "total": total}
        except Exception as e:
            logger.warning("api_quotations_list: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="Error al cargar la lista de cotizaciones.")


    @router.post("/quotations/create")
    def api_quotations_create(request: Request, payload: dict = Body(...), issuer: dict = Depends(get_portal_issuer)):
        csrf_service.verify_api_csrf(request)
        _api_rate_check(request, "api_quotation", max_attempts=20, window=60.0)
        try:
            issuer_id = issuer["id"]
            customer_rfc = (payload.get("customer_rfc") or "").strip().upper()
            customer_legal_name = (payload.get("customer_legal_name") or "").strip()
            customer_email = (payload.get("customer_email") or "").strip() or None
            notes = (payload.get("notes") or "").strip() or None
            status = (payload.get("status") or "draft").strip().lower()
            if status not in QUOTATION_STATUSES:
                status = "draft"
            if not customer_legal_name:
                raise HTTPException(status_code=400, detail="Nombre del cliente es obligatorio")
            items = payload.get("items") or []
            if not items:
                raise HTTPException(status_code=400, detail="Agrega al menos un concepto a la cotización")
            public_token = secrets.token_urlsafe(32)
            iva_rate_quote = float(payload.get("iva_rate") or 0.16)
            currency = (payload.get("currency") or "MXN").strip() or "MXN"
            notes_default = (
                "Condiciones: Esta cotización tiene una vigencia de 30 días. "
                "Los precios están expresados en pesos mexicanos (MXN) e incluyen IVA según se indique. "
                "Para proceder, acepte esta cotización y nos pondremos en contacto."
            )
            notes = (payload.get("notes") or "").strip() or notes_default
            conn = db()
            year = datetime.now().strftime("%Y")
            prefix = f"Q-{year}-"
            next_num = conn.execute(
                """SELECT COALESCE(MAX(CAST(SUBSTR(folio, LENGTH(?) + 1) AS INTEGER)), 0) + 1 AS n
                   FROM quotations WHERE issuer_id = ? AND (folio IS NOT NULL AND folio LIKE ?)""",
                (prefix, issuer_id, prefix + "%"),
            ).fetchone()["n"]
            folio = f"{prefix}{next_num:04d}"
            sent_at = datetime.now().isoformat() if status == "sent" else None
            conn.execute(
                """INSERT INTO quotations (issuer_id, folio, customer_rfc, customer_legal_name, customer_email,
                    status, public_token, notes, iva_rate, currency, sent_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (issuer_id, folio, customer_rfc or "", customer_legal_name, customer_email, status, public_token, notes, iva_rate_quote, currency, sent_at),
            )
            qid = conn.execute("SELECT last_insert_rowid() AS rid").fetchone()["rid"]
            for idx, it in enumerate(items):
                desc = (it.get("description") or "").strip()
                if not desc:
                    continue
                qty = float(it.get("quantity") or 1)
                unit_price = float(it.get("unit_price") or 0)
                iva_rate = float(it.get("iva_rate") or 0.16)
                product_id = it.get("product_id")
                if product_id is not None:
                    try:
                        product_id = int(product_id)
                    except (TypeError, ValueError):
                        product_id = None
                conn.execute(
                    """INSERT INTO quotation_items (quotation_id, description, quantity, unit_price, iva_rate, product_id, sort_order)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (qid, desc, qty, unit_price, iva_rate, product_id, idx),
                )
            # Snapshot para PDF consistente aunque se editen productos después
            items_list = []
            subtotal_sum = 0.0
            for it in items:
                desc = (it.get("description") or "").strip()
                if not desc:
                    continue
                qty = float(it.get("quantity") or 1)
                unit_price = float(it.get("unit_price") or 0)
                iva_rate = float(it.get("iva_rate") or 0.16)
                line_sub = qty * unit_price
                iva_line = line_sub * iva_rate
                subtotal_sum += line_sub
                items_list.append({
                    "description": desc,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "iva_rate": iva_rate,
                    "subtotal": round(line_sub, 2),
                    "total_line": round(line_sub + iva_line, 2),
                })
            iva_total = round(sum((x["subtotal"] * x["iva_rate"]) for x in items_list), 2)
            total = round(subtotal_sum + iva_total, 2)
            created_at = datetime.now().isoformat()
            snapshot = {
                "issuer_name": (issuer.get("razon_social") or issuer.get("rfc") or "").strip(),
                "issuer_rfc": (issuer.get("rfc") or "").strip(),
                "issuer_regimen": (issuer.get("regimen_fiscal") or "").strip(),
                "customer_rfc": customer_rfc or "",
                "customer_legal_name": customer_legal_name or "",
                "customer_email": (customer_email or "").strip() or None,
                "items": items_list,
                "subtotal": round(subtotal_sum, 2),
                "iva_total": iva_total,
                "total": total,
                "valid_until": None,
                "notes": notes or "",
                "folio": folio,
                "created_at": created_at,
            }
            if has_column(conn, "quotations", "metadata_json"):
                conn.execute(
                    "UPDATE quotations SET metadata_json = ? WHERE id = ? AND issuer_id = ?",
                    (json.dumps(snapshot), qid, issuer_id),
                )
            conn.commit()
            conn.close()
            return ok({"id": qid, "public_token": public_token})
        except HTTPException:
            raise
        except Exception:
            logger.exception("api quotations create: issuer_id=%s", issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos crear la cotización. Intenta de nuevo.",
            )


    @router.get("/quotations/{qid}")
    def api_quotations_get(qid: int, issuer: dict = Depends(get_portal_issuer)):
        issuer_id = issuer["id"]
        conn = db()
        row = conn.execute(
            "SELECT id, customer_rfc, customer_legal_name, customer_email, status, public_token, valid_until, notes, responded_at, created_at, updated_at FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer_id, qid),
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Cotización no encontrada")
        items = conn.execute(
            "SELECT id, description, quantity, unit_price, iva_rate, product_id, sort_order FROM quotation_items WHERE quotation_id = ? ORDER BY sort_order, id",
            (qid,),
        ).fetchall()
        conn.close()
        total = 0.0
        items_list = []
        for r in items:
            subtotal = float(r["quantity"] or 0) * float(r["unit_price"] or 0)
            iva = subtotal * float(r["iva_rate"] or 0)
            total += subtotal + iva
            items_list.append({"id": r["id"], "description": r["description"], "quantity": float(r["quantity"] or 0),
                               "unit_price": float(r["unit_price"] or 0), "iva_rate": float(r["iva_rate"] or 0.16),
                               "subtotal": subtotal, "total_line": subtotal + iva})
        d = dict(row)
        return {"id": d["id"], "customer_rfc": d["customer_rfc"], "customer_legal_name": d["customer_legal_name"],
                "customer_email": d["customer_email"], "status": d["status"], "public_token": d["public_token"],
                "valid_until": d["valid_until"], "notes": d["notes"], "responded_at": d["responded_at"],
                "created_at": d["created_at"], "updated_at": d["updated_at"], "items": items_list, "total": round(total, 2)}


    @router.post("/quotations/update-status")
    def api_quotations_update_status(request: Request, payload: dict = Body(...), issuer: dict = Depends(get_portal_issuer)):
        csrf_service.verify_api_csrf(request)
        try:
            qid = payload.get("id")
            status = (payload.get("status") or "").strip().lower()
            if status not in QUOTATION_STATUSES:
                raise HTTPException(status_code=400, detail="Estatus inválido")
            if qid is None:
                raise HTTPException(status_code=400, detail="id requerido")
            try:
                qid = int(qid)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="id inválido")
            conn = db()
            cur = conn.execute(
                "UPDATE quotations SET status = ?, updated_at = datetime('now') WHERE issuer_id = ? AND id = ?",
                (status, issuer["id"], qid),
            )
            conn.commit()
            conn.close()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Cotización no encontrada")
            return ok({"id": qid, "status": status})
        except HTTPException:
            raise
        except Exception:
            logger.exception("api quotations status: qid=%s issuer_id=%s", qid, issuer.get("id"))
            raise HTTPException(
                status_code=500,
                detail="No pudimos obtener el estado. Intenta de nuevo.",
            )


    @router.post("/quotations/respond")
    def api_quotations_respond(request: Request, payload: dict = Body(...)):
        _api_rate_check(request, "quotation_respond", max_attempts=15, window=60.0)
        public_token = (payload.get("public_token") or "").strip()
        action = (payload.get("action") or "").strip().lower()
        if not public_token:
            raise HTTPException(status_code=400, detail="Link inválido")
        if action not in ("accept", "reject", "aceptar", "rechazar"):
            raise HTTPException(status_code=400, detail="Acción inválida")
        status = "accepted" if action in ("accept", "aceptar") else "rejected"
        reason = (payload.get("rejection_reason") or "").strip() or None
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        now = datetime.now().isoformat()
        conn = db()
        row = conn.execute("SELECT id, status FROM quotations WHERE public_token = ?", (public_token,)).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Cotización no encontrada o link expirado")
        if dict(row)["status"] not in ("draft", "sent"):
            conn.close()
            raise HTTPException(status_code=400, detail="Esta cotización ya fue respondida")
        qid = dict(row)["id"]
        if status == "accepted":
            conn.execute(
                """UPDATE quotations SET status = ?, responded_at = datetime('now'), updated_at = datetime('now'),
                   accepted_at = ?, decision_ip = ?, decision_user_agent = ? WHERE id = ?""",
                (status, now, client_ip, user_agent, qid),
            )
        else:
            conn.execute(
                """UPDATE quotations SET status = ?, responded_at = datetime('now'), updated_at = datetime('now'),
                   rejected_at = ?, decision_ip = ?, decision_user_agent = ?, rejection_reason = ? WHERE id = ?""",
                (status, now, client_ip, user_agent, reason, qid),
            )
        conn.commit()
        conn.close()
        return ok({"status": status})




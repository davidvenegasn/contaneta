"""Post-stamp hooks for quick invoice creation — XML storage, sat_cfdi registration, replacement cancel."""
import hashlib
import logging
import os
from datetime import datetime

from fastapi import Request

from config import BASE_DIR
from database import db
from facturapi_client import cancel_invoice as facturapi_cancel
from services.action_log import log_action

logger = logging.getLogger(__name__)


def save_xml_and_register_cfdi(
    issuer: dict,
    issuer_id: int,
    uuid: str,
    fact_id: str,
    currency: str,
    cfdi_use: str,
    payment_method: str,
    payment_form: str,
    customer_rfc: str,
    customer_legal_name: str,
    items_meta: list[dict],
    isr_ret_rate: float,
    iva_ret_rate: float,
) -> None:
    """Download XML from Facturapi, save to storage, and register in sat_cfdi."""
    try:
        from facturapi_client import download_invoice
        xml_bytes = download_invoice(issuer["facturapi_org_id"], fact_id, "xml")
        if isinstance(xml_bytes, str):
            xml_bytes = xml_bytes.encode("utf-8")
        if not xml_bytes:
            return
        now = datetime.utcnow()
        year = now.strftime("%Y")
        month = now.strftime("%m")
        rel_path = os.path.join("storage", "xml", str(issuer_id), "issued", year, month, f"{uuid}.xml")
        abs_path = os.path.normpath(os.path.abspath(os.path.join(BASE_DIR, rel_path)))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(xml_bytes)
        xml_sha256 = hashlib.sha256(xml_bytes).hexdigest()

        subtotal = sum(float(it["quantity"]) * float(it["unit_price"]) for it in items_meta)
        iva_amt = sum(float(it["quantity"]) * float(it["unit_price"]) * float(it["iva_rate"]) for it in items_meta)
        ret_isr_amt = subtotal * float(isr_ret_rate)
        ret_iva_amt = iva_amt * float(iva_ret_rate)
        ret_total = ret_isr_amt + ret_iva_amt
        concepto_txt = (
            (items_meta[0]["description"] or "")[:220]
            if len(items_meta) == 1
            else f"{len(items_meta)} conceptos"
        )

        conn2 = db()
        conn2.execute(
            """
            INSERT INTO sat_cfdi (
              issuer_id, direction, uuid, status, fecha_emision,
              rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor,
              total, moneda, tipo_comprobante, xml_path, uso_cfdi,
              subtotal, impuestos, retenciones, concepto, metodo_pago, forma_pago,
              xml_status, xml_sha256, xml_downloaded_at, updated_at
            ) VALUES (
              ?, 'issued', ?, 'V', ?,
              ?, ?, ?, ?,
              ?, ?, 'I', ?, ?,
              ?, ?, ?, ?, ?, ?,
              'ok', ?, datetime('now'), datetime('now')
            )
            ON CONFLICT(issuer_id, direction, uuid) DO UPDATE SET
              xml_path = excluded.xml_path,
              total = excluded.total,
              moneda = excluded.moneda,
              uso_cfdi = excluded.uso_cfdi,
              subtotal = excluded.subtotal,
              impuestos = excluded.impuestos,
              retenciones = excluded.retenciones,
              concepto = excluded.concepto,
              metodo_pago = excluded.metodo_pago,
              forma_pago = excluded.forma_pago,
              xml_status = excluded.xml_status,
              xml_sha256 = excluded.xml_sha256,
              xml_downloaded_at = excluded.xml_downloaded_at,
              updated_at = datetime('now')
            """,
            (
                issuer_id,
                uuid,
                now.isoformat(timespec="seconds"),
                (issuer.get("rfc") or "").strip().upper() or None,
                (issuer.get("razon_social") or "").strip() or None,
                customer_rfc,
                customer_legal_name,
                float(subtotal + iva_amt - ret_total),
                currency,
                rel_path,
                cfdi_use,
                float(subtotal),
                float(iva_amt),
                float(ret_total),
                concepto_txt,
                payment_method,
                payment_form,
                xml_sha256,
            ),
        )
        conn2.commit()
        conn2.close()
    except Exception as e:
        logger.warning("api_invoices_quick xml/sat_cfdi: %s", e, exc_info=True)


def process_replacement_cancel(
    request: Request,
    issuer: dict,
    issuer_id: int,
    replaces_uuid: str,
    new_uuid: str,
) -> str | None:
    """Auto-cancel the original invoice when issuing a replacement.

    Returns:
        Cancel status string ('accepted', 'pending', 'error') or None.
    """
    try:
        org_id = issuer.get("facturapi_org_id")
        conn_rep = db()
        try:
            orig = conn_rep.execute(
                "SELECT id, facturapi_invoice_id FROM invoices WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) LIMIT 1",
                (issuer_id, replaces_uuid),
            ).fetchone()
            if orig:
                orig = dict(orig)
                orig_facturapi_id = orig.get("facturapi_invoice_id")
                if orig_facturapi_id and org_id:
                    fa_result = facturapi_cancel(org_id, orig_facturapi_id, "01")
                    fa_status = (fa_result.get("status") or "").lower()
                    fa_cs = (fa_result.get("cancellation_status") or "").lower()
                    c_status = "accepted" if fa_status == "canceled" else ("pending" if fa_cs == "pending" else "accepted")
                    c_flag = 1 if c_status == "accepted" else 0
                    now_iso = datetime.utcnow().isoformat(timespec="seconds")
                    conn_rep.execute(
                        """UPDATE invoices
                           SET cancelled = ?, cancel_status = ?, cancel_motive = '01',
                               cancelled_at = ?, replacement_uuid = ?
                           WHERE id = ? AND issuer_id = ?""",
                        (c_flag, c_status, now_iso, new_uuid, orig["id"], issuer_id),
                    )
                    conn_rep.execute(
                        "UPDATE invoices SET replaces_uuid = ? WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?)",
                        (replaces_uuid, issuer_id, new_uuid),
                    )
                    if c_status == "accepted":
                        conn_rep.execute(
                            "UPDATE sat_cfdi SET status = 'C', updated_at = datetime('now') WHERE issuer_id = ? AND LOWER(TRIM(uuid)) = LOWER(?) AND direction = 'issued'",
                            (issuer_id, replaces_uuid),
                        )
                    conn_rep.commit()
                    log_action(request, "invoice_cancelled", issuer_id=issuer_id, uuid=replaces_uuid[:36], motive="01", cancel_status=c_status)
                    return c_status
        finally:
            conn_rep.close()
    except Exception as e:
        logger.warning("api_invoices_quick auto-cancel: %s", e, exc_info=True)
        return "error"
    return None

"""Helpers para cotizaciones: carga por public_token, generación de PDF, CRUD y filtros."""
import json
import logging
from io import BytesIO
from typing import Optional

from database import db, has_column, transaction

logger = logging.getLogger(__name__)


def get_quotation_by_public_token(public_token: str) -> Optional[dict]:
    """Carga cotización + issuer + items por public_token. None si no existe."""
    conn = db()
    select_cols = """
        q.id, q.issuer_id, q.folio, q.customer_rfc, q.customer_legal_name, q.customer_email,
        q.status, q.public_token, q.notes, q.responded_at, q.created_at, q.iva_rate AS quote_iva_rate,
        q.currency, q.rejection_reason, q.valid_until,
        i.razon_social AS issuer_name, i.rfc AS issuer_rfc, i.regimen_fiscal AS issuer_regimen
    """
    if has_column(conn, "quotations", "metadata_json"):
        select_cols += ", q.metadata_json"
    row = conn.execute(
        f"SELECT {select_cols} FROM quotations q JOIN issuers i ON i.id = q.issuer_id WHERE q.public_token = ?",
        (public_token,),
    ).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    # Si hay snapshot guardado, usarlo para items y totales (PDF consistente)
    metadata_json = d.pop("metadata_json", None) if "metadata_json" in d else None
    if metadata_json:
        try:
            snap = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
            if isinstance(snap, dict):
                d["items"] = snap.get("items") or []
                d["subtotal"] = snap.get("subtotal")
                d["iva_total"] = snap.get("iva_total")
                d["total"] = snap.get("total")
                if d["subtotal"] is None and d["items"]:
                    d["subtotal"] = round(sum(it.get("subtotal", 0) or (float(it.get("quantity") or 0) * float(it.get("unit_price") or 0)) for it in d["items"]), 2)
                if d["iva_total"] is None and d["items"]:
                    d["iva_total"] = round(sum((it.get("subtotal") or (float(it.get("quantity") or 0) * float(it.get("unit_price") or 0))) * float(it.get("iva_rate") or 0.16) for it in d["items"]), 2)
                if d["total"] is None:
                    d["total"] = round((d.get("subtotal") or 0) + (d.get("iva_total") or 0), 2)
                if snap.get("issuer_name") is not None:
                    d["issuer_name"] = snap.get("issuer_name") or d.get("issuer_rfc") or "Emisor"
                if snap.get("issuer_rfc") is not None:
                    d["issuer_rfc"] = snap.get("issuer_rfc")
                if snap.get("issuer_regimen") is not None:
                    d["issuer_regimen"] = snap.get("issuer_regimen")
                if snap.get("valid_until") is not None:
                    d["valid_until"] = snap.get("valid_until")
                if snap.get("notes") is not None:
                    d["notes"] = snap.get("notes")
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    if "items" not in d or not d["items"]:
        items = conn.execute(
            "SELECT description, quantity, unit_price, iva_rate FROM quotation_items WHERE quotation_id = ? ORDER BY sort_order, id",
            (d["id"],),
        ).fetchall()
        subtotal_sum = 0.0
        items_list = []
        for r in items:
            line_sub = float(r["quantity"] or 0) * float(r["unit_price"] or 0)
            iva_rate = float(r["iva_rate"]) if r.get("iva_rate") is not None else float(d.get("quote_iva_rate") or 0.16)
            iva_line = line_sub * iva_rate
            subtotal_sum += line_sub
            items_list.append({
                "description": r["description"],
                "quantity": float(r["quantity"] or 0),
                "unit_price": float(r["unit_price"] or 0),
                "iva_rate": iva_rate,
                "subtotal": line_sub,
                "total_line": round(line_sub + iva_line, 2),
            })
        d["items"] = items_list
        iva_total = sum((it["subtotal"] * it["iva_rate"]) for it in items_list)
        d["subtotal"] = round(subtotal_sum, 2)
        d["iva_total"] = round(iva_total, 2)
        d["total"] = round(subtotal_sum + iva_total, 2)
    conn.close()
    d["issuer_name"] = d.get("issuer_name") or d.get("issuer_rfc") or "Emisor"
    return d


DELETABLE_STATUSES = ("draft", "sent")
"""Statuses from which a quotation may be soft-deleted."""


def delete_quotation(issuer_id: int, quotation_id: int) -> dict:
    """Soft-delete a quotation by setting status='deleted'.

    Args:
        issuer_id: Tenant ID (ownership check).
        quotation_id: ID of the quotation to delete.

    Returns:
        Dict with id and new status.

    Raises:
        ValueError: If the quotation does not exist, belongs to another tenant,
                    or its current status does not allow deletion.
    """
    conn = db()
    try:
        row = conn.execute(
            "SELECT id, status FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer_id, quotation_id),
        ).fetchone()
        if not row:
            raise ValueError("Cotización no encontrada")
        if row["status"] not in DELETABLE_STATUSES:
            raise ValueError(
                f"No se puede eliminar una cotización con estatus '{row['status']}'"
            )
        conn.execute(
            "UPDATE quotations SET status = 'deleted', updated_at = datetime('now') WHERE id = ? AND issuer_id = ?",
            (quotation_id, issuer_id),
        )
        conn.commit()
        return {"id": quotation_id, "status": "deleted"}
    finally:
        conn.close()


def update_quotation_items(
    issuer_id: int, quotation_id: int, items: list[dict], issuer: dict | None = None
) -> dict:
    """Replace all items of a draft quotation and refresh the metadata snapshot.

    Args:
        issuer_id: Tenant ID (ownership check).
        quotation_id: ID of the quotation whose items are replaced.
        items: List of dicts with keys: description, quantity, unit_price, iva_rate.
        issuer: Optional issuer dict with razon_social/rfc/regimen_fiscal for snapshot.

    Returns:
        Dict with id, items list, subtotal, iva_total, total.

    Raises:
        ValueError: If the quotation is not found or is not in 'draft' status.
    """
    conn = db()
    try:
        row = conn.execute(
            "SELECT id, status, folio, customer_rfc, customer_legal_name, customer_email, notes, valid_until, created_at "
            "FROM quotations WHERE issuer_id = ? AND id = ?",
            (issuer_id, quotation_id),
        ).fetchone()
        if not row:
            raise ValueError("Cotización no encontrada")
        if row["status"] != "draft":
            raise ValueError("Solo se pueden editar conceptos en cotizaciones en borrador")

        with transaction(conn):
            conn.execute(
                "DELETE FROM quotation_items WHERE quotation_id = ?",
                (quotation_id,),
            )
            items_list = []
            subtotal_sum = 0.0
            for idx, it in enumerate(items):
                desc = (it.get("description") or "").strip()
                if not desc:
                    continue
                qty = float(it.get("quantity") or 1)
                unit_price = float(it.get("unit_price") or 0)
                iva_rate = float(it.get("iva_rate") or 0.16)
                conn.execute(
                    """INSERT INTO quotation_items
                       (quotation_id, description, quantity, unit_price, iva_rate, sort_order)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (quotation_id, desc, qty, unit_price, iva_rate, idx),
                )
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

            iva_total = round(sum(x["subtotal"] * x["iva_rate"] for x in items_list), 2)
            total = round(subtotal_sum + iva_total, 2)

            # Rebuild metadata snapshot
            if has_column(conn, "quotations", "metadata_json"):
                snapshot = {
                    "issuer_name": (issuer.get("razon_social") or issuer.get("rfc") or "").strip() if issuer else "",
                    "issuer_rfc": (issuer.get("rfc") or "").strip() if issuer else "",
                    "issuer_regimen": (issuer.get("regimen_fiscal") or "").strip() if issuer else "",
                    "customer_rfc": row["customer_rfc"] or "",
                    "customer_legal_name": row["customer_legal_name"] or "",
                    "customer_email": row["customer_email"],
                    "items": items_list,
                    "subtotal": round(subtotal_sum, 2),
                    "iva_total": iva_total,
                    "total": total,
                    "valid_until": row["valid_until"],
                    "notes": row["notes"] or "",
                    "folio": row["folio"],
                    "created_at": row["created_at"],
                }
                conn.execute(
                    "UPDATE quotations SET metadata_json = ?, updated_at = datetime('now') WHERE id = ? AND issuer_id = ?",
                    (json.dumps(snapshot), quotation_id, issuer_id),
                )
            else:
                conn.execute(
                    "UPDATE quotations SET updated_at = datetime('now') WHERE id = ? AND issuer_id = ?",
                    (quotation_id, issuer_id),
                )

        return {
            "id": quotation_id,
            "items": items_list,
            "subtotal": round(subtotal_sum, 2),
            "iva_total": iva_total,
            "total": total,
        }
    finally:
        conn.close()


def list_quotations(
    issuer_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
    status: str | None = None,
    customer_rfc: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """List quotations for a tenant with optional filters.

    Args:
        issuer_id: Tenant ID.
        limit: Max rows to return.
        offset: Rows to skip.
        status: Filter by quotation status.
        customer_rfc: Filter by customer RFC (exact match, uppercased).
        date_from: Filter quotations created on or after this date (YYYY-MM-DD).
        date_to: Filter quotations created on or before this date (YYYY-MM-DD).

    Returns:
        Dict with 'items' (list of quotation dicts) and 'total' (int count).
    """
    conn = db()
    try:
        where_clauses = ["q.issuer_id = ?"]
        params: list = [issuer_id]

        if status:
            where_clauses.append("q.status = ?")
            params.append(status.strip().lower())
        if customer_rfc:
            where_clauses.append("q.customer_rfc = ?")
            params.append(customer_rfc.strip().upper())
        if date_from:
            where_clauses.append("q.created_at >= ?")
            params.append(date_from.strip())
        if date_to:
            # Include the full day by comparing < the next day
            where_clauses.append("q.created_at <= ?")
            params.append(date_to.strip() + " 23:59:59")

        where_sql = " AND ".join(where_clauses)

        total_row = conn.execute(
            f"SELECT COUNT(*) AS c FROM quotations q WHERE {where_sql}",
            tuple(params),
        ).fetchone()
        total = total_row["c"] if total_row else 0

        rows = conn.execute(
            f"""
            SELECT q.id, q.folio, q.customer_rfc, q.customer_legal_name, q.customer_email,
                   q.status, q.public_token, q.valid_until, q.notes, q.responded_at, q.created_at, q.updated_at,
                   (SELECT COALESCE(SUM((qi.quantity * qi.unit_price) * (1 + COALESCE(qi.iva_rate, 0))), 0)
                    FROM quotation_items qi WHERE qi.quotation_id = q.id) AS total
            FROM quotations q WHERE {where_sql} ORDER BY q.created_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        ).fetchall()

        items = [
            {
                "id": r["id"],
                "folio": r.get("folio"),
                "customer_rfc": r["customer_rfc"],
                "customer_legal_name": r["customer_legal_name"],
                "customer_email": r["customer_email"],
                "status": r["status"],
                "public_token": r["public_token"],
                "valid_until": r["valid_until"],
                "notes": r["notes"],
                "responded_at": r["responded_at"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "total": float(r["total"] or 0),
            }
            for r in rows
        ]
        return {"items": items, "total": total}
    finally:
        conn.close()


def _safe_text(s: str, max_len: int = 200) -> str:
    """Escape y truncar para PDF."""
    if s is None:
        return "—"
    out = str(s).replace("<", " ").replace(">", " ").strip()
    return (out[:max_len] + "…") if len(out) > max_len else (out or "—")


def build_quotation_pdf(quote: dict) -> bytes:
    """Genera PDF formal de cotización: encabezado, emisor, cliente, tabla conceptos, totales, vigencia, notas."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, SimpleDocTemplate

    buf = BytesIO()
    margin = 0.65 * inch
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=0.9 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="QuoteTitle",
        parent=styles["Heading1"],
        fontSize=20,
        spaceAfter=2,
        textColor=colors.HexColor("#0d1f1c"),
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        name="QuoteSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=0,
        textColor=colors.HexColor("#475569"),
        fontName="Helvetica",
    )
    section_style = ParagraphStyle(
        name="QuoteSection",
        parent=styles["Normal"],
        fontSize=11,
        spaceAfter=8,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0d1f1c"),
    )
    body_style = ParagraphStyle(
        name="QuoteBody",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=4,
        fontName="Helvetica",
    )
    small_style = ParagraphStyle(
        name="QuoteSmall",
        parent=styles["Normal"],
        fontSize=9,
        spaceAfter=3,
        textColor=colors.HexColor("#475569"),
        fontName="Helvetica",
    )

    # --- Emisor ---
    issuer_name = _safe_text(quote.get("issuer_name") or "Emisor", 120)
    issuer_rfc = _safe_text(quote.get("issuer_rfc"), 20)
    issuer_regimen = _safe_text(quote.get("issuer_regimen"), 80)
    issuer_lines = [f"<b>{issuer_name}</b>", f"RFC: {issuer_rfc}"]
    if issuer_regimen and issuer_regimen != "—":
        issuer_lines.append(f"Régimen fiscal: {issuer_regimen}")

    # --- Folio y fecha ---
    folio = quote.get("folio") or f"COT-{quote.get('id', '')}"
    raw_fecha = (quote.get("created_at") or "")[:10] if quote.get("created_at") else ""
    fecha_dd_mm_yyyy = raw_fecha
    if raw_fecha and len(raw_fecha) >= 10:
        try:
            y, m, d = raw_fecha.split("-")[:3]
            fecha_dd_mm_yyyy = f"{d}/{m}/{y}"
        except Exception:
            pass

    # --- Cliente ---
    customer_name = _safe_text(quote.get("customer_legal_name"), 120)
    customer_rfc = _safe_text(quote.get("customer_rfc"), 20)
    customer_email = _safe_text(quote.get("customer_email"), 80)
    client_lines = [f"<b>{customer_name}</b>", f"RFC: {customer_rfc}"]
    if customer_email and customer_email != "—":
        client_lines.append(f"Correo: {customer_email}")

    currency = (quote.get("currency") or "MXN").strip()

    # ----- Encabezado: COTIZACIÓN + folio/fecha -----
    header_data = [[
        Paragraph('<font size="16"><b>COTIZACIÓN</b></font>', section_style),
        "",
        Paragraph(
            f'<font size="9" color="#475569">Folio: <b>{folio}</b><br/>Fecha: {fecha_dd_mm_yyyy}</font>',
            small_style,
        ),
    ]]
    header_table = Table(header_data, colWidths=[3.2 * inch, 2.0 * inch, 2.1 * inch])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#0d9488")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story = [header_table, Spacer(1, 12)]

    # ----- Emisor -----
    story.append(Paragraph(issuer_lines[0], title_style))
    story.append(Paragraph("<br/>".join(issuer_lines[1:]), subtitle_style))
    story.append(Spacer(1, 14))

    # ----- Cliente (bloque con fondo) -----
    story.append(Paragraph("<b>Cliente</b>", section_style))
    client_para = Paragraph("<br/>".join(client_lines), small_style)
    client_block = Table([[client_para]], colWidths=[6.2 * inch])
    client_block.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdfa")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#99f6e4")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(client_block)
    story.append(Spacer(1, 16))

    # ----- Tabla de conceptos -----
    story.append(Paragraph("<b>Conceptos</b>", section_style))
    headers = ["Descripción", "Cant.", "P. unit.", "IVA %", "Importe", "Total línea"]
    col_widths = [2.4 * inch, 0.5 * inch, 0.75 * inch, 0.5 * inch, 0.85 * inch, 0.9 * inch]
    data = [headers]
    for it in quote.get("items") or []:
        desc = _safe_text(it.get("description"), 60)
        qty = float(it.get("quantity") or 0)
        pu = float(it.get("unit_price") or 0)
        iva_pct = float(it.get("iva_rate") or 0.16) * 100
        importe = round(qty * pu, 2)
        total_line = round(importe * (1 + float(it.get("iva_rate") or 0.16)), 2)
        data.append([
            desc,
            f"{qty:,.2f}",
            f"${pu:,.2f}",
            f"{iva_pct:.0f}%",
            f"${importe:,.2f}",
            f"${total_line:,.2f}",
        ])

    subtotal = quote.get("subtotal")
    if subtotal is None:
        subtotal = sum(float(it.get("quantity") or 0) * float(it.get("unit_price") or 0) for it in quote.get("items") or [])
    subtotal = float(subtotal)
    iva_val = float(quote.get("iva_total", 0))
    total_val = float(quote.get("total") or (subtotal + iva_val))

    data.append(["", "", "", "", "Subtotal", f"${subtotal:,.2f}"])
    data.append(["", "", "", "", "IVA", f"${iva_val:,.2f}"])
    data.append(["", "", "", "", f"<b>Total ({currency})</b>", f"<b>${total_val:,.2f}</b>"])

    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d9488")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (3, -4), "RIGHT"),
        ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -4), 0.5, colors.HexColor("#e2e8f0")),
        ("LINEABOVE", (0, -3), (-1, -3), 1, colors.HexColor("#94a3b8")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#0d1f1c")),
        ("FONTNAME", (4, -3), (-1, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -4), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))

    # ----- Vigencia -----
    valid_until = (quote.get("valid_until") or "").strip()
    if valid_until and len(valid_until) >= 10:
        try:
            y, m, d = valid_until[:10].split("-")
            vigencia_str = f"Válida hasta el {d}/{m}/{y}"
        except Exception:
            vigencia_str = "Vigencia: 30 días naturales"
    else:
        vigencia_str = "Vigencia: 30 días naturales"
    vigencia_data = [[Paragraph(f"<b>Vigencia:</b> {vigencia_str}", body_style)]]
    vigencia_table = Table(vigencia_data, colWidths=[6.2 * inch])
    vigencia_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdfa")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#99f6e4")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(vigencia_table)
    story.append(Spacer(1, 12))

    # ----- Notas y condiciones -----
    story.append(Paragraph("<b>Notas y condiciones</b>", section_style))
    notes = (quote.get("notes") or "").strip()
    if notes:
        story.append(Paragraph(_safe_text(notes, 800).replace("\n", "<br/>"), small_style))
    story.append(Paragraph(
        "Forma de pago: según acuerdo con el cliente. Los precios están expresados en "
        + currency
        + ". Para proceder, acepte esta cotización a través del enlace proporcionado.",
        small_style,
    ))
    story.append(Spacer(1, 6))

    page_num = [0]

    def add_page_number(canvas, doc):
        page_num[0] += 1
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawRightString(doc.pagesize[0] - margin, 0.45 * inch, f"Página {page_num[0]}")
        canvas.drawString(margin, 0.45 * inch, f"{folio} · {fecha_dd_mm_yyyy}")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()

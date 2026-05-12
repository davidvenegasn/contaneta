"""Helpers para cotizaciones: carga por public_token y generación de PDF."""
import json
from io import BytesIO
from typing import Optional

from database import db, has_column


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
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

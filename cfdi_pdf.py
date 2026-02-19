"""
Genera PDF en formato de representación impresa del CFDI (Comprobante Fiscal Digital por Internet),
similar al formato oficial del SAT/PAC.
"""
import re
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    SimpleDocTemplate,
)


# Catálogos SAT (subset común)
FORMA_PAGO = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia electrónica de fondos (incluye SPEI)",
    "04": "Tarjeta de crédito",
    "05": "Monedero electrónico",
    "06": "Dinero electrónico",
    "08": "Vales de despensa",
    "15": "Condonación",
    "17": "Compensación",
    "28": "Tarjeta de débito",
    "99": "Por definir",
}

METODO_PAGO = {
    "PUE": "Pago en una sola exhibición",
    "PPD": "Pago en parcialidades o diferido",
}

USO_CFDI = {
    "G01": "Adquisición de mercancías",
    "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general",
    "D01": "Honorarios médicos, dentales y gastos hospitalarios",
    "D02": "Gastos médicos por incapacidad o discapacidad",
    "D03": "Gastos funerarios",
    "D04": "Donativos",
    "D05": "Intereses reales efectivamente pagados",
    "D06": "Aportaciones voluntarias al SAR",
    "D07": "Primas por seguros de gastos médicos",
    "D08": "Gastos de transportación escolar obligatoria",
    "D09": "Depósitos en cuentas para el ahorro",
    "CP01": "Pagos",
    "CN01": "Nómina",
}

REGIMEN_FISCAL = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "606": "Arrendamiento",
    "612": "Personas Físicas con Actividades Empresariales",
    "620": "Sociedades Cooperativas de Producción",
    "622": "Regimen de Actividades Agrícolas",
    "626": "Régimen Simplificado de Confianza",
    "628": "Hidrocarburos",
    "621": "Incorporación Fiscal",
}

OBJETO_IMP = {"01": "No objeto de impuesto.", "02": "Sí objeto de impuesto.", "03": "Sí objeto de impuesto y no obligado al desglose."}

CLAVE_UNIDAD = {"E48": "Unidad de servicio", "ACT": "Actividad", "H87": "Pieza", "EA": "Cada uno"}

IMPUESTO = {"001": "ISR", "002": "IVA", "003": "IEPS"}

IMPUESTO_TIPO = {"Tasa": "Tasa", "Cuota": "Cuota", "Exento": "Exento"}

MONEDA = {"MXN": "Peso Mexicano", "USD": "Dólar Americano", "EUR": "Euro"}

EXPORTACION = {"01": "No aplica", "02": "Definitiva", "03": "Temporal"}


def _text(el: Optional[ET.Element], attr: str, default: str = "") -> str:
    if el is None:
        return default
    val = el.get(attr)
    if val is not None:
        return str(val).strip()
    for key in el.attrib:
        if key.endswith("}" + attr) or key == attr:
            return str(el.attrib[key]).strip()
    return default


def _text_any(el: Optional[ET.Element], *attrs: str, default: str = "") -> str:
    """Obtiene el primer atributo que exista (prueba varias grafías)."""
    if el is None:
        return default
    for a in attrs:
        v = _text(el, a, "")
        if v:
            return v
    for key in el.attrib:
        v = str(el.attrib[key]).strip()
        if v and key.replace("}", "").split("}")[-1].lower() in [x.lower() for x in attrs]:
            return v
    return default


def _find(el: Optional[ET.Element], tag: str) -> Optional[ET.Element]:
    if el is None:
        return None
    for child in el:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == tag:
            return child
    return None


def _find_all(el: Optional[ET.Element], tag: str) -> list:
    if el is None:
        return []
    return [c for c in el if (c.tag.split("}")[-1] if "}" in c.tag else c.tag) == tag]


def _float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _strip_ns(content: bytes) -> bytes:
    text = content.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    text = re.sub(r"<\w+:(\w+)(\s|>)", r"<\1\2", text)
    text = re.sub(r"</\w+:(\w+)\s*>", r"</\1>", text)
    text = re.sub(r'\s+xmlns[^=]*="[^"]*"', "", text)
    text = re.sub(r'\s(\w+):(\w+)=', r" \2=", text)
    return text.encode("utf-8")


def _format_fecha_emision(s: str) -> str:
    """Format ISO datetime to DD/MM/YYYY HH:MM:SS."""
    if not s:
        return ""
    s = s.strip()
    try:
        if "T" in s:
            date_part, time_part = s.split("T", 1)
            time_part = (time_part[:8] if len(time_part) >= 8 else time_part).replace("Z", "")
            parts = date_part.split("-")
            if len(parts) == 3:
                return f"{parts[2]}/{parts[1]}/{parts[0]} {time_part}"
        return s[:19] if len(s) >= 19 else s
    except Exception:
        return s[:19] if len(s) >= 19 else s


def parse_cfdi_xml(xml_path: str) -> dict:
    with open(xml_path, "rb") as f:
        raw = f.read()
    raw = _strip_ns(raw)
    root = ET.fromstring(raw)

    comp = root
    emisor = _find(comp, "Emisor")
    receptor = _find(comp, "Receptor")
    conceptos = _find(comp, "Conceptos")
    impuestos = _find(comp, "Impuestos")
    complemento = _find(comp, "Complemento")
    tfd = None
    if complemento:
        for c in complemento:
            if (c.tag.split("}")[-1] if "}" in c.tag else c.tag) == "TimbreFiscalDigital":
                tfd = c
                break

    subtotal = _float(_text(comp, "SubTotal") or comp.get("SubTotal"))
    descuento = _float(_text(comp, "Descuento") or comp.get("Descuento"))
    total = _float(_text(comp, "Total") or comp.get("Total"))
    total_trasladados = _float(_text(impuestos, "TotalImpuestosTrasladados") if impuestos else 0)
    total_retenidos = _float(_text(impuestos, "TotalImpuestosRetenidos") if impuestos else 0)
    traslado_iva_tasa = 0.16
    if impuestos:
        for tr in _find_all(_find(impuestos, "Traslados"), "Traslado"):
            if _text(tr, "Impuesto") == "002":
                traslado_iva_tasa = _float(tr.get("TasaOCuota"), 0.16)
                break
    retenciones_detalle = {}
    if impuestos:
        ret_node = _find(impuestos, "Retenciones")
        if ret_node:
            for r in _find_all(ret_node, "Retencion"):
                cod = _text(r, "Impuesto")
                imp = _float(r.get("Importe"))
                if cod:
                    retenciones_detalle[cod] = retenciones_detalle.get(cod, 0) + imp

    conceptos_list = []
    for c in _find_all(conceptos, "Concepto"):
        imp_node = _find(c, "Impuestos")
        traslados = []
        retenciones = []
        if imp_node:
            for tr in _find_all(_find(imp_node, "Traslados"), "Traslado"):
                traslados.append({
                    "impuesto": _text(tr, "Impuesto"),
                    "tipo": _text(tr, "TipoFactor"),
                    "base": _float(tr.get("Base")),
                    "tasa": _float(tr.get("TasaOCuota")),
                    "importe": _float(tr.get("Importe")),
                })
            for ret in _find_all(_find(imp_node, "Retenciones"), "Retencion"):
                retenciones.append({
                    "impuesto": _text(ret, "Impuesto"),
                    "tipo": _text(ret, "TipoFactor"),
                    "base": _float(ret.get("Base")),
                    "tasa": _float(ret.get("TasaOCuota")),
                    "importe": _float(ret.get("Importe")),
                })
        concepto = {
            "clave_prod_serv": _text(c, "ClaveProdServ"),
            "no_identificacion": _text(c, "NoIdentificacion"),
            "cantidad": _float(c.get("Cantidad")),
            "clave_unidad": _text(c, "ClaveUnidad"),
            "unidad": _text(c, "Unidad"),
            "descripcion": _text(c, "Descripcion"),
            "valor_unitario": _float(c.get("ValorUnitario")),
            "importe": _float(c.get("Importe")),
            "descuento": _float(c.get("Descuento")),
            "objeto_imp": _text(c, "ObjetoImp"),
            "traslados": traslados,
            "retenciones": retenciones,
        }
        conceptos_list.append(concepto)

    sello_cfd = _text(comp, "Sello")
    no_certificado = _text(comp, "NoCertificado")

    sello_sat = _text(tfd, "SelloSAT") if tfd else ""
    no_certificado_sat = _text(tfd, "NoCertificadoSAT") if tfd else ""

    def cadena_original_tfd():
        if not tfd:
            return ""
        u = _text(tfd, "UUID")
        ft = _text(tfd, "FechaTimbrado")
        rfc = _text(tfd, "RfcProvCertif")
        sc = _text(tfd, "SelloCFD")
        nc = _text(tfd, "NoCertificadoSAT")
        return f"||1.1|{u}|{ft}|{rfc}|{sc}|{nc}||"

    emisor_data = {}
    if emisor is not None:
        emisor_data = {
            "rfc": _text_any(emisor, "Rfc", "RFC"),
            "nombre": _text_any(emisor, "Nombre"),
            "regimen_fiscal": _text_any(emisor, "RegimenFiscal", "Regimen"),
        }
    receptor_data = {}
    if receptor is not None:
        receptor_data = {
            "rfc": _text_any(receptor, "Rfc", "RFC"),
            "nombre": _text_any(receptor, "Nombre"),
            "uso_cfdi": _text_any(receptor, "UsoCFDI", "UsoCFDI"),
            "domicilio_fiscal": _text_any(receptor, "DomicilioFiscalReceptor", "DomicilioFiscal"),
            "regimen_fiscal": _text_any(receptor, "RegimenFiscalReceptor", "RegimenFiscal"),
        }

    return {
        "version": _text(comp, "Version", "4.0"),
        "serie": _text(comp, "Serie"),
        "folio": _text(comp, "Folio"),
        "fecha": _text(comp, "Fecha"),
        "tipo_comprobante": _text(comp, "TipoDeComprobante"),
        "moneda": _text(comp, "Moneda", "MXN"),
        "forma_pago": _text(comp, "FormaPago"),
        "metodo_pago": _text(comp, "MetodoPago"),
        "lugar_expedicion": _text(comp, "LugarExpedicion"),
        "exportacion": _text(comp, "Exportacion"),
        "condiciones_pago": _text(comp, "CondicionesDePago"),
        "subtotal": subtotal,
        "descuento": descuento,
        "total": total,
        "total_trasladados": total_trasladados,
        "total_retenidos": total_retenidos,
        "traslado_iva_tasa": traslado_iva_tasa,
        "retenciones_detalle": retenciones_detalle,
        "emisor": emisor_data,
        "receptor": receptor_data,
        "conceptos": conceptos_list,
        "uuid": _text(tfd, "UUID") if tfd else "",
        "fecha_timbrado": _text(tfd, "FechaTimbrado") if tfd else "",
        "rfc_prov_certif": _text(tfd, "RfcProvCertif") if tfd else "",
        "sello_cfd": sello_cfd,
        "sello_sat": sello_sat,
        "no_certificado": no_certificado,
        "no_certificado_sat": no_certificado_sat,
        "cadena_original": cadena_original_tfd(),
    }


def _label(catalog: dict, raw: str) -> str:
    r = (raw or "").strip()
    return catalog.get(r, catalog.get(r.upper(), raw if raw else "-"))


def _val(v: str, empty: str = "—") -> str:
    """Devuelve el valor o el texto para vacío."""
    s = (v or "").strip()
    return s if s else empty

def build_pdf(data: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
    )
    story = []
    fs = 9
    fs_small = 8

    style_label = ParagraphStyle(name="Label", fontSize=fs, leading=fs + 2, textColor=colors.HexColor("#333"))
    style_value = ParagraphStyle(name="Value", fontSize=fs, leading=fs + 2, textColor=colors.HexColor("#111"))
    style_section = ParagraphStyle(name="Section", fontSize=11, leading=14, textColor=colors.HexColor("#1a1a1a"), spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold")
    style_h3 = ParagraphStyle(name="H3", fontSize=10, leading=14, textColor=colors.black, spaceBefore=12, spaceAfter=6, fontName="Helvetica-Bold")
    style_seal = ParagraphStyle(name="Seal", fontSize=fs_small, leading=10, textColor=colors.HexColor("#444"), fontName="Courier")

    em = data.get("emisor", {})
    rec = data.get("receptor", {})

    style_lbl = ParagraphStyle(name="HdrLbl", fontSize=fs, leading=fs+2, textColor=colors.HexColor("#555"), wordWrap="LTR")
    style_val = ParagraphStyle(name="HdrVal", fontSize=fs, leading=fs+2, textColor=colors.black, wordWrap="LTR")

    def _p(text: str, style=style_val) -> Paragraph:
        return Paragraph(str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)

    # ——— Datos del emisor ———
    story.append(Paragraph("Datos del emisor", style_section))
    em_rows = [
        ["RFC", _val(em.get("rfc"))],
        ["Nombre o razón social", _val(em.get("nombre"))],
        ["Régimen fiscal", _val(_label(REGIMEN_FISCAL, em.get("regimen_fiscal", "")))],
        ["Lugar de expedición (C.P.)", _val(data.get("lugar_expedicion"))],
    ]
    t_em = Table(em_rows, colWidths=[2.0 * inch, 4.2 * inch])
    t_em.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
    ]))
    story.append(t_em)
    story.append(Spacer(1, 12))

    # ——— Datos del receptor ———
    story.append(Paragraph("Datos del receptor", style_section))
    rec_rows = [
        ["RFC", _val(rec.get("rfc"))],
        ["Nombre o razón social", _val(rec.get("nombre"))],
        ["Código postal", _val(rec.get("domicilio_fiscal"))],
        ["Régimen fiscal", _val(_label(REGIMEN_FISCAL, rec.get("regimen_fiscal", "")))],
        ["Uso del CFDI", _val(_label(USO_CFDI, rec.get("uso_cfdi", "")))],
    ]
    t_rec = Table(rec_rows, colWidths=[2.0 * inch, 4.2 * inch])
    t_rec.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f8f8")),
    ]))
    story.append(t_rec)
    story.append(Spacer(1, 12))

    # ——— Datos del comprobante ———
    story.append(Paragraph("Datos del comprobante", style_section))
    fecha_fmt = _format_fecha_emision(data.get("fecha", "") or "")
    comp_rows = [
        ["Folio fiscal (UUID)", _val(data.get("uuid"))],
        ["No. de serie del CSD", _val(data.get("no_certificado"))],
        ["Fecha y hora de emisión", _val(fecha_fmt)],
        ["Efecto del comprobante", _val({"I": "Ingreso", "E": "Egreso", "N": "Nómina", "P": "Pago", "T": "Traslado"}.get((data.get("tipo_comprobante") or "I").upper(), "Ingreso"))],
        ["Exportación", _val(_label(EXPORTACION, data.get("exportacion", "01")))],
    ]
    t_comp = Table(comp_rows, colWidths=[2.0 * inch, 4.2 * inch])
    t_comp.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f4f0")),
    ]))
    story.append(t_comp)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Conceptos", style_h3))

    conceptos = data.get("conceptos") or []
    if conceptos:
        # Tabla simplificada: Clave, Descripción, Cant., Unidad, Valor unit., Importe, Objeto imp.
        style_th = ParagraphStyle(name="TH", fontSize=fs_small, leading=10, fontName="Helvetica-Bold", wordWrap="LTR")
        style_td = ParagraphStyle(name="TD", fontSize=fs_small, leading=10, wordWrap="LTR")
        headers = ["Clave", "Descripción", "Cant.", "Unidad", "Valor unit.", "Importe", "Objeto imp."]
        header_cells = [_p(h, style_th) for h in headers]
        rows = [header_cells]
        for c in conceptos:
            obj = c.get("objeto_imp", "02")
            obj_label = OBJETO_IMP.get(obj, "Sí objeto de impuesto")
            unidad_label = _label(CLAVE_UNIDAD, c.get("clave_unidad", "")) or c.get("unidad", "-")
            desc_raw = c.get("descripcion") or "-"
            desc = desc_raw[:80] + ("…" if len(desc_raw) > 80 else "")
            cant = c.get("cantidad", 0) or 0
            val_uni = c.get("valor_unitario", 0) or 0
            imp_val = c.get("importe", 0) or 0
            rows.append([
                _p(c.get("clave_prod_serv") or "-", style_td),
                _p(desc, style_td),
                _p(f"{cant:,.4f}".rstrip("0").rstrip(".") if cant else "-", style_td),
                _p(unidad_label, style_td),
                _p(f"{val_uni:,.2f}".rstrip("0").rstrip(".") if val_uni else "-", style_td),
                _p(f"{imp_val:,.2f}" if imp_val else "-", style_td),
                _p(obj_label, style_td),
            ])
        t1 = Table(rows, colWidths=[0.9*inch, 2.4*inch, 0.5*inch, 0.9*inch, 0.8*inch, 0.9*inch, 1.1*inch])
        t1.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e0e0")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ccc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t1)

        for c in conceptos:
            desc = (c.get("descripcion") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if desc and len(desc) > 80:
                story.append(Spacer(1, 8))
                story.append(Paragraph(f"<b>Descripción completa:</b> {desc}", ParagraphStyle(name="Desc", fontSize=fs_small, leading=11, leftIndent=0, spaceBefore=2, spaceAfter=8)))

        imp_rows = [[_p("Impuesto", style_th), _p("Tipo", style_th), _p("Base", style_th), _p("Tipo Factor", style_th), _p("Tasa o Cuota", style_th), _p("Importe", style_th)]]
        for c in conceptos:
            for tr in c.get("traslados", []):
                imp_c = IMPUESTO.get(tr.get("impuesto"), tr.get("impuesto", ""))
                tasa = tr.get("tasa", 0) or 0
                tipo = tr.get("tipo", "")
                tasa_pct = f"{tasa*100:.2f}%" if tipo == "Tasa" else str(tasa)
                imp_rows.append([
                    _p(imp_c, style_td), _p("Traslado", style_td), _p(f"{(tr.get('base') or 0):,.2f}", style_td),
                    _p(IMPUESTO_TIPO.get(tipo, tipo or "-"), style_td), _p(tasa_pct, style_td), _p(f"{(tr.get('importe') or 0):,.2f}", style_td),
                ])
            for ret in c.get("retenciones", []):
                imp_c = IMPUESTO.get(ret.get("impuesto"), ret.get("impuesto", ""))
                tasa = ret.get("tasa", 0) or 0
                tipo = ret.get("tipo", "")
                tasa_pct = f"{tasa*100:.2f}%" if tipo == "Tasa" else str(tasa)
                imp_rows.append([
                    _p(imp_c, style_td), _p("Retención", style_td), _p(f"{(ret.get('base') or 0):,.2f}", style_td),
                    _p(IMPUESTO_TIPO.get(tipo, tipo or "-"), style_td), _p(tasa_pct, style_td), _p(f"{(ret.get('importe') or 0):,.2f}", style_td),
                ])
        if len(imp_rows) > 1:
            story.append(Spacer(1, 8))
            t2 = Table(imp_rows, colWidths=[1.0*inch, 0.9*inch, 1.2*inch, 0.9*inch, 1.0*inch, 1.0*inch])
            t2.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e0e0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(t2)

    story.append(Spacer(1, 18))

    story.append(Paragraph("Pago y totales", style_h3))
    subtotal = data.get("subtotal", 0)
    total_tras = data.get("total_trasladados", 0)
    total_ret = data.get("total_retenidos", 0)
    total = data.get("total", 0)
    tasa_iva = data.get("traslado_iva_tasa", 0.16)
    mon = data.get("moneda", "MXN")

    pay_left = [
        ("Moneda", MONEDA.get(mon, mon)),
        ("Forma de pago", _label(FORMA_PAGO, data.get("forma_pago", ""))),
        ("Método de pago", _label(METODO_PAGO, data.get("metodo_pago", "PUE"))),
    ]
    totals_right = [
        (f"Impuestos trasladados IVA {tasa_iva*100:.2f}%", f"$ {total_tras:,.2f}"),
    ]
    ret_det = data.get("retenciones_detalle", {})
    if ret_det:
        totals_right.append(("Impuestos retenidos", ""))
        for cod, imp in ret_det.items():
            totals_right.append((IMPUESTO.get(cod, cod), f"$ {imp:,.2f}"))
    elif total_ret > 0:
        totals_right.append(("Impuestos retenidos", f"$ {total_ret:,.2f}"))
    else:
        totals_right.append(("Impuestos retenidos", "-"))
    totals_right.insert(0, ("Subtotal", f"$ {subtotal:,.2f}"))
    totals_right.append(("Total", f"$ {total:,.2f}"))

    pay_tot_rows = []
    for i in range(max(len(pay_left), len(totals_right))):
        l = pay_left[i] if i < len(pay_left) else ("", "")
        r = totals_right[i] if i < len(totals_right) else ("", "")
        rlab = (r[0] + ":") if r[0] and not r[0].endswith("%") else (r[0] or "")
        pay_tot_rows.append([f"{l[0]}:", l[1], rlab, r[1]])
    t3 = Table(pay_tot_rows, colWidths=[1.6*inch, 2.6*inch, 2.0*inch, 1.6*inch])
    t3.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("TEXTCOLOR", (0, 0), (1, -1), colors.HexColor("#333")),
        ("TEXTCOLOR", (2, 0), (3, -1), colors.black),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), fs),
        ("LINEAFTER", (1, 0), (1, -1), 0.5, colors.HexColor("#ccc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
    ]))
    story.append(t3)

    sello_cfd = data.get("sello_cfd", "")
    sello_sat = data.get("sello_sat", "")
    if sello_cfd:
        story.append(Spacer(1, 18))
        story.append(Paragraph("Sello digital del CFDI:", style_h3))
        for i in range(0, len(sello_cfd), 100):
            story.append(Paragraph(sello_cfd[i : i + 100], style_seal))
    if sello_sat:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Sello digital del SAT:", style_h3))
        for i in range(0, len(sello_sat), 100):
            story.append(Paragraph(sello_sat[i : i + 100], style_seal))

    cadena = data.get("cadena_original", "")
    sello_cfd = data.get("sello_cfd", "")
    uuid_qr = data.get("uuid", "")
    em_rfc = em.get("rfc", "")
    rec_rfc = rec.get("rfc", "")
    total_qr = data.get("total", 0)
    fe_sello = sello_cfd[-8:] if len(sello_cfd) >= 8 else ""
    url_verif = f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id={uuid_qr}&re={em_rfc}&rr={rec_rfc}&tt={total_qr:.2f}&fe={fe_sello}"
    qr_img = None
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=3, border=2)
        qr.add_data(url_verif)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        qr_img = Image(qr_buffer, width=1.2*inch, height=1.2*inch)
    except Exception:
        pass

    seal_content = []
    if cadena and qr_img:
        seal_content = [[qr_img, Paragraph("Cadena Original del complemento de certificación digital del SAT:<br/>" + "<br/>".join(cadena[i:i+90] for i in range(0, min(len(cadena), 400), 90)), style_seal)]]
    elif cadena:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Cadena Original del complemento de certificación digital del SAT:", style_h3))
        for i in range(0, len(cadena), 100):
            story.append(Paragraph(cadena[i : i + 100], style_seal))
    if seal_content:
        t_qr = Table(seal_content, colWidths=[1.4*inch, 5.5*inch])
        t_qr.setStyle(TableStyle([("VALIGN", (0, 0), (0, -1), "TOP")]))
        story.append(Spacer(1, 6))
        story.append(t_qr)

    rfc_prov = data.get("rfc_prov_certif", "")
    no_cert_sat = data.get("no_certificado_sat", "")
    fecha_timb = _format_fecha_emision(data.get("fecha_timbrado", ""))
    if rfc_prov:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"RFC del proveedor de certificación: {rfc_prov}", style_value))
        story.append(Paragraph(f"No. de serie del certificado SAT {no_cert_sat}", style_value))
        story.append(Paragraph(f"Fecha y hora de certificación: {fecha_timb}", style_value))

    story.append(Spacer(1, 12))
    em_rfc = em.get("rfc", "")
    uuid = data.get("uuid", "")
    story.append(Paragraph(f"RFC emisor: {em_rfc}  Folio fiscal: {uuid}", ParagraphStyle(name="Foot", fontSize=fs_small, textColor=colors.HexColor("#444"))))
    t_foot = Table([["Este documento es una representación impresa de un CFDI", "Página 1 de 1"]], colWidths=[5*inch, 3*inch])
    t_foot.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), fs_small),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#666")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(t_foot)

    doc.build(story)
    return buffer.getvalue()

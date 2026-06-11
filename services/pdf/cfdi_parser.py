"""Parse CFDI 4.0 XML into the dict shape expected by templates/pdf/cfdi.html."""
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Optional

from num2words import num2words

from . import cfdi_catalogs as cat


def _strip_ns(content: bytes) -> bytes:
    """Drop xmlns prefixes so we can navigate without ns awareness."""
    text = content.decode("utf-8", errors="replace").lstrip("\ufeff")
    text = re.sub(r"<\w+:(\w+)(\s|>)", r"<\1\2", text)
    text = re.sub(r"</\w+:(\w+)\s*>", r"</\1>", text)
    text = re.sub(r'\s+xmlns[^=]*="[^"]*"', "", text)
    text = re.sub(r'\s(\w+):(\w+)=', r" \2=", text)
    return text.encode("utf-8")


def _find(el: Optional[ET.Element], tag: str) -> Optional[ET.Element]:
    if el is None:
        return None
    for child in el:
        if child.tag == tag:
            return child
    return None


def _find_all(el: Optional[ET.Element], tag: str) -> list:
    if el is None:
        return []
    return [c for c in el if c.tag == tag]


def _attr(el: Optional[ET.Element], name: str, default: str = "") -> str:
    if el is None:
        return default
    return (el.get(name) or default).strip()


def _money(s: str) -> str:
    """Format SAT decimal (1.000000) to currency-friendly (1.00)."""
    try:
        d = Decimal(str(s or "0"))
    except Exception:
        return "0.00"
    return f"{d:,.2f}"


def _fecha(iso: str) -> str:
    """ISO datetime → 'YYYY-MM-DD HH:MM:SS'."""
    if not iso:
        return ""
    s = iso.strip().replace("T", " ").replace("Z", "")
    return s[:19]


def _importe_letra(total: str, moneda: str = "MXN") -> str:
    """Convert numeric total to Spanish words: '1234.50' → 'Mil doscientos treinta y cuatro pesos 50/100 M.N.'"""
    try:
        d = Decimal(str(total or "0"))
    except Exception:
        return ""
    entero = int(d)
    cents = int((d - entero) * 100)
    unidad = "pesos" if moneda == "MXN" else moneda
    moneda_mn = "M.N." if moneda == "MXN" else moneda
    try:
        if entero == 0:
            words = "cero"
        elif entero == 1:
            words = "un"
        else:
            words = num2words(entero, lang="es")
        words = words.capitalize()
    except Exception:
        words = str(entero)
    return f"{words} {unidad} {cents:02d}/100 {moneda_mn}"


def _cadena_original_tfd(tfd: ET.Element) -> str:
    """Build cadena original del Complemento de Certificación del SAT (Anexo 20).

    Format: ||{Version}|{UUID}|{FechaTimbrado}|{RfcProvCertif}|{Leyenda?}|{SelloCFD}|{NoCertificadoSAT}||
    Leyenda is empty for the standard case.
    """
    if tfd is None:
        return ""
    version = _attr(tfd, "Version", "1.1")
    uuid = _attr(tfd, "UUID")
    fecha = _attr(tfd, "FechaTimbrado")
    prov = _attr(tfd, "RfcProvCertif")
    leyenda = _attr(tfd, "Leyenda", "")
    sello = _attr(tfd, "SelloCFD")
    no_cert = _attr(tfd, "NoCertificadoSAT")
    return f"||{version}|{uuid}|{fecha}|{prov}|{leyenda}|{sello}|{no_cert}||"


def parse_cfdi(xml_path: str) -> dict:
    """Parse a CFDI 4.0 XML file and return the Jinja context dict.

    Returns the shape documented at the top of templates/pdf/cfdi.html.
    Raises ValueError if XML is malformed or not a recognizable CFDI.
    """
    with open(xml_path, "rb") as f:
        raw = f.read()
    try:
        root = ET.fromstring(_strip_ns(raw))
    except ET.ParseError as e:
        raise ValueError(f"XML inválido: {e}") from e

    emisor = _find(root, "Emisor")
    receptor = _find(root, "Receptor")
    conceptos_el = _find(root, "Conceptos")
    impuestos_el = _find(root, "Impuestos")
    complemento = _find(root, "Complemento")
    tfd = _find(complemento, "TimbreFiscalDigital") if complemento is not None else None

    if emisor is None or receptor is None or tfd is None:
        raise ValueError("CFDI no contiene Emisor/Receptor/TimbreFiscalDigital")

    tipo_cb = _attr(root, "TipoDeComprobante")
    emisor_regimen = _attr(emisor, "RegimenFiscal")
    receptor_regimen = _attr(receptor, "RegimenFiscalReceptor")
    moneda = _attr(root, "Moneda", "MXN")

    conceptos = []
    for c in _find_all(conceptos_el, "Concepto"):
        conceptos.append({
            "clave_prod_serv": _attr(c, "ClaveProdServ"),
            "descripcion": _attr(c, "Descripcion"),
            "descripcion_extra": "",
            "cantidad": _attr(c, "Cantidad", "1"),
            "clave_unidad": _attr(c, "ClaveUnidad"),
            "valor_unitario": _money(_attr(c, "ValorUnitario")),
            "importe": _money(_attr(c, "Importe")),
        })

    iva_traslado = Decimal("0")
    iva_retenido = Decimal("0")
    isr_retenido = Decimal("0")
    if impuestos_el is not None:
        for tr in _find_all(_find(impuestos_el, "Traslados"), "Traslado"):
            if _attr(tr, "Impuesto") == "002":
                iva_traslado += Decimal(_attr(tr, "Importe", "0") or "0")
        for rt in _find_all(_find(impuestos_el, "Retenciones"), "Retencion"):
            imp = _attr(rt, "Impuesto")
            amt = Decimal(_attr(rt, "Importe", "0") or "0")
            if imp == "002":
                iva_retenido += amt
            elif imp == "001":
                isr_retenido += amt

    total = _attr(root, "Total")
    subtotal = _attr(root, "SubTotal")

    no_cert_sat = _attr(tfd, "NoCertificadoSAT")
    return {
        "doc_type_label": f"Factura · {cat.label(cat.TIPO_COMPROBANTE, tipo_cb, 'CFDI')}",
        "emisor": {
            "name": _attr(emisor, "Nombre"),
            "rfc": _attr(emisor, "Rfc"),
            "regimen_fiscal": emisor_regimen,
            "regimen_fiscal_label": cat.label(cat.REGIMEN_FISCAL, emisor_regimen),
            "codigo_postal": _attr(root, "LugarExpedicion"),
            "moneda": moneda,
        },
        "fiscal": {
            "uuid": _attr(tfd, "UUID"),
            "tipo_comprobante": tipo_cb,
            "tipo_label": cat.label(cat.TIPO_COMPROBANTE, tipo_cb),
            "version": _attr(root, "Version", "4.0"),
            "no_certificado_emisor": _attr(root, "NoCertificado"),
            "fecha_emision": _fecha(_attr(root, "Fecha")),
            "fecha_timbrado": _fecha(_attr(tfd, "FechaTimbrado")),
            "forma_pago": _attr(root, "FormaPago"),
            "forma_pago_label": cat.label(cat.FORMA_PAGO, _attr(root, "FormaPago")),
            "metodo_pago": _attr(root, "MetodoPago"),
            "metodo_pago_label": cat.label(cat.METODO_PAGO, _attr(root, "MetodoPago")),
        },
        "receptor": {
            "name": _attr(receptor, "Nombre"),
            "rfc": _attr(receptor, "Rfc"),
            "regimen_fiscal": receptor_regimen,
            "regimen_fiscal_label": cat.label(cat.REGIMEN_FISCAL, receptor_regimen),
            "codigo_postal": _attr(receptor, "DomicilioFiscalReceptor"),
            "uso_cfdi": _attr(receptor, "UsoCFDI"),
            "uso_cfdi_label": cat.label(cat.USO_CFDI, _attr(receptor, "UsoCFDI")),
        },
        "conceptos": conceptos,
        "totales": {
            "subtotal": _money(subtotal),
            "iva_trasladado": f"{iva_traslado:,.2f}",
            "iva_retenido": f"{iva_retenido:,.2f}" if iva_retenido > 0 else None,
            "isr_retenido": f"{isr_retenido:,.2f}" if isr_retenido > 0 else None,
            "total": _money(total),
            "moneda": moneda,
            "importe_letra": _importe_letra(total, moneda),
        },
        "sello": {
            "no_certificado_sat": no_cert_sat,
            "sello_cfd": _attr(root, "Sello"),
            "sello_sat": _attr(tfd, "SelloSAT"),
            "cadena_original_tfd": _cadena_original_tfd(tfd),
        },
        # Raw fields needed by the QR builder
        "_qr_fields": {
            "uuid": _attr(tfd, "UUID"),
            "rfc_emisor": _attr(emisor, "Rfc"),
            "rfc_receptor": _attr(receptor, "Rfc"),
            "total": total,
            "sello_cfd": _attr(root, "Sello"),
        },
    }

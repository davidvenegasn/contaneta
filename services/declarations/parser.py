"""Parse SAT declaration PDFs using regex on extracted text."""
import io
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Common regex patterns
RFC_PATTERN = re.compile(r'\b([A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{3})\b')
LINEA_CAPTURA_PATTERN = re.compile(r'\b(\d{4}\s?-?\s?\d{4}\s?-?\s?\d{4}\s?-?\s?\d{4})\b')
FOLIO_ACUSE_PATTERN = re.compile(
    r'(?:Folio|N(?:ú|u)mero de operaci(?:ó|o)n)[:\s]+([A-Z0-9]{6,20})', re.I
)
FECHA_PATTERN = re.compile(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})')
MONTO_PATTERN = re.compile(r'\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)')


def extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF, page by page, joined."""
    import pdfplumber

    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
    return "\n".join(text_parts)


def extract_from_pdf(pdf_bytes: bytes) -> dict:
    """Extract fiscal fields from a SAT declaration PDF.

    Returns dict with: rfc, tipo, periodo_ym, ejercicio, fecha_presentacion,
    fecha_vencimiento, saldo_a_cargo, saldo_a_favor, total_a_pagar,
    linea_captura, folio_acuse, numero_operacion, parse_confidence (0-1).
    """
    text = extract_text(pdf_bytes)
    result = {"raw_text": text[:5000], "parse_confidence": 0.0}

    # RFC
    rfc_matches = RFC_PATTERN.findall(text)
    if rfc_matches:
        result["rfc"] = rfc_matches[0].upper()
        result["parse_confidence"] += 0.2

    # Linea de captura
    lc = LINEA_CAPTURA_PATTERN.search(text)
    if lc:
        result["linea_captura"] = re.sub(r'\s|-', '', lc.group(1))
        result["parse_confidence"] += 0.2

    # Folio acuse
    fa = FOLIO_ACUSE_PATTERN.search(text)
    if fa:
        result["folio_acuse"] = fa.group(1)
        result["parse_confidence"] += 0.15

    # Tipo de declaracion
    result["tipo"] = _classify_tipo(text)
    if result.get("tipo"):
        result["parse_confidence"] += 0.15

    # Periodo
    periodo = _extract_periodo(text)
    if periodo:
        result["periodo_ym"] = periodo
        result["parse_confidence"] += 0.1

    # Saldos
    saldo_cargo = _extract_amount_near(text, [
        r'(?:Cantidad|Total)\s*a\s*(?:cargo|pagar)',
        r'Importe a pagar',
    ])
    if saldo_cargo is not None:
        result["saldo_a_cargo"] = saldo_cargo
        result["total_a_pagar"] = saldo_cargo
        result["parse_confidence"] += 0.1

    saldo_favor = _extract_amount_near(text, [
        r'Saldo a favor', r'Cantidad a favor',
    ])
    if saldo_favor is not None:
        result["saldo_a_favor"] = saldo_favor
        result["parse_confidence"] += 0.05

    # Fechas
    fechas = _extract_dates(text)
    if "fecha_presentacion" in fechas:
        result["fecha_presentacion"] = fechas["fecha_presentacion"]
        result["parse_confidence"] += 0.05
    if "fecha_vencimiento" in fechas:
        result["fecha_vencimiento"] = fechas["fecha_vencimiento"]
        result["parse_confidence"] += 0.05

    result["parse_confidence"] = min(1.0, result["parse_confidence"])
    return result


def _classify_tipo(text: str) -> Optional[str]:
    """Classify declaration type from text content."""
    t = text.lower()
    if "isr" in t and ("provisional" in t or "mensual" in t):
        return "mensual_isr"
    if "iva" in t and ("definitivo" in t or "mensual" in t):
        return "mensual_iva"
    if "ieps" in t and "mensual" in t:
        return "mensual_ieps"
    if "anual" in t and "isr" in t:
        return "anual_isr"
    if "pago referenciado" in t or "captura de pago" in t:
        return "pago_referenciado"
    if "informativa" in t:
        return "informativa"
    return None


def _extract_periodo(text: str) -> Optional[str]:
    """Extract periodo as YYYY-MM."""
    MONTHS = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    }
    m = re.search(
        r'(?:periodo|mes(?:\s+a\s+declarar)?)\s*:?\s*(\w+)\s+(?:de\s+)?(\d{4})', text, re.I
    )
    if m:
        month_name = m.group(1).lower()
        year = m.group(2)
        if month_name in MONTHS:
            return f"{year}-{MONTHS[month_name]}"
    m = re.search(r'(\d{2})[/\-](\d{4})', text)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return None


def _extract_amount_near(text: str, label_patterns: list[str]) -> Optional[float]:
    """Find a dollar amount near a label pattern."""
    for label_pat in label_patterns:
        match = re.search(label_pat + r'[\s:$]*' + MONTO_PATTERN.pattern, text, re.I)
        if match:
            # The last group is the amount
            groups = match.groups()
            for g in reversed(groups):
                if g and re.match(r'\d', g):
                    try:
                        return float(g.replace(",", ""))
                    except ValueError:
                        continue
    return None


def _extract_dates(text: str) -> dict:
    """Extract presentation and due dates."""
    result = {}
    fp = re.search(
        r'Fecha\s+(?:de\s+)?presentaci(?:ó|o)n[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})',
        text, re.I,
    )
    if fp:
        result["fecha_presentacion"] = _normalize_date(fp.group(1))
    fv = re.search(
        r'Fecha\s+(?:l(?:í|i)mite\s+de\s+pago|vencimiento)[:\s]+'
        r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})',
        text, re.I,
    )
    if fv:
        result["fecha_vencimiento"] = _normalize_date(fv.group(1))
    return result


def _normalize_date(s: str) -> str:
    """Convert DD/MM/YYYY or DD-MM-YYYY to YYYY-MM-DD."""
    parts = re.split(r'[/\-]', s)
    if len(parts) == 3:
        d, m, y = parts
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return s

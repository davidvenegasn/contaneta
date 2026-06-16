"""Parse Constancia de Situación Fiscal PDFs issued by SAT.

Extracts: RFC, CURP (if persona física), razón social, régimen fiscal,
código postal, domicilio, and obligaciones fiscales.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Known régimen fiscal codes and labels
REGIMEN_MAP = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios",
    "606": "Arrendamiento",
    "607": "Régimen de Enajenación o Adquisición de Bienes",
    "608": "Demás ingresos",
    "610": "Residentes en el Extranjero",
    "611": "Ingresos por Dividendos",
    "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "615": "Régimen de los ingresos por obtención de premios",
    "616": "Sin obligaciones fiscales",
    "620": "Sociedades Cooperativas de Producción",
    "621": "Incorporación Fiscal",
    "622": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "Opcional para Grupos de Sociedades",
    "624": "Coordinados",
    "625": "Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza",
}


def extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF using pdfplumber."""
    import pdfplumber
    import io

    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def parse_constancia(pdf_bytes: bytes) -> dict:
    """Parse a Constancia de Situación Fiscal PDF.

    Returns dict with extracted fields and confidence score.
    """
    text = extract_text(pdf_bytes)
    if not text.strip():
        return {"error": "No se pudo extraer texto del PDF", "confidence": 0}

    result = {
        "rfc": _extract_rfc(text),
        "curp": _extract_curp(text),
        "razon_social": _extract_razon_social(text),
        "regimen_fiscal": _extract_regimen(text),
        "codigo_postal": _extract_codigo_postal(text),
        "domicilio": _extract_domicilio(text),
        "obligaciones": _extract_obligaciones(text),
    }

    # Confidence: count how many key fields were extracted
    key_fields = ["rfc", "razon_social", "regimen_fiscal", "codigo_postal"]
    found = sum(1 for f in key_fields if result.get(f))
    result["confidence"] = round(found / len(key_fields), 2)

    return result


def _extract_rfc(text: str) -> Optional[str]:
    """Extract RFC from constancia text."""
    # Pattern: "RFC:" or "R.F.C." followed by the RFC value
    m = re.search(
        r'(?:RFC|R\.F\.C\.?)\s*:?\s*([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})',
        text, re.I
    )
    if m:
        return m.group(1).upper()
    # Fallback: any RFC-like pattern
    m = re.search(r'\b([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b', text)
    return m.group(1).upper() if m else None


def _extract_curp(text: str) -> Optional[str]:
    """Extract CURP (18 chars) from text."""
    m = re.search(
        r'(?:CURP|C\.U\.R\.P\.?)\s*:?\s*([A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d)',
        text, re.I
    )
    if m:
        return m.group(1).upper()
    # Fallback
    m = re.search(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d)\b', text)
    return m.group(1).upper() if m else None


def _extract_razon_social(text: str) -> Optional[str]:
    """Extract razón social / denominación."""
    patterns = [
        r'(?:Denominaci[oó]n|Raz[oó]n\s+Social|Nombre)[:\s]+(.+?)(?:\n|RFC|R\.F\.C)',
        r'(?:Nombre\s*,?\s*Denominaci[oó]n|Denominaci[oó]n\s+o\s+Raz[oó]n\s+Social)[:\s]+(.+?)(?:\n)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            name = m.group(1).strip()
            # Clean trailing artifacts
            name = re.sub(r'\s+$', '', name)
            if len(name) > 3:
                return name
    return None


def _extract_regimen(text: str) -> Optional[str]:
    """Extract régimen fiscal code."""
    # Look for 3-digit code near "Régimen" label
    m = re.search(
        r'(?:R[eé]gimen\s+Fiscal|Régimen)[:\s]*(\d{3})',
        text, re.I
    )
    if m:
        code = m.group(1)
        if code in REGIMEN_MAP:
            return code

    # Fallback: search for known regime descriptions
    for code, desc in REGIMEN_MAP.items():
        if desc.lower() in text.lower():
            return code

    return None


def _extract_codigo_postal(text: str) -> Optional[str]:
    """Extract código postal (5 digits)."""
    # Pattern: "Código Postal:" or "C.P." followed by 5 digits
    m = re.search(
        r'(?:C[oó]digo\s+Postal|C\.P\.?)\s*:?\s*(\d{5})',
        text, re.I
    )
    return m.group(1) if m else None


def _extract_domicilio(text: str) -> Optional[str]:
    """Extract domicilio fiscal (best-effort multi-line)."""
    m = re.search(
        r'(?:Domicilio\s+Fiscal|Ubicaci[oó]n\s+Fiscal)[:\s]+(.+?)(?:\n\s*\n|Régimen|Obligaciones|Actividad)',
        text, re.I | re.DOTALL
    )
    if m:
        addr = m.group(1).strip()
        # Collapse whitespace
        addr = re.sub(r'\s+', ' ', addr)
        if len(addr) > 5:
            return addr
    return None


def _extract_obligaciones(text: str) -> list[str]:
    """Extract obligaciones fiscales as a list of strings."""
    m = re.search(
        r'(?:Obligaciones|Actividades\s+Econ[oó]micas)[:\s]+(.+?)(?:\n\s*\n|$)',
        text, re.I | re.DOTALL
    )
    if not m:
        return []
    block = m.group(1).strip()
    # Split by newlines or bullet patterns
    items = re.split(r'\n|•|–|—|\d+\.', block)
    return [i.strip() for i in items if i.strip() and len(i.strip()) > 3]

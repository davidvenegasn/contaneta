"""
Genera concepto resumen legible para un movimiento preview.
Prioriza UX: descripciones cortas y útiles.
Quita la fecha al inicio del texto (redundante con la columna Fecha).
"""
from __future__ import annotations

import re
from typing import Any

_LEADING_DATE_RE = re.compile(
    r"^\s*\d{1,2}[\s\-]*(?:ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|SET|OCT|NOV|DIC)[\s\-]*\d{2}\s*",
    re.IGNORECASE,
)


def _strip_leading_date(text: str) -> str:
    """Quita fecha DD-MMM-YY o DD MMM YY al inicio."""
    if not text:
        return text
    return _LEADING_DATE_RE.sub("", text).strip()


def build_concept_summary(mov: dict[str, Any]) -> str:
    """
    Produce una descripción corta útil para el movimiento.
    Reutiliza lógica de bank_parse_preview.summarize cuando esté disponible.
    """
    raw = (mov.get("raw_text_normalized") or mov.get("raw_text_original") or mov.get("description_raw") or "").upper()
    raw = _strip_leading_date(raw)
    canal = (mov.get("canal") or mov.get("method") or "").upper()
    contraparte = (mov.get("contraparte_nombre") or (mov.get("extracted") or {}).get("counterparty") or "").strip()
    if "SALDO ANTERIOR" in raw:
        return "Saldo anterior"
    if contraparte and "SPEI" in canal:
        if "RECIBIDO" in raw or "DEPOSITO" in raw or "ABONO" in raw:
            return "Transferencia SPEI recibida de " + contraparte[:40]
        return "Transferencia SPEI a " + contraparte[:40]
    if "PAGO CONCENTRACION" in raw and ("TARJETA" in raw or "TDC" in raw):
        return "Pago tarjeta crédito Banorte"
    if "AMERICAN EXPRES" in raw or "AMEX" in raw:
        return "Pago AMEX"
    if "OXXO" in raw:
        return "Compra en OXXO"
    if "PAGO REFERENCIADO" in raw and "IMPUESTO" in raw:
        return "Pago de impuesto referenciado"
    if "DEPOSITO DE NOMINA" in raw or "NOMINA" in raw:
        return "Depósito de nómina"
    if "DOMICILIACION" in raw and "PROFUTURO" in raw:
        return "Domiciliación Profuturo"
    if "DOMICILIACION" in raw:
        return "Domiciliación"
    if "RETIRO DE EFECTIVO" in raw or "CAJERO" in raw:
        return "Retiro efectivo cajero Banorte"
    if "ABONO POR DISPOSICION" in raw and "TDC" in raw:
        return "Abono por disposición TDC"
    if contraparte:
        return contraparte[:50]
    words = [w for w in re.split(r"[^A-Z0-9&Ñ]+", raw) if w and len(w) >= 2]
    stop = {"SPEI", "TRASPASO", "ABONO", "CARGO", "PAGO", "DEPOSITO", "RETIRO", "REFERENCIA", "REF", "CVE"}
    clean = [w for w in words if w not in stop and not re.match(r"^\d{5,}$", w)]
    return " ".join(clean[:10]) if clean else (raw[:80] + ("…" if len(raw) > 80 else ""))

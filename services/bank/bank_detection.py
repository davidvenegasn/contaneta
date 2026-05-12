"""
Detección de banco a partir del texto extraído del PDF.
Permite extender con nuevos perfiles (Banorte, BBVA, etc.).
Incluye extracción del titular del estado de cuenta para detectar transferencias propias.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional


def _normalize_for_name_match(s: str) -> str:
    """Quita acentos, mayúsculas, espacios múltiples."""
    if not s:
        return ""
    t = unicodedata.normalize("NFKD", (s or "").strip().upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_account_holder_from_pdf_text(pages_text: list[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Intenta extraer nombre del titular (y opcionalmente RFC) del estado de cuenta.
    Busca en las primeras páginas patrones típicos Banorte/otros.
    Returns (account_holder_name, account_holder_rfc).
    """
    if not pages_text:
        return None, None
    combined = " ".join((p or "") for p in pages_text[:3])
    if not combined.strip():
        return None, None
    norm = _normalize_for_name_match(combined)
    name: Optional[str] = None
    rfc: Optional[str] = None

    # RFC en encabezado (ej. "RFC: XIA190128J61")
    rfc_m = re.search(r"\bRFC\s*[:\-]?\s*([A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})\b", norm)
    if rfc_m:
        rfc = rfc_m.group(1).strip()

    # Titular: NOMBRE o Titular - NOMBRE (hasta fin de línea o siguiente etiqueta)
    for pattern in [
        r"(?:TITULAR|NOMBRE\s+DEL\s+TITULAR)\s*[:\-]?\s*([A-Z\s]{4,80}?)(?:\s+RFC|\s+CLABE|\s+ESTADO|\s*$|\n)",
        r"TITULAR\s+([A-Z\s]{4,80}?)(?:\s+RFC|\s+CLABE|\s+ESTADO|\s*$|\n)",
        r"(?:CUENTA\s+)?A\s+NOMBRE\s+DE\s*[:\-]?\s*([A-Z\s]{4,80}?)(?:\s+RFC|\s+CLABE|\s*$|\n)",
        r"CUENTA\s+ENLACE\s+PERSONAL\s+([A-Z\s]{4,60}?)(?:\s+NO\.|\s+No\.|\s+\d|\s*$|\n)",
        r"ESTADO\s+DE\s+CUENTA\s+([A-Z\s]{4,60}?)(?:\s+NO\.|\s+\d|\s*$|\n)",
    ]:
        m = re.search(pattern, norm)
        if m:
            raw_name = " ".join(m.group(1).split()).strip()
            if len(raw_name) >= 4 and not re.match(r"^\d+$", raw_name):
                name = raw_name[:80]
                break
    if not name:
        norm_ascii = _normalize_for_name_match(combined)
        m = re.search(r"BANORTE\s+([A-Z\s]{4,50}?)(?:\s+DETALLE|\s+ESTADO|\s+No\.|\s*\d)", norm_ascii)
        if m:
            raw_name = " ".join(m.group(1).split()).strip()
            if len(raw_name) >= 4:
                name = raw_name[:80]
    return name, rfc


def detect_bank_from_text(text: str) -> dict[str, Any]:
    """
    Detecta el banco a partir del texto plano (una página o todo el PDF).
    Usa normalización Unicode para que "BANORTE" se encuentre aunque el PDF traiga caracteres raros.
    Returns: {"bank_name": str, "profile": str, "confidence": int 0-100}
    """
    if not text or not isinstance(text, str):
        return {"bank_name": "DESCONOCIDO", "profile": "generic_v1", "confidence": 0}
    # Normalizar: quitar acentos y dejar mayúsculas para buscar "BANORTE", "BBVA", etc.
    t = unicodedata.normalize("NFKD", text.strip().upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    # Buscar en los primeros caracteres (donde suele estar el nombre del banco)
    head = (t[:2000] if len(t) > 2000 else t)
    if "BANORTE" in head or "CUENTA ENLACE PERSONAL" in head:
        return {"bank_name": "BANORTE", "profile": "banorte_v1", "confidence": 95}
    if "BBVA" in head and ("ESTADO DE CUENTA" in head or "CUENTA" in head):
        return {"bank_name": "BBVA", "profile": "not_implemented", "confidence": 70}
    if "SANTANDER" in head and ("ESTADO DE CUENTA" in head or "MOVIMIENTOS" in head):
        return {"bank_name": "SANTANDER", "profile": "not_implemented", "confidence": 70}
    if "BANAMEX" in head or "CITIBANAMEX" in head:
        return {"bank_name": "CITIBANAMEX", "profile": "not_implemented", "confidence": 70}
    if "HSBC" in head and ("ESTADO DE CUENTA" in head or "MOVIMIENTOS" in head or "ACCOUNT" in head):
        return {"bank_name": "HSBC", "profile": "not_implemented", "confidence": 70}
    if "SCOTIABANK" in head:
        return {"bank_name": "SCOTIABANK", "profile": "not_implemented", "confidence": 70}
    if "BANBAJIO" in head or "BAJIO" in head:
        return {"bank_name": "BANBAJIO", "profile": "not_implemented", "confidence": 65}
    if "BANREGIO" in head:
        return {"bank_name": "BANREGIO", "profile": "not_implemented", "confidence": 70}
    if "BANCO AZTECA" in head or "AZTECA" in head:
        return {"bank_name": "AZTECA", "profile": "not_implemented", "confidence": 60}
    if "INBURSA" in head:
        return {"bank_name": "INBURSA", "profile": "not_implemented", "confidence": 70}
    if "MIFEL" in head:
        return {"bank_name": "MIFEL", "profile": "not_implemented", "confidence": 65}
    # Repetir búsqueda en todo el texto por si el encabezado está más abajo
    if "BANORTE" in t or "CUENTA ENLACE PERSONAL" in t:
        return {"bank_name": "BANORTE", "profile": "banorte_v1", "confidence": 90}
    if "BBVA" in t:
        return {"bank_name": "BBVA", "profile": "not_implemented", "confidence": 60}
    if "SANTANDER" in t:
        return {"bank_name": "SANTANDER", "profile": "not_implemented", "confidence": 60}
    if "BANAMEX" in t or "CITIBANAMEX" in t:
        return {"bank_name": "CITIBANAMEX", "profile": "not_implemented", "confidence": 60}
    if "HSBC" in t:
        return {"bank_name": "HSBC", "profile": "not_implemented", "confidence": 55}
    return {"bank_name": "DESCONOCIDO", "profile": "generic_v1", "confidence": 0}


def detect_bank_from_pdf_text_pages(pages_text: list[str]) -> dict[str, Any]:
    """
    Detecta banco concatenando el texto de las primeras páginas (máx. 3).
    """
    if not pages_text:
        return {"bank_name": "DESCONOCIDO", "profile": "generic_v1", "confidence": 0}
    combined = " ".join((p or "") for p in pages_text[:3])
    return detect_bank_from_text(combined)

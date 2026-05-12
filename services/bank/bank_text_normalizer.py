"""
Normalización de texto extraído de PDF (estados de cuenta).
Limpieza y correcciones OCR comunes; preserva RFC, CVE, REF, CLABE.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_raw_text(text: str) -> str:
    """
    Colapsa espacios, quita saltos innecesarios, corrige OCR comunes.
    Conserva información importante (RFC, CVE, REF, CLABE).
    """
    if not text or not isinstance(text, str):
        return ""
    t = text.strip()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*\n\s*", " ", t)
    t = t.strip()
    t = re.sub(r"\s+", " ", t)
    t = t.upper()
    t = re.sub(r"INFORMACI N\b", "INFORMACION", t)
    t = re.sub(r"\bn CVE\b", " CVE", t)
    t = re.sub(r"RASTREO\s+", "RASTREO ", t)
    return t

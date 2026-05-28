"""Text parsing, classification, and CFDI matching helpers for bank statement processing."""
import re
import unicodedata
from datetime import date, datetime
from typing import Iterable, Optional

from services.pdf_to_excel._constants import (
    _BANK_KEYWORDS,
    _DATE_PATTERNS,
    _KNOWN_COUNTERPARTIES,
    _MONTHS,
    _STOPWORDS_CP,
)


def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch))


def _norm_text(s: str) -> str:
    t = _strip_accents(str(s or ""))
    t = re.sub(r"\s+", " ", t).strip().upper()
    return t


def _detect_bank_name(all_text_norm: str) -> str:
    t = all_text_norm or ""
    for name, keys in _BANK_KEYWORDS:
        if any(k in t for k in keys):
            return name
    return "DESCONOCIDO"


def _detect_account_last4(all_text_norm: str) -> str:
    t = all_text_norm or ""
    m = re.search(r"(?:\*{2,}|X{2,})\s*(\d{4})\b", t)
    if m:
        return m.group(1)
    m = re.search(r"(?:TERMINACION|TERMINACIÓN|ULTIMOS|ÚLTIMOS|ULT|FINAL)\s*(\d{4})\b", t)
    if m:
        return m.group(1)
    m = re.search(r"\bCUENTA\s*(\d{4})\b", t)
    if m:
        return m.group(1)
    return ""


def _detect_period(all_text_norm: str) -> tuple[str, str]:
    """
    Intenta detectar rango de periodo en el PDF (encabezado del estado de cuenta).
    Devuelve (period_start, period_end) como YYYY-MM-DD o ("","") si no detecta.
    Prioriza el texto explícito "del ... al ..." / "periodo ..." sobre fechas de movimientos.
    """
    t = all_text_norm or ""
    date_part = r"(\d{2}[\/\-]\d{2}[\/\-]\d{2,4})"
    # 1) "DEL 01/01/2026 AL 31/01/2026" o "PERIODO DEL 01/01/2026 AL 31/01/2026"
    m = re.search(
        r"\b(?:PERIODO\s+)?DEL\s+" + date_part + r"\s+(?:AL|A)\s+" + date_part + r"\b",
        t,
    )
    if m:
        d1, d2 = _detect_date(m.group(1)), _detect_date(m.group(2))
        if d1 and d2:
            return (d1, d2)
    # 2) "PERIODO 01/01/2026 AL 31/01/2026" o "01/01/2026 AL 31/01/2026" (sin DEL)
    m = re.search(
        r"\b(?:PERIODO\s*:?\s*)?(\d{2}[\/\-]\d{2}[\/\-]\d{2,4})\s+(?:AL|A)\s+(\d{2}[\/\-]\d{2}[\/\-]\d{2,4})\b",
        t,
    )
    if m:
        d1, d2 = _detect_date(m.group(1)), _detect_date(m.group(2))
        if d1 and d2:
            return (d1, d2)
    # 3) "DE 01/01/2026 A 31/01/2026"
    m = re.search(r"\bDE\s+" + date_part + r"\s+A\s+" + date_part + r"\b", t)
    if m:
        d1, d2 = _detect_date(m.group(1)), _detect_date(m.group(2))
        if d1 and d2:
            return (d1, d2)
    return ("", "")


def detect_statement_period_from_text(raw_text: str) -> tuple[str, str]:
    """
    Detecta periodo del estado de cuenta desde texto crudo (ej. páginas del PDF concatenadas).
    Útil para el pipeline de preview sin depender del Excel.
    Returns (period_start, period_end) en YYYY-MM-DD o ("", "").
    """
    if not (raw_text or "").strip():
        return ("", "")
    all_text = " ".join((raw_text or "").split())
    all_text_norm = _norm_text(all_text)
    return _detect_period(all_text_norm)


def _detect_date(line: str) -> Optional[str]:
    s = (line or "").strip()
    for pat in _DATE_PATTERNS:
        m = pat.match(s)
        if m:
            d = m.groupdict()
            try:
                if "mon" in d and d.get("mon"):
                    mon_raw = _strip_accents(d["mon"]).upper().strip().strip(".")
                    mon_raw = mon_raw[:3]
                    m_num = _MONTHS.get(mon_raw)
                    if not m_num:
                        return None
                    y = int(d["y"])
                    if y < 100:
                        y = 2000 + y
                    dt = date(int(y), int(m_num), int(d["d"]))
                    return dt.isoformat()
                y = int(d["y"])
                if y < 100:
                    y = 2000 + y
                dt = date(int(y), int(d["m"]), int(d["d"]))
                return dt.isoformat()
            except Exception:
                return None
    return None


def _parse_amount(token: str) -> Optional[float]:
    """
    Parse monto tipo $1,234.56 o (1,234.56).
    Retorna float (puede ser negativo si viene entre paréntesis o con signo).
    """
    if token is None:
        return None
    t = str(token).strip()
    if not t:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg = True
        t = t[1:-1].strip()
    t = t.replace("$", "").replace(" ", "")
    if t.startswith("-"):
        neg = True
        t = t[1:]
    # Normalizar separadores: 1,234.56 | 1.234,56 | 1234,56 | 1234.56
    if not re.match(r"^\d[\d\.,]*$", t):
        return None
    if "," in t and "." in t:
        # decimal = último separador
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t and "." not in t:
        # si termina con ,dd entonces es decimal
        if re.match(r"^\d{1,3}(?:\.\d{3})*,\d{1,2}$", t) or re.match(r"^\d+,(\d{1,2})$", t):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    else:
        # solo punto: dejarlo como decimal
        pass
    if not re.match(r"^\d+(\.\d{1,2})?$", t):
        return None
    try:
        n = float(t)
        return -n if neg else n
    except Exception:
        return None


def _split_columns(line: str) -> list[str]:
    # muchos estados separan columnas por 2+ espacios
    parts = re.split(r"\s{2,}", (line or "").strip())
    return [p.strip() for p in parts if p and p.strip()]


def _extract_amounts_from_end(s: str, max_amounts: int = 3) -> tuple[str, list[float]]:
    """
    Extrae hasta N montos al final del string y regresa (texto_sin_montos, montos_en_orden_original).
    """
    txt = (s or "").rstrip()
    found_rev: list[float] = []
    for _ in range(max_amounts):
        m = re.search(r"(?:\s+|^)(\(?-?\$?\d[\d\.,]*\)?)\s*$", txt)
        if not m:
            break
        tok = m.group(1)
        a = _parse_amount(tok)
        if a is None:
            break
        found_rev.append(a)
        txt = txt[: m.start(1)].rstrip()
    found = list(reversed(found_rev))
    return txt.strip(), found


def _extract_referencia(desc_norm: str) -> str:
    d = desc_norm or ""
    m = re.search(r"\b(?:REF|REFERENCIA|FOLIO|AUT|AUTORIZACION|AUTORIZACIÓN|ID)\s*[:\-]?\s*([A-Z0-9]{4,})\b", d)
    return m.group(1) if m else ""


def _metodo_pago_hint(desc_norm: str) -> str:
    d = desc_norm or ""
    if "SPEI" in d:
        return "SPEI"
    if "TPV" in d or "POS" in d:
        return "TPV"
    if "TARJ" in d or "TARJETA" in d or "DEBITO" in d or "DÉBITO" in d or "CREDITO" in d or "CRÉDITO" in d:
        return "TARJETA"
    if "COMISION" in d or "COMISIONES" in d:
        return "COMISION"
    if "EFECTIVO" in d or "RETIRO" in d or "CAJERO" in d:
        return "EFECTIVO"
    if "TRANSF" in d or "TRANSFER" in d or "TRASP" in d:
        return "TRANSFER"
    return ""


def _contraparte_hint(desc_norm: str) -> str:
    d = desc_norm or ""
    for k in _KNOWN_COUNTERPARTIES:
        if k in d:
            return k
    # fallback: primeras 1-3 "palabras útiles"
    words = [w for w in re.split(r"[^A-Z0-9&\-]+", d) if w]
    useful: list[str] = []
    for w in words:
        if len(w) < 3:
            continue
        if w in _STOPWORDS_CP:
            continue
        useful.append(w)
        if len(useful) >= 3:
            break
    return " ".join(useful[:2]) if useful else ""


def _clasificar(desc_norm: str) -> tuple[str, str, int, int, int]:
    """
    Regresa (categoria, subcategoria, es_comision_bancaria, es_impuesto_bancario, posible_facturable).
    posible_facturable se calcula con heurística simple, principalmente para gastos.
    """
    d = desc_norm or ""
    cat = "OTROS"
    sub = ""

    def has_any(keys: Iterable[str]) -> bool:
        return any(k in d for k in keys)

    if has_any(["COMISION", "MANEJO CTA", "ANUALIDAD", "MEMBERSHIP"]):
        cat = "COMISIONES BANCARIAS"
    elif has_any(["SAT", "HACIENDA", "IMPUESTO", "ISR", "IVA"]):
        cat = "IMPUESTOS"
    elif has_any(["CFE", "AGUA", "GAS", "TELMEX", "IZZI", "TOTALPLAY", "TELCEL", "AT&T", "MOVISTAR"]):
        cat = "SERVICIOS"
    elif has_any(["UBER", "DIDI", "GASOLINA", "PEMEX", "OXXO GAS", "ESTACION"]):
        cat = "TRANSPORTE"
    elif has_any(["OXXO", "7-ELEVEN", "SORIANA", "WALMART", "COSTCO", "REST", "RESTAUR", "CAFE", "CAFÉ"]):
        cat = "ALIMENTOS"
    elif has_any(["GOOGLE", "APPLE", "MICROSOFT", "AWS", "OPENAI", "ADOBE", "NETFLIX", "SPOTIFY"]):
        cat = "SOFTWARE/SUSCRIPCIONES"
    elif has_any(["HONORARIOS", "CONSULTORIA", "CONSULTOR", "FACTURA", "RFC", "SERVICIO PROFESIONAL", "SERVICIOS PROFESIONALES"]):
        cat = "HONORARIOS/PROVEEDORES"
    elif has_any(["RETIRO", "CAJERO"]):
        cat = "RETIRO/EFECTIVO"
        sub = "CAJERO"
    elif has_any(["SPEI", "TRANSF", "TRANSFER", "TRASPASO", "TRASP"]):
        cat = "TRANSFERENCIAS"
        if "SPEI" in d:
            sub = "SPEI"
        elif "TRASP" in d or "TRASPASO" in d:
            sub = "TRASPASO"
        else:
            sub = "TRANSFER"

    es_com = 1 if cat == "COMISIONES BANCARIAS" else 0
    es_imp = 1 if cat == "IMPUESTOS" else 0

    # posible_facturable: heurística rápida (sin depender de proveedores)
    fact = 0
    if cat not in ("COMISIONES BANCARIAS", "IMPUESTOS", "RETIRO/EFECTIVO"):
        if any(x in d for x in ["RFC", "FACTURA", "S A DE C V", "S.A. DE C.V", "SAPI", "SA CV"]):
            fact = 1
        elif any(x in d for x in ["WALMART", "COSTCO", "SORIANA", "CFE", "TELCEL", "TELMEX", "IZZI", "TOTALPLAY", "GOOGLE", "APPLE", "MICROSOFT", "AWS", "ADOBE"]):
            fact = 1
    return cat, sub, es_com, es_imp, fact


def _to_date(s: str | None) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _amount_in_tolerance(mov: float, cfdi: float) -> bool:
    if mov <= 0 or cfdi <= 0:
        return False
    diff = abs(mov - cfdi)
    tol = max(2.0, mov * 0.005)
    return diff <= tol


def _score_cfdi(mov_date: date, mov_amount: float, contraparte_hint: str, cfdi: dict) -> int:
    score = 0
    try:
        cfdi_total = float(cfdi.get("total") or 0)
    except Exception:
        cfdi_total = 0.0
    if _amount_in_tolerance(mov_amount, cfdi_total):
        score += 60
    cfdi_date = _to_date(cfdi.get("fecha_emision"))
    if cfdi_date:
        d = abs((cfdi_date - mov_date).days)
        if d <= 2:
            score += 20
    cp = _norm_text(contraparte_hint or "")
    if cp:
        hay = _norm_text(f"{cfdi.get('rfc_emisor') or ''} {cfdi.get('nombre_emisor') or ''}")
        # match por substring; si cp es multi-palabra, basta que una palabra útil aparezca
        if cp in hay:
            score += 20
        else:
            tokens = [t for t in cp.split() if len(t) >= 4 and t not in _STOPWORDS_CP]
            if any(t in hay for t in tokens):
                score += 20
    return score


def _best_cfdi_for_movement(mov_date: date, mov_amount: float, contraparte_hint: str, cfdis: list[dict]) -> tuple[Optional[dict], int]:
    best = None
    best_score = -1
    for c in cfdis:
        c_date = _to_date(c.get("fecha_emision"))
        if not c_date:
            continue
        if abs((c_date - mov_date).days) > 7:
            continue
        s = _score_cfdi(mov_date, mov_amount, contraparte_hint, c)
        if s > best_score:
            best = c
            best_score = s
    return best, (best_score if best_score >= 0 else 0)

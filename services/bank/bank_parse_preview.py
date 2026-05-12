"""
Parser Banorte: vista previa de movimientos sin guardar en DB.
Extrae movimientos, genera short_description, clasifica con reglas IFs.
Solo Banorte; no matching CFDI, no DB, no jobs en background.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Regex fecha inicio transacción Banorte: 01-ENE-26
_DATE_START_RE = re.compile(r"^\d{2}-[A-ZÑ]{3}-\d{2}")
# Solo montos con 2 decimales (evita 31, 33, horas, referencias)
REGEX_MONEY = r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b"
_MONEY_RE = re.compile(REGEX_MONEY)
_RFC_RE = re.compile(r"\b(?P<rfc>[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})\b")
_CLABE_RE = re.compile(r"\b\d{18}\b")


@dataclass
class Extracted:
    rfc: Optional[str] = None
    reference: Optional[str] = None
    tracking: Optional[str] = None
    counterparty: Optional[str] = None
    clabe: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rfc": self.rfc,
            "reference": self.reference,
            "tracking": self.tracking,
            "counterparty": self.counterparty,
            "clabe": self.clabe,
        }


@dataclass
class MovementPreview:
    idx: int
    date: str  # YYYY-MM-DD
    description_raw: str
    description_short: str
    deposit: float
    withdraw: float
    balance: Optional[float]
    direction: str  # "IN" | "OUT" | "INFO"
    method: str  # SPEI | TARJETA | DOMICILIACION | EFECTIVO | NOMINA | OTRO
    category: str
    bucket: str  # NEGOCIO | PERSONAL | FINANCIERO | DESCONOCIDO
    deductible_hint: str  # SI | NO | DEPENDE
    needs_review: bool
    confidence: int  # 0-100
    extracted: Extracted = field(default_factory=Extracted)
    rule_hits: List[str] = field(default_factory=list)   # ej: ["METHOD:TARJETA","CAT:FINANCIERO_PAGO_TARJETA"]
    warnings: List[str] = field(default_factory=list)  # ej: ["HEADER_NOISE_REMOVED","AMBIGUOUS_BUCKET"]
    confidence_breakdown: List[str] = field(default_factory=list)  # ej: ["base:60","balance:+15"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "idx": self.idx,
            "date": self.date,
            "description_raw": self.description_raw,
            "description_short": self.description_short,
            "deposit": self.deposit,
            "withdraw": self.withdraw,
            "balance": self.balance,
            "direction": self.direction,
            "method": self.method,
            "category": self.category,
            "bucket": self.bucket,
            "deductible_hint": self.deductible_hint,
            "needs_review": self.needs_review,
            "confidence": self.confidence,
            "extracted": self.extracted.to_dict(),
            "rule_hits": list(self.rule_hits),
            "warnings": list(self.warnings),
            "confidence_breakdown": list(self.confidence_breakdown),
        }


def _norm(s: str) -> str:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t).strip().upper()
    return t


def _clean_noise(desc: str) -> tuple[str, bool]:
    """Cortar ruido: headers, x/4. Devuelve (texto_limpio, hubo_cambios)."""
    if not desc:
        return desc, False
    t = desc
    changed = False
    if "ESTADO DE CUENTA" in t and "/" in t:
        idx = t.find("ESTADO DE CUENTA")
        end = t.find("/", idx)
        if end > idx:
            t = (t[:idx] + " " + t[end + 1:]).strip()
            changed = True
    t2 = re.sub(r"\s*\d\s*/\s*\d\s*", " ", t)
    if t2 != t:
        changed = True
    t = " ".join(t2.split())
    return t, changed


# Fecha al inicio tipo Banorte: 07-ENE-26 o 07 ENE 26 (redundante con columna Fecha)
_LEADING_DATE_RE = re.compile(
    r"^\s*\d{1,2}[\s\-]*(?:ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|SET|OCT|NOV|DIC)[\s\-]*\d{2}\s*",
    re.IGNORECASE,
)


def _strip_leading_date(desc: str) -> str:
    """Quita la fecha al inicio del concepto (DD-MMM-YY o DD MMM YY) para no duplicarla en la columna Concepto."""
    if not desc:
        return desc
    return _LEADING_DATE_RE.sub("", desc).strip()


def _parse_money_token(s: str) -> Optional[float]:
    t = str(s).strip().replace("$", "").replace(" ", "").replace(",", "")
    if not t or not re.match(r"^\d+\.\d{2}$", t):
        return None
    try:
        return float(t)
    except Exception:
        return None


def _extract_money_values(norm_text: str) -> tuple[list[float], str]:
    r"""Extrae montos con regex \d{1,3}(?:,\d{3})*\.\d{2}. Devuelve (valores, texto_sin_montos)."""
    values: list[float] = []
    for m in _MONEY_RE.finditer(norm_text):
        raw = m.group(0)
        v = _parse_money_token(raw)
        if v is not None:
            values.append(v)
    return values, norm_text


def _parse_banorte_date_start(s_norm: str) -> Optional[tuple[str, str]]:
    """(YYYY-MM-DD, resto)."""
    import unicodedata
    _MONTHS = {
        "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AGO": 8, "SEP": 9, "SET": 9, "OCT": 10, "NOV": 11, "DIC": 12,
    }
    m = re.match(r"^(?P<d>\d{2})-(?P<mon>[A-ZÑ]{3})-(?P<y>\d{2})", s_norm)
    if not m:
        return None
    d = int(m.group("d"))
    mon = m.group("mon")
    y2 = int(m.group("y"))
    mm = _MONTHS.get(mon)
    if mm is None:
        return None
    yyyy = 2000 + y2
    try:
        from datetime import date
        dt = date(yyyy, mm, d).isoformat()
    except Exception:
        return None
    rest = s_norm[m.end():].strip()
    return dt, rest


def _extract_fields(desc_norm: str) -> Extracted:
    rfc = None
    m = re.search(r"\bRFC\s*[:=\-]?\s*([A-Z&Ñ0-9]{12,14})\b", desc_norm)
    if m:
        rfc = m.group(1).strip()
    if not rfc:
        m2 = _RFC_RE.search(desc_norm)
        if m2:
            rfc = m2.group("rfc")
    if rfc and "ND" in rfc.upper():
        rfc = None
    reference = None
    m = re.search(r"\b(?:REFERENCIA|REF)\s*[:=\-]?\s*([A-Z0-9]{4,})\b", desc_norm)
    if m:
        reference = m.group(1).strip()
    tracking = None
    m = re.search(r"\bCVE\s+RAST(?:REO)?\s*[:=\-]?\s*([A-Z0-9]{8,40})\b", desc_norm)
    if m:
        tracking = m.group(1).strip()
    counterparty = None
    m = re.search(r"\bBENEF[:\s]+([^,\(]{4,60}?)(?:\s*,\s*|\s*\(|$)", desc_norm)
    if m:
        counterparty = " ".join(m.group(1).split())[:50].strip()
    if not counterparty:
        m = re.search(r"\bDEL CLIENTE\s+([A-Z0-9&Ñ ]{4,60})\b", desc_norm)
        if m:
            counterparty = " ".join(m.group(1).split())[:50].strip()
    if not counterparty:
        if "OXXO" in desc_norm:
            counterparty = "OXXO"
        elif "AMERICAN EXPRES" in desc_norm or "AMERICAN EXPRESS" in desc_norm:
            counterparty = "AMEX"
        elif "PROFUTURO" in desc_norm:
            counterparty = "PROFUTURO"
    clabe = None
    m = _CLABE_RE.search(desc_norm)
    if m:
        clabe = m.group(0)
    return Extracted(rfc=rfc, reference=reference, tracking=tracking, counterparty=counterparty, clabe=clabe)


def summarize(description_raw: str, method: str, counterparty: Optional[str]) -> str:
    """Genera short_description humana."""
    d = _norm(description_raw)
    cp = (counterparty or "").strip()
    if cp:
        if method == "SPEI":
            if "RECIBIDO" in d or "DEPOSITO" in d or "ABONO" in d:
                return f"SPEI de {cp}"
            return f"SPEI a {cp}"
        return cp
    if "RETIRO DE EFECTIVO" in d or "CAJERO" in d:
        return "Retiro en cajero"
    if "DEPOSITO DE NOMINA" in d or "NOMINA" in d:
        return "Nómina"
    if "PAGO REFERENCIADO" in d or "IMPUESTO" in d:
        return "Pago de impuesto"
    if "SALDO ANTERIOR" in d:
        return "Saldo anterior"
    words = [w for w in re.split(r"[^A-Z0-9&Ñ]+", d) if w and len(w) >= 2]
    stop = {"SPEI", "TRASPASO", "ABONO", "CARGO", "PAGO", "DEPOSITO", "RETIRO", "REFERENCIA", "REF", "CVE", "RFC"}
    clean = [w for w in words if w not in stop and not re.match(r"^\d{5,}$", w)]
    return " ".join(clean[:10]) if clean else (d[:80] + ("…" if len(d) > 80 else ""))


def _classify(m: MovementPreview, desc_norm: str, preset: Optional[dict[str, Any]] = None) -> None:
    """Clasifica en método, categoría, bucket, deductible_hint, needs_review, confidence. Registra rule_hits y confidence_breakdown."""
    from services.bank.bank_classifier_presets import (
        KEYWORDS_IMPUESTO,
        KEYWORDS_TARJETA,
        MERCHANT_MAP,
        PRESET_CONSERVATIVE,
        get_preset,
    )
    preset = preset or get_preset(PRESET_CONSERVATIVE)
    default_bucket = preset.get("default_bucket_unknown") or "DESCONOCIDO"
    default_needs_review_spei = preset.get("default_needs_review_spei", True)
    penalty_otros = preset.get("confidence_penalty_otros", -20)

    # CAPA 1: Método
    if "SPEI" in desc_norm:
        m.method = "SPEI"
        m.rule_hits.append("METHOD:SPEI")
    elif any(k in desc_norm for k in KEYWORDS_TARJETA):
        m.method = "TARJETA"
        m.rule_hits.append("METHOD:TARJETA")
    elif "DOMICILIACION" in desc_norm or "DOMICILIACIÓN" in desc_norm:
        m.method = "DOMICILIACION"
        m.rule_hits.append("METHOD:DOMICILIACION")
    elif "RETIRO DE EFECTIVO" in desc_norm or "CAJERO" in desc_norm:
        m.method = "EFECTIVO"
        m.rule_hits.append("METHOD:EFECTIVO")
    elif "NOMINA" in desc_norm or "NÓMINA" in desc_norm:
        m.method = "NOMINA"
        m.rule_hits.append("METHOD:NOMINA")
    else:
        m.method = "OTRO"
        m.rule_hits.append("METHOD:OTRO")

    # CAPA 2: Categoría dura
    if m.method == "TARJETA" and (
        "PAGO CONCENTRACION" in desc_norm or "TARJETA DE CRED" in desc_norm or "AMERICAN EXPRES" in desc_norm
    ):
        m.category = "FINANCIERO_PAGO_TARJETA"
        m.bucket = "FINANCIERO"
        m.deductible_hint = "NO"
        m.needs_review = False
        m.rule_hits.append("CAT:FINANCIERO_PAGO_TARJETA")
        m.rule_hits.append("BUCKET:FINANCIERO")
    elif any(k in desc_norm for k in KEYWORDS_IMPUESTO):
        m.category = "IMPUESTOS"
        m.bucket = default_bucket
        m.deductible_hint = "DEPENDE"
        m.needs_review = True
        m.rule_hits.append("CAT:IMPUESTOS")
        m.warnings.append("AMBIGUOUS_BUCKET")
    elif "OXXO" in desc_norm:
        m.category = "ALIMENTOS"
        m.bucket = "PERSONAL"
        m.deductible_hint = "NO"
        m.needs_review = True
        m.rule_hits.append("MERCHANT:OXXO->ALIMENTOS")
    elif "PROFUTURO" in desc_norm or "AFORE" in desc_norm:
        m.category = "OTROS"
        m.bucket = "PERSONAL"
        m.deductible_hint = "NO"
        m.needs_review = False
        m.rule_hits.append("CAT:OTROS")
        m.rule_hits.append("BUCKET:PERSONAL")
    elif m.method == "EFECTIVO":
        m.category = "EFECTIVO"
        m.bucket = "PERSONAL"
        m.deductible_hint = "NO"
        m.needs_review = True
        m.rule_hits.append("CAT:EFECTIVO")
    elif m.method == "NOMINA":
        m.category = "NOMINA"
        m.bucket = "PERSONAL"
        m.deductible_hint = "NO"
        m.needs_review = False
        m.rule_hits.append("CAT:NOMINA")
    elif m.method == "SPEI" and m.direction == "OUT":
        m.category = "TRANSFERENCIA"
        m.bucket = default_bucket
        m.deductible_hint = "DEPENDE"
        m.needs_review = default_needs_review_spei
        m.rule_hits.append("CAT:TRANSFERENCIA")
        m.rule_hits.append("DIR:OUT")
    elif m.method == "SPEI" and m.direction == "IN":
        m.category = "TRANSFERENCIA"
        m.bucket = default_bucket
        m.deductible_hint = "DEPENDE"
        m.needs_review = default_needs_review_spei
        m.rule_hits.append("CAT:TRANSFERENCIA")
        m.rule_hits.append("DIR:IN")
    else:
        m.category = "OTROS"
        m.bucket = default_bucket
        m.deductible_hint = "DEPENDE"
        m.needs_review = True
        m.rule_hits.append("CAT:OTROS")
        m.rule_hits.append("BUCKET:" + default_bucket)
        m.warnings.append("AMBIGUOUS_BUCKET")

    # CAPA 3: Ajuste por RFC
    rfc_val = m.extracted.rfc and "ND" not in (m.extracted.rfc or "").upper()
    if rfc_val:
        m.confidence = min(100, m.confidence + 10)
        if m.direction == "OUT":
            m.deductible_hint = "DEPENDE"
        m.rule_hits.append("RFC:DETECTED:YES")
    else:
        m.rule_hits.append("RFC:DETECTED:NO")

    # CAPA 4: confidence scoring
    m.confidence_breakdown.append("base:60")
    base = 60
    if m.balance is not None:
        base += 15
        m.confidence_breakdown.append("balance:+15")
    if m.method != "OTRO":
        base += 10
        m.confidence_breakdown.append("method:+10")
    if m.extracted.counterparty:
        base += 10
        m.confidence_breakdown.append("counterparty:+10")
    if rfc_val:
        base += 10
        m.confidence_breakdown.append("rfc:+10")
    if m.category == "OTROS" and m.needs_review:
        base += penalty_otros
        m.confidence_breakdown.append("otros_review:" + str(penalty_otros))
    m.confidence = max(0, min(100, base))


def _build_movement(
    idx: int,
    date_str: str,
    description_raw: str,
    deposit: float,
    withdraw: float,
    balance: Optional[float],
    direction: str,
    is_saldo_anterior: bool,
    preset: Optional[dict[str, Any]] = None,
) -> MovementPreview:
    desc_clean, noise_removed = _clean_noise(description_raw)
    desc_clean = _strip_leading_date(desc_clean)
    desc_norm = _norm(desc_clean)
    extracted = _extract_fields(desc_norm)
    method = "OTRO"
    if "SPEI" in desc_norm:
        method = "SPEI"
    elif "TARJETA DE CRED" in desc_norm or "PAGO CONCENTRACION" in desc_norm:
        method = "TARJETA"
    elif "DOMICILIACION" in desc_norm:
        method = "DOMICILIACION"
    elif "RETIRO DE EFECTIVO" in desc_norm or "CAJERO" in desc_norm:
        method = "EFECTIVO"
    elif "NOMINA" in desc_norm:
        method = "NOMINA"
    short = summarize(desc_clean, method, extracted.counterparty)
    if is_saldo_anterior:
        m = MovementPreview(
            idx=idx,
            date=date_str,
            description_raw=desc_clean,
            description_short=short,
            deposit=0.0,
            withdraw=0.0,
            balance=balance,
            direction="INFO",
            method="OTRO",
            category="OTROS",
            bucket="DESCONOCIDO",
            deductible_hint="NO",
            needs_review=False,
            confidence=60,
            extracted=extracted,
        )
        m.rule_hits.append("SALDO_ANTERIOR")
        m.confidence_breakdown.append("base:60")
        if noise_removed:
            m.warnings.append("HEADER_NOISE_REMOVED")
    else:
        m = MovementPreview(
            idx=idx,
            date=date_str,
            description_raw=desc_clean,
            description_short=short,
            deposit=deposit,
            withdraw=withdraw,
            balance=balance,
            direction=direction,
            method="OTRO",
            category="OTROS",
            bucket="DESCONOCIDO",
            deductible_hint="DEPENDE",
            needs_review=True,
            confidence=60,
            extracted=extracted,
        )
        if noise_removed:
            m.warnings.append("HEADER_NOISE_REMOVED")
        _classify(m, desc_norm, preset=preset)
    return m


def parse_bank_pdf_to_movements_preview(pdf_path: str, preset: str = "conservative") -> dict[str, Any]:
    """
    Parsea PDF Banorte y devuelve movements + summary + raw_debug (si DEV).
    preset: "conservative" | "aggressive". No guarda en DB.
    """
    from services.bank.bank_classifier_presets import get_preset
    preset_dict = get_preset(preset)
    try:
        import pdfplumber
    except ModuleNotFoundError:
        return {
            "movements": [],
            "summary": {"total_deposit": 0, "total_withdraw": 0, "count_in": 0, "count_out": 0, "count_info": 0, "error": "pdfplumber_missing"},
            "raw_debug": None,
        }
    if not os.path.isfile(pdf_path):
        return {
            "movements": [],
            "summary": {"total_deposit": 0, "total_withdraw": 0, "count_in": 0, "count_out": 0, "count_info": 0, "error": "file_not_found"},
            "raw_debug": None,
        }
    from services.bank.bank_statement_parser import (
        _parse_banorte_date_from_start,
        build_transactions,
        extract_money_candidates,
        locate_sections,
        norm_text,
    )
    raw_rows: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for li, ln in enumerate((text or "").splitlines(), start=1):
                ln = (ln or "").strip()
                if ln:
                    raw_rows.append({"Page": page_idx, "Line": li, "Text": ln})
    # Detectar banco desde el texto del inicio del PDF (nombre del banco suele estar arriba)
    from services.bank.bank_detection import detect_bank_from_text
    first_page_text = " ".join((r.get("Text") or "") for r in raw_rows if r.get("Page") == 1).strip()
    if not first_page_text and raw_rows:
        first_page_text = " ".join((r.get("Text") or "") for r in raw_rows[:60]).strip()
    detection = detect_bank_from_text(first_page_text)
    detected_bank_name = (detection.get("bank_name") or "BANORTE").strip() or "BANORTE"
    sections = locate_sections(raw_rows)
    txs_grouped: list[list[dict[str, Any]]] = []
    for sec in sections:
        start = int(sec["start_idx"])
        end = int(sec["end_idx"])
        txs_grouped.extend(build_transactions(raw_rows[start : end + 1]))
    movements: list[MovementPreview] = []
    prev_saldo: Optional[float] = None
    for i, g in enumerate(txs_grouped):
        raw_lines = [str(r.get("Text") or "").strip() for r in g if (r.get("Text") or "").strip()]
        joined_raw = " ".join(raw_lines).strip()
        joined_norm = norm_text(joined_raw)
        is_saldo_anterior = "SALDO ANTERIOR" in joined_norm
        dt_and_rest = _parse_banorte_date_from_start(joined_norm)
        date_str = ""
        if dt_and_rest:
            date_str, _ = dt_and_rest
        candidates = extract_money_candidates(joined_norm)
        values = [c["value"] for c in candidates]
        balance = values[-1] if values else None
        rest_amounts = values[:-1] if len(values) > 1 else []
        deposit = 0.0
        withdraw = 0.0
        if is_saldo_anterior:
            pass
        elif len(rest_amounts) == 1:
            amt = rest_amounts[0]
            if "SPEI RECIBIDO" in joined_norm or "DEPOSITO" in joined_norm or "ABONO" in joined_norm or "NOMINA" in joined_norm or "TRASPASO RECIBIDO" in joined_norm:
                deposit = amt
            elif "CARGO" in joined_norm or "COMPRA" in joined_norm or "PAGO" in joined_norm or "RETIRO" in joined_norm or "DOMICILIACION" in joined_norm or "IMPUESTO" in joined_norm or "ORDEN DE PAGO SPEI" in joined_norm:
                withdraw = amt
            elif prev_saldo is not None and balance is not None:
                if abs(prev_saldo + amt - balance) < max(2.0, abs(balance) * 0.005):
                    deposit = amt
                elif abs(prev_saldo - amt - balance) < max(2.0, abs(balance) * 0.005):
                    withdraw = amt
                else:
                    withdraw = amt
            else:
                withdraw = amt
        elif len(rest_amounts) >= 2:
            a1, a2 = rest_amounts[0], rest_amounts[1]
            amt = a1 if a1 != 0 else a2
            if "SPEI RECIBIDO" in joined_norm or "DEPOSITO" in joined_norm or "ABONO" in joined_norm or "NOMINA" in joined_norm:
                deposit = amt
            elif "CARGO" in joined_norm or "COMPRA" in joined_norm or "PAGO" in joined_norm or "RETIRO" in joined_norm or "DOMICILIACION" in joined_norm or "IMPUESTO" in joined_norm or "ORDEN DE PAGO SPEI" in joined_norm:
                withdraw = amt
            elif prev_saldo is not None and balance is not None:
                if abs(prev_saldo + amt - balance) < max(2.0, abs(balance) * 0.005):
                    deposit = amt
                elif abs(prev_saldo - amt - balance) < max(2.0, abs(balance) * 0.005):
                    withdraw = amt
                else:
                    withdraw = amt
            else:
                withdraw = amt
        if deposit > 0 and withdraw == 0:
            direction = "IN"
        elif withdraw > 0 and deposit == 0:
            direction = "OUT"
        elif is_saldo_anterior:
            direction = "INFO"
        else:
            direction = "INFO"
        if balance is not None:
            prev_saldo = balance
        mov = _build_movement(
            idx=i + 1,
            date_str=date_str,
            description_raw=joined_raw,
            deposit=deposit,
            withdraw=withdraw,
            balance=balance,
            direction=direction,
            is_saldo_anterior=is_saldo_anterior,
            preset=preset_dict,
        )
        movements.append(mov)
    total_deposit = sum(m.deposit for m in movements)
    total_withdraw = sum(m.withdraw for m in movements)
    count_in = sum(1 for m in movements if m.direction == "IN")
    count_out = sum(1 for m in movements if m.direction == "OUT")
    count_info = sum(1 for m in movements if m.direction == "INFO")
    summary = {
        "total_deposit": round(total_deposit, 2),
        "total_withdraw": round(total_withdraw, 2),
        "count_in": count_in,
        "count_out": count_out,
        "count_info": count_info,
        "count_total": len(movements),
        "needs_review_count": sum(1 for m in movements if m.needs_review),
        "bank_name": detected_bank_name,
        "raw_rows_count": len(raw_rows),
        "sections_detected": len(sections),
        "txs_grouped_count": len(txs_grouped),
    }
    raw_debug = None
    try:
        from config import DEV_MODE
        if DEV_MODE:
            raw_debug = {
                "raw_rows_count": len(raw_rows),
                "sections": sections,
                "txs_grouped_count": len(txs_grouped),
            }
    except Exception:
        pass
    return {
        "movements": [m.to_dict() for m in movements],
        "summary": summary,
        "raw_debug": raw_debug,
    }


def reclassify_movements(movements: list[dict[str, Any]], preset: str = "conservative") -> list[dict[str, Any]]:
    """
    Re-clasifica una lista de movimientos (dicts) con el preset dado.
    Preserva concept, notes y demás campos editados; actualiza category, bucket,
    deductible_hint, needs_review, confidence, rule_hits, warnings, confidence_breakdown.
    """
    from services.bank.bank_classifier_presets import get_preset
    preset_dict = get_preset(preset)
    result: list[dict[str, Any]] = []
    for d in movements:
        ext = d.get("extracted") or {}
        if isinstance(ext, dict):
            extracted = Extracted(
                rfc=ext.get("rfc"),
                reference=ext.get("reference"),
                tracking=ext.get("tracking"),
                counterparty=ext.get("counterparty"),
                clabe=ext.get("clabe"),
            )
        else:
            extracted = Extracted()
        desc_raw = d.get("description_raw") or ""
        desc_norm = _norm(desc_raw)
        m = MovementPreview(
            idx=int(d.get("idx") or 0),
            date=d.get("date") or "",
            description_raw=desc_raw,
            description_short=d.get("description_short") or d.get("concept") or "",
            deposit=float(d.get("deposit") or 0),
            withdraw=float(d.get("withdraw") or 0),
            balance=float(d["balance"]) if d.get("balance") is not None else None,
            direction=d.get("direction") or "INFO",
            method="OTRO",
            category="OTROS",
            bucket="DESCONOCIDO",
            deductible_hint="DEPENDE",
            needs_review=True,
            confidence=60,
            extracted=extracted,
        )
        if "SALDO ANTERIOR" in desc_raw.upper():
            m.rule_hits.append("SALDO_ANTERIOR")
            m.confidence_breakdown.append("base:60")
        else:
            _classify(m, desc_norm, preset=preset_dict)
        out = m.to_dict()
        if d.get("concept") is not None:
            out["concept"] = d["concept"]
        if d.get("notes") is not None:
            out["notes"] = d.get("notes")
        result.append(out)
    return result

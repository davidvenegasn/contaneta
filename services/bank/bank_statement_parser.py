import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)


_DATE_START_RE = re.compile(r"^(?P<d>\d{2})-(?P<mon>[A-ZÑ]{3})-(?P<y>\d{2})")
_RFC_RE = re.compile(r"\b(?P<rfc>[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})\b")


_MONTHS = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "SET": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}


# Solo sección explícita Banorte (PESOS)
_SECTION_START_KEYS = [
    "DETALLE DE MOVIMIENTOS (PESOS)",
    "DETALLE DE MOVIMIENTOS ( PESOS )",
]
# Fallback si el PDF no trae "(PESOS)"
_SECTION_START_KEYS_FALLBACK = ["DETALLE DE MOVIMIENTOS"]

_SECTION_TERMINATORS = [
    "INVERSION ENLACE PERSONAL",
    "INVERSIÓN ENLACE PERSONAL",
    "GAT",
    "SIN MOVIMIENTOS",
]


def _strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch))


def norm_text(s: str) -> str:
    t = _strip_accents(str(s or ""))
    t = re.sub(r"\s+", " ", t).strip().upper()
    return t


def _parse_banorte_date_from_start(s_norm: str) -> Optional[tuple[str, str]]:
    """
    Devuelve (fecha_yyyy_mm_dd, resto_sin_fecha) si detecta al inicio.
    Acepta casos pegados: 01-ENE-26TRASPASO...
    """
    if not s_norm:
        return None
    m = _DATE_START_RE.match(s_norm)
    if not m:
        return None
    d = int(m.group("d"))
    mon = m.group("mon")
    y2 = int(m.group("y"))
    mm = _MONTHS.get(mon)
    if not mm:
        return None
    yyyy = 2000 + y2
    try:
        dt = date(yyyy, mm, d).isoformat()
    except Exception:
        return None
    rest = s_norm[m.end() :].strip()
    return dt, rest


def _parse_money_str(s: str) -> Optional[float]:
    """
    Convierte solo tokens que coinciden con dinero con 2 decimales: 10,000.00 -> 10000.00
    NO captura enteros (31), horas (17:19:33) ni referencias (0260101).
    """
    if s is None:
        return None
    t = str(s).strip().replace("$", "").replace(" ", "").replace(",", "")
    if not t or not re.match(r"^\d+\.\d{2}$", t):
        return None
    try:
        return float(t)
    except Exception:
        return None


# Solo montos con exactamente 2 decimales (evita 31, 33, 1, horas, referencias)
REGEX_MONEY = r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b"
_MONEY_RE = re.compile(REGEX_MONEY)


def extract_money_candidates(s: str) -> list[dict[str, Any]]:
    """Extrae solo montos con 2 decimales (sin enteros/horas/referencias)."""
    out: list[dict[str, Any]] = []
    if not s:
        return out
    for m in _MONEY_RE.finditer(s):
        raw = m.group(0)
        val = _parse_money_str(raw)
        if val is None:
            continue
        out.append({"raw": raw, "value": float(val), "start": m.start(), "end": m.end()})
    return out


def locate_sections(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Encuentra rangos (por índice sobre raw_rows) donde parece estar la tabla de movimientos.
    """
    sections: list[dict[str, Any]] = []
    in_section = False
    start_idx = None
    for i, r in enumerate(raw_rows):
        t = norm_text(r.get("Text") or "")
        if not t:
            continue
        is_start = any(k in t for k in _SECTION_START_KEYS) or any(
            k in t for k in _SECTION_START_KEYS_FALLBACK
        ) or (
            "FECHA" in t and "DESCRIP" in t and "DEPOS" in t and "RETIRO" in t and "SALDO" in t
        )
        is_terminator = any(k in t for k in _SECTION_TERMINATORS) or ("OTROS" == t.strip())
        is_cont = "CONTINUACION" in t or "CONTINUACIÓN" in t
        if (not in_section) and is_start:
            in_section = True
            start_idx = i
            continue
        if in_section and is_terminator and not is_cont:
            end_idx = i - 1
            if start_idx is not None and end_idx >= start_idx:
                sections.append({"start_idx": start_idx, "end_idx": end_idx})
            in_section = False
            start_idx = None
    if in_section and start_idx is not None:
        sections.append({"start_idx": start_idx, "end_idx": len(raw_rows) - 1})
    return sections


def _is_header_line(t_norm: str) -> bool:
    t = t_norm or ""
    if not t:
        return False
    if "FECHA" in t and "DESCRIP" in t and "SALDO" in t:
        return True
    if "MONTO DEL DEPOS" in t and "MONTO DEL RETIRO" in t:
        return True
    if "DETALLE DE MOVIMIENTOS" in t:
        return True
    # Ignorar "x/4" (página 1/4, 2/4, etc.)
    if re.match(r"^\d\s*/\s*\d\s*$", t.strip()) or re.match(r"^\s*\d\s*/\s*\d\s*$", t):
        return True
    return False


def build_transactions(section_rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """
    Agrupa filas en transacciones.
    Una transacción inicia cuando una línea comienza con DD-MMM-YY (pegado o con espacio).
    """
    txs: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for r in section_rows:
        t = norm_text(r.get("Text") or "")
        if not t:
            continue
        if _is_header_line(t):
            continue
        starts = _DATE_START_RE.match(t) is not None
        if starts:
            if cur:
                txs.append(cur)
            cur = [r]
        else:
            if cur:
                cur.append(r)
            else:
                # ruido antes de la primera fecha
                continue
    if cur:
        txs.append(cur)
    return txs


def _extract_ref(t_norm: str) -> str:
    m = re.search(r"\b(?:REFERENCIA|REF)\s*[:=\-]?\s*([A-Z0-9]{4,})\b", t_norm or "")
    return m.group(1) if m else ""


def _extract_cve_rastreo(t_norm: str) -> str:
    m = re.search(r"\bCVE\s+RAST(?:REO)?\s*[:=\-]?\s*([A-Z0-9]{8,40})\b", t_norm or "")
    return m.group(1) if m else ""


def _extract_rfc(t_norm: str) -> str:
    t = t_norm or ""
    m = re.search(r"\bRFC\s*[:=\-]?\s*([A-Z&Ñ0-9]{12,14})\b", t)
    if m:
        return m.group(1).strip()
    m = _RFC_RE.search(t)
    return m.group("rfc") if m else ""


def _metodo_hint(t_norm: str) -> str:
    t = t_norm or ""
    if "SPEI" in t:
        return "SPEI"
    if "NOMINA" in t:
        return "NOMINA"
    if "DOMICIL" in t:
        return "DOMICILIACION"
    if "TARJ" in t or "TDC" in t or "TARJETA DE CRED" in t:
        return "TARJETA"
    if "CAJERO" in t or "RETIRO DE EFECTIVO" in t or "EFECTIVO" in t:
        return "EFECTIVO"
    if "IMPUEST" in t or "SAT" in t or "HACIENDA" in t:
        return "IMPUESTO"
    return "OTRO"


def _contraparte_hint(t_norm: str) -> str:
    t = t_norm or ""
    if "OXXO" in t:
        return "OXXO"
    if "AMERICAN EXPRES" in t or "AMERICAN EXPRESS" in t:
        return "AMEX"
    if "PROFUTURO" in t:
        return "PROFUTURO"
    if "PAGO CONCENTRACION" in t and ("TARJETA DE CRED" in t or "TARJETA" in t or "TDC" in t):
        return "TDC"
    m = re.search(r"\bDEL CLIENTE\s+([A-Z0-9&Ñ ]{4,60})\b", t)
    if m:
        name = " ".join(m.group(1).split())[:40].strip()
        return name
    # fallback: primeras palabras útiles
    words = [w for w in re.split(r"[^A-Z0-9&Ñ]+", t) if w]
    stop = {"SPEI", "TRASPASO", "ABONO", "CARGO", "PAGO", "DEPOSITO", "DEPÓSITO", "RETIRO", "REFERENCIA", "REF", "CVE"}
    useful: list[str] = []
    for w in words:
        if len(w) < 3:
            continue
        if w in stop:
            continue
        useful.append(w)
        if len(useful) >= 2:
            break
    return " ".join(useful) if useful else ""


def _categoria(t_norm: str) -> str:
    t = t_norm or ""
    if any(k in t for k in ["COMISION", "IVA COMISION", "MANEJO"]):
        return "COMISIONES_BANCARIAS"
    if any(k in t for k in ["IMPUESTO", "SAT", "HACIENDA"]):
        return "IMPUESTOS"
    if any(k in t for k in ["OXXO", "7-ELEVEN", "BENAVIDES"]):
        return "ALIMENTOS"
    if any(k in t for k in ["TARJETA DE CRED", "AMERICAN EXPRES", "AMERICAN EXPRESS", "PAGO CONCENTRACION"]):
        return "TARJETAS_CREDITO"
    if any(k in t for k in ["SPEI", "TRASPASO"]):
        return "TRANSFERENCIAS"
    if "NOMINA" in t:
        return "NOMINA"
    if any(k in t for k in ["RETIRO DE EFECTIVO", "CAJERO"]):
        return "EFECTIVO"
    return "OTROS"


def _approx(a: float, b: float, tol_abs: float = 2.0, tol_rel: float = 0.005) -> bool:
    if a is None or b is None:
        return False
    d = abs(a - b)
    return d <= max(tol_abs, abs(b) * tol_rel)


def parse_transaction(
    tx_rows: list[dict[str, Any]],
    *,
    prev_saldo: Optional[float] = None,
) -> dict[str, Any]:
    """
    Parsea una transacción a partir de sus líneas agrupadas.
    """
    raw_lines = [str(r.get("Text") or "").strip() for r in tx_rows if (r.get("Text") or "").strip()]
    joined_raw = " ".join(raw_lines).strip()
    joined_norm = norm_text(joined_raw)

    debug: dict[str, Any] = {"raw_lines": raw_lines[:], "decisions": []}

    dt_and_rest = _parse_banorte_date_from_start(joined_norm)
    if not dt_and_rest:
        fecha = ""
        rest = joined_norm
        debug["decisions"].append("no_fecha_al_inicio")
    else:
        fecha, rest = dt_and_rest
        debug["decisions"].append("fecha_parseada")

    # SALDO ANTERIOR => tipo INFO (no es movimiento contable)
    es_saldo_anterior = "SALDO ANTERIOR" in joined_norm
    if es_saldo_anterior:
        debug["decisions"].append("saldo_anterior=>INFO")

    # extracción de montos (solo con 2 decimales; sin basura)
    candidates = extract_money_candidates(joined_norm)
    values = [c["value"] for c in candidates]
    debug["money_candidates"] = candidates

    saldo: Optional[float] = None
    deposito: Optional[float] = None
    retiro: Optional[float] = None

    if values:
        # Banorte: el último suele ser saldo
        saldo = values[-1]
        debug["decisions"].append("saldo=ultimo_monto")
        rest_amounts = values[:-1]
    else:
        rest_amounts = []
        debug["decisions"].append("sin_montos")

    metodo = _metodo_hint(joined_norm)
    keywords_in = ["SPEI RECIBIDO", "DEPOSITO", "DEPÓSITO", "ABONO", "NOMINA", "TRASPASO RECIBIDO"]
    keywords_out = ["CARGO", "COMPRA", "PAGO", "DOMICILIACION", "DOMICILIACIÓN", "RETIRO", "IMPUESTO", "ORDEN DE PAGO SPEI"]
    is_in = any(k in joined_norm for k in keywords_in)
    is_out = any(k in joined_norm for k in keywords_out)

    # heurística de asignación
    if len(rest_amounts) == 1:
        amt = rest_amounts[0]
        if is_in and not is_out:
            deposito = amt
            debug["decisions"].append("monto_unico=>deposito_por_keyword")
        elif is_out and not is_in:
            retiro = amt
            debug["decisions"].append("monto_unico=>retiro_por_keyword")
        else:
            # ambiguo: inferir por secuencia si hay saldo previo
            if prev_saldo is not None and saldo is not None:
                if _approx(prev_saldo + amt, saldo):
                    deposito = amt
                    debug["decisions"].append("monto_unico=>deposito_por_secuencia")
                elif _approx(prev_saldo - amt, saldo):
                    retiro = amt
                    debug["decisions"].append("monto_unico=>retiro_por_secuencia")
                else:
                    retiro = amt
                    debug["decisions"].append("monto_unico=>retiro_default_ambiguo")
            else:
                retiro = amt
                debug["decisions"].append("monto_unico=>retiro_default_sin_secuencia")
    elif len(rest_amounts) == 2:
        a1, a2 = rest_amounts
        # algunos PDFs traen depósito/retiro y saldo, pero ya removimos saldo; aquí serían 2 montos extra (raro)
        # tratar: elegir uno como monto y otro ignorar, usando keywords
        amt = a1
        if is_in and not is_out:
            deposito = amt
            debug["decisions"].append("2_montos=>deposito=a1_por_keyword")
        elif is_out and not is_in:
            retiro = amt
            debug["decisions"].append("2_montos=>retiro=a1_por_keyword")
        else:
            # probar secuencia con a1 y a2
            if prev_saldo is not None and saldo is not None:
                if _approx(prev_saldo + a1, saldo):
                    deposito = a1
                    debug["decisions"].append("2_montos=>deposito=a1_por_secuencia")
                elif _approx(prev_saldo - a1, saldo):
                    retiro = a1
                    debug["decisions"].append("2_montos=>retiro=a1_por_secuencia")
                elif _approx(prev_saldo + a2, saldo):
                    deposito = a2
                    debug["decisions"].append("2_montos=>deposito=a2_por_secuencia")
                elif _approx(prev_saldo - a2, saldo):
                    retiro = a2
                    debug["decisions"].append("2_montos=>retiro=a2_por_secuencia")
                else:
                    retiro = a1
                    debug["decisions"].append("2_montos=>retiro_default")
            else:
                retiro = a1
                debug["decisions"].append("2_montos=>retiro_default_sin_secuencia")
    elif len(rest_amounts) >= 3:
        # si hay 3+ montos antes del saldo, elegir el más cercano a delta con prev_saldo
        if prev_saldo is not None and saldo is not None:
            best = None
            best_kind = None
            best_diff = None
            for amt in rest_amounts:
                diff_in = abs((prev_saldo + amt) - saldo)
                diff_out = abs((prev_saldo - amt) - saldo)
                if best_diff is None or diff_in < best_diff:
                    best, best_kind, best_diff = amt, "deposito", diff_in
                if best_diff is None or diff_out < best_diff:
                    best, best_kind, best_diff = amt, "retiro", diff_out
            if best is not None and best_diff is not None and best_diff <= max(2.0, abs(saldo) * 0.005):
                if best_kind == "deposito":
                    deposito = best
                    debug["decisions"].append("3+_montos=>deposito_por_mejor_secuencia")
                else:
                    retiro = best
                    debug["decisions"].append("3+_montos=>retiro_por_mejor_secuencia")
            else:
                # fallback keyword
                amt = rest_amounts[0]
                if is_in and not is_out:
                    deposito = amt
                    debug["decisions"].append("3+_montos=>deposito_por_keyword_fallback")
                else:
                    retiro = amt
                    debug["decisions"].append("3+_montos=>retiro_por_default_fallback")
        else:
            amt = rest_amounts[0]
            if is_in and not is_out:
                deposito = amt
                debug["decisions"].append("3+_montos=>deposito_por_keyword_sin_secuencia")
            else:
                retiro = amt
                debug["decisions"].append("3+_montos=>retiro_default_sin_secuencia")

    tipo = "DESCONOCIDO"
    if es_saldo_anterior:
        tipo = "INFO"
        deposito = None
        retiro = None
        # saldo se mantiene si se extrajo
    elif deposito and deposito > 0:
        tipo = "INGRESO"
    elif retiro and retiro > 0:
        tipo = "GASTO"

    referencia = _extract_ref(joined_norm)
    cve_rastreo = _extract_cve_rastreo(joined_norm)
    rfc = _extract_rfc(joined_norm)
    contraparte = _contraparte_hint(joined_norm)
    categoria = _categoria(joined_norm)

    # confidence_score: +40 fecha, +30 saldo, +20 monto principal, +10 keyword, +10 validación, -20 si 1 monto o SALDO ANTERIOR
    score = 0
    if fecha:
        score += 40
    if saldo is not None:
        score += 30
    if (deposito or 0) > 0 or (retiro or 0) > 0:
        score += 20
    if (is_in and not is_out) or (is_out and not is_in):
        score += 10
    if prev_saldo is not None and saldo is not None and (deposito or retiro):
        expected = prev_saldo + (deposito or 0.0) - (retiro or 0.0)
        if _approx(expected, saldo):
            score += 10
            debug["decisions"].append("secuencia_ok")
        else:
            debug["decisions"].append("secuencia_no_cuadra")
    if len(values) == 1 or es_saldo_anterior:
        score -= 20
        debug["decisions"].append("penalidad_1_monto_o_saldo_anterior")
    score = max(0, min(100, score))

    source_page_first = int(tx_rows[0].get("Page") or 0) if tx_rows else 0
    source_page_last = int(tx_rows[-1].get("Page") or 0) if tx_rows else source_page_first
    return {
        "fecha": fecha,
        "descripcion_full": " ".join(joined_raw.split()),
        "descripcion_norm": joined_norm,
        "deposito": deposito,
        "retiro": retiro,
        "saldo": saldo,
        "tipo": tipo,
        "referencia": referencia,
        "cve_rastreo": cve_rastreo,
        "rfc_encontrado": rfc,
        "contraparte_hint": contraparte,
        "categoria": categoria,
        "metodo_hint": metodo,
        "confidence_score": score,
        "source_page_first": source_page_first,
        "source_page_last": source_page_last,
        "_debug": debug,
    }


@dataclass
class ParseResult:
    transactions: list[dict[str, Any]]
    sections: list[dict[str, Any]]
    metrics: dict[str, Any]
    debug_payload: dict[str, Any]


def parse_bank_statement(
    raw_rows: list[dict[str, Any]],
    *,
    debug: bool = False,
) -> ParseResult:
    sections = locate_sections(raw_rows)
    txs_grouped: list[list[dict[str, Any]]] = []
    for sec in sections:
        start = int(sec["start_idx"])
        end = int(sec["end_idx"])
        txs_grouped.extend(build_transactions(raw_rows[start : end + 1]))

    parsed: list[dict[str, Any]] = []
    prev_saldo = None
    for g in txs_grouped:
        tx = parse_transaction(g, prev_saldo=prev_saldo)
        parsed.append(tx)
        if isinstance(tx.get("saldo"), (int, float)):
            prev_saldo = float(tx["saldo"])

    movements_count = sum(1 for t in parsed if (t.get("deposito") or 0) > 0 or (t.get("retiro") or 0) > 0)
    saldo_count = sum(1 for t in parsed if isinstance(t.get("saldo"), (int, float)))
    rfc_count = sum(1 for t in parsed if (t.get("rfc_encontrado") or "").strip())
    rastreo_count = sum(1 for t in parsed if (t.get("cve_rastreo") or "").strip())
    avg_conf = (sum(float(t.get("confidence_score") or 0) for t in parsed) / len(parsed)) if parsed else 0.0
    sin_parse_count = sum(1 for t in parsed if not ((t.get("deposito") or 0) > 0 or (t.get("retiro") or 0) > 0))
    low_confidence_count = sum(1 for t in parsed if int(t.get("confidence_score") or 0) < 60)

    total_ingresos = sum(float(t.get("deposito") or 0) for t in parsed if isinstance(t.get("deposito"), (int, float)))
    total_gastos = sum(float(t.get("retiro") or 0) for t in parsed if isinstance(t.get("retiro"), (int, float)))

    metrics = {
        "sections_detected": len(sections),
        "transactions_grouped": len(txs_grouped),
        "movements_count": movements_count,
        "sin_parse_count": sin_parse_count,
        "saldo_count": saldo_count,
        "rfc_count": rfc_count,
        "rastreo_count": rastreo_count,
        "avg_confidence": avg_conf,
        "low_confidence_count": low_confidence_count,
        "total_ingresos": total_ingresos,
        "total_gastos": total_gastos,
    }

    debug_payload = {}
    if debug:
        debug_payload = {
            "sections": sections,
            "metrics": metrics,
            "transactions": [
                {k: v for k, v in t.items() if k != "_debug"} | {"debug": t.get("_debug")}
                for t in parsed
            ],
        }

    return ParseResult(transactions=parsed, sections=sections, metrics=metrics, debug_payload=debug_payload)


def write_debug_json(debug_payload: dict[str, Any], path_abs: str) -> None:
    if not debug_payload:
        return
    with open(path_abs, "w", encoding="utf-8") as f:
        json.dump(debug_payload, f, ensure_ascii=False, indent=2)


def _movement_hash(issuer_id: int, tx: dict[str, Any]) -> str:
    """sha256(issuer_id + fecha + abs(deposito-retiro) + saldo(optional) + descripcion_norm[:80])"""
    import hashlib
    d = float(tx.get("deposito") or 0)
    r = float(tx.get("retiro") or 0)
    s = tx.get("saldo")
    desc = (tx.get("descripcion_norm") or "")[:80]
    fecha = tx.get("fecha") or ""
    payload = f"{issuer_id}|{fecha}|{abs(d - r)}|{s}|{desc}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upsert_bank_movements(
    issuer_id: int,
    statement_id: int,
    transactions: list[dict[str, Any]],
) -> int:
    """
    Inserta o actualiza movimientos en bank_movements (solo INGRESO/GASTO).
    Dedupe por (issuer_id, movement_hash). Devuelve cantidad de filas insertadas/actualizadas.
    """
    from database import db

    count = 0
    conn = db()
    try:
        for tx in transactions:
            tipo = (tx.get("tipo") or "").strip().upper()
            if tipo not in ("INGRESO", "GASTO"):
                continue
            h = _movement_hash(issuer_id, tx)
            fecha = tx.get("fecha") or ""
            descripcion = (tx.get("descripcion") or tx.get("descripcion_full") or tx.get("descripcion_raw") or "")[:2000]
            raw_description = (tx.get("descripcion_full") or tx.get("descripcion_raw") or descripcion)[:4000]
            normalized_description = (tx.get("descripcion_norm") or "")[:4000]
            deposito = float(tx.get("deposito") or 0)
            retiro = float(tx.get("retiro") or 0)
            saldo = tx.get("saldo")
            if saldo is not None:
                saldo = float(saldo)
            categoria = (tx.get("categoria") or "")[:200]
            metodo_hint = (tx.get("metodo_hint") or "")[:64]
            contraparte_hint = (tx.get("contraparte_hint") or "")[:200]
            reference_text = (tx.get("referencia") or tx.get("reference_text") or "")[:128]
            rfc_encontrado = (tx.get("rfc_encontrado") or "")[:20]
            confidence_score = int(tx.get("confidence_score") or 0)
            source_page_first = tx.get("source_page_first")
            if source_page_first is not None:
                source_page_first = int(source_page_first)

            # Derive period_month from fecha (YYYY-MM-DD → YYYY-MM)
            period_month = None
            if fecha and len(fecha) >= 7 and fecha[4:5] == "-" and fecha[:4].isdigit() and fecha[5:7].isdigit():
                period_month = fecha[:7]

            # Check if movement already exists by hash (partial unique index)
            existing = conn.execute(
                "SELECT id FROM bank_movements WHERE issuer_id = ? AND movement_hash = ? LIMIT 1",
                (issuer_id, h),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE bank_movements SET
                      statement_file_id = ?, fecha = ?, descripcion = ?,
                      raw_description = ?, normalized_description = ?,
                      deposito = ?, retiro = ?, saldo = ?, tipo = ?,
                      categoria = ?, metodo_hint = ?, contraparte_hint = ?,
                      reference_text = ?, rfc_encontrado = ?, confidence_score = ?,
                      source_page_first = ?,
                      period_month = COALESCE(?, period_month)
                    WHERE id = ?
                    """,
                    (
                        statement_id, fecha, descripcion,
                        raw_description, normalized_description,
                        deposito, retiro, saldo, tipo,
                        categoria, metodo_hint, contraparte_hint,
                        reference_text, rfc_encontrado, confidence_score,
                        source_page_first,
                        period_month,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO bank_movements (
                      issuer_id, statement_file_id, movement_hash, fecha, descripcion,
                      raw_description, normalized_description,
                      deposito, retiro, saldo, tipo, categoria, metodo_hint, contraparte_hint,
                      reference_text, rfc_encontrado, confidence_score,
                      source_page_first, period_month, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        issuer_id, statement_id, h, fecha, descripcion,
                        raw_description, normalized_description,
                        deposito, retiro, saldo, tipo,
                        categoria, metodo_hint, contraparte_hint,
                        reference_text, rfc_encontrado, confidence_score,
                        source_page_first, period_month,
                    ),
                )
            count += 1
        conn.commit()
    finally:
        conn.close()
    return count


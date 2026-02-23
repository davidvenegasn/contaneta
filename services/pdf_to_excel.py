import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Iterable, Any


_DATE_PATTERNS = [
    re.compile(r"^(?P<d>\d{2})[\/\-](?P<m>\d{2})[\/\-](?P<y>\d{2,4})\b"),
    re.compile(r"^(?P<y>\d{4})[\/\-](?P<m>\d{2})[\/\-](?P<d>\d{2})\b"),
    re.compile(r"^(?P<d>\d{2})[\/\-\s](?P<mon>[A-Za-zÁÉÍÓÚÜÑ\.]{3,})[\/\-\s](?P<y>\d{2,4})\b"),
]

_MONTHS = {
    # ES
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
    # EN
    "JAN": 1,
    "APR": 4,
    "AUG": 8,
    "DEC": 12,
}

_BANK_KEYWORDS = [
    ("BBVA", ["BBVA", "BANCOMER"]),
    ("SANTANDER", ["SANTANDER"]),
    ("BANORTE", ["BANORTE"]),
    ("CITIBANAMEX", ["CITIBANAMEX", "BANAMEX"]),
    ("HSBC", ["HSBC"]),
    ("SCOTIABANK", ["SCOTIABANK", "SCOTIA"]),
    ("INBURSA", ["INBURSA"]),
    ("AZTECA", ["BANCO AZTECA", "AZTECA"]),
]

_STOPWORDS_CP = {
    "PAGO",
    "PAGOS",
    "COMPRA",
    "COMPRAS",
    "CARGO",
    "ABONO",
    "DEPOSITO",
    "DEPÓSITO",
    "DEP",
    "TRANSFERENCIA",
    "TRANSFER",
    "TRANSF",
    "TRASPASO",
    "TRASP",
    "SPEI",
    "SPID",
    "COMISION",
    "COMISIONES",
    "IVA",
    "REF",
    "REFERENCIA",
    "FOLIO",
    "AUT",
    "AUTORIZACION",
    "AUTORIZACIÓN",
    "ID",
    "NUM",
    "NO",
    "CTA",
    "CUENTA",
    "TARJ",
    "TARJETA",
    "DEBITO",
    "DÉBITO",
    "CREDITO",
    "CRÉDITO",
    "POS",
    "TPV",
}

_KNOWN_COUNTERPARTIES = [
    "AMAZON",
    "UBER",
    "DIDI",
    "CFE",
    "TELCEL",
    "TELMEX",
    "AT&T",
    "MOVISTAR",
    "TOTALPLAY",
    "IZZI",
    "NETFLIX",
    "SPOTIFY",
    "GOOGLE",
    "APPLE",
    "MICROSOFT",
    "AWS",
    "OPENAI",
    "ADOBE",
    "WALMART",
    "COSTCO",
    "SORIANA",
    "OXXO",
    "7-ELEVEN",
    "SEVEN",
    "PEMEX",
]


def get_storage_root(base_dir: str) -> str:
    """
    Root de storage. Respeta env APP_STORAGE_PATH si existe.
    - Si APP_STORAGE_PATH es relativo, se resuelve contra base_dir.
    - Siempre regresa ruta absoluta normalizada.
    """
    raw = (os.environ.get("APP_STORAGE_PATH") or "").strip()
    if raw:
        root = raw if os.path.isabs(raw) else os.path.join(base_dir, raw)
    else:
        root = os.path.join(base_dir, "storage")
    return os.path.normpath(os.path.abspath(root))


def safe_join(root_abs: str, *parts: str) -> str:
    """Une paths y asegura que queden bajo root_abs (previene path traversal)."""
    root_abs = os.path.normpath(os.path.abspath(root_abs))
    p = os.path.join(root_abs, *[str(x) for x in parts])
    abs_p = os.path.normpath(os.path.abspath(p))
    if abs_p == root_abs:
        return abs_p
    if not abs_p.startswith(root_abs + os.sep):
        raise ValueError("Ruta inválida (path traversal)")
    return abs_p


def ensure_parent_dir(path_abs: str) -> None:
    os.makedirs(os.path.dirname(path_abs), exist_ok=True)


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
    Intenta detectar rango de periodo en el PDF.
    Devuelve (period_start, period_end) como YYYY-MM-DD o ("","") si no detecta.
    """
    t = all_text_norm or ""
    # ejemplos: "DEL 01/01/2026 AL 31/01/2026"
    m = re.search(
        r"\bDEL\s+(\d{2}[\/\-]\d{2}[\/\-]\d{2,4})\s+(?:AL|A)\s+(\d{2}[\/\-]\d{2}[\/\-]\d{2,4})\b",
        t,
    )
    if m:
        d1 = _detect_date(m.group(1))
        d2 = _detect_date(m.group(2))
        return (d1 or "", d2 or "")
    return ("", "")


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


@dataclass
class ConvertMeta:
    rows: int
    raw_lines: int
    mode: str  # 'parsed' | 'raw'


def convert_pdf_to_xlsx(pdf_path_abs: str, xlsx_path_abs: str, issuer_id: int | None = None) -> dict[str, Any]:
    """
    Convierte un PDF de estado de cuenta a Excel.
    - Intenta heurística simple (fecha + montos) con normalización.
    - Genera un XLSX con estructura contable útil (Movimientos/Gastos/Ingresos/Resumen/Conciliacion_CFDI/Gastos_sin_factura).
    - Siempre genera un XLSX válido. Si no detecta estructura, genera RAW y hojas vacías con headers.
    """
    try:
        import pdfplumber  # lazy import (dependencia opcional hasta instalar)
    except ModuleNotFoundError:
        pdfplumber = None
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    from openpyxl.utils import get_column_letter

    if not os.path.isfile(pdf_path_abs):
        raise FileNotFoundError("PDF no encontrado")

    HEAD_MOV = [
        "movimiento_id",
        "issuer_id",
        "bank_name",
        "account_last4",
        "period_start",
        "period_end",
        "fecha",
        "descripcion_raw",
        "descripcion_norm",
        "referencia",
        "tipo",
        "monto",
        "moneda",
        "saldo",
        "categoria",
        "subcategoria",
        "metodo_pago_hint",
        "contraparte_hint",
        "es_comision_bancaria",
        "es_impuesto_bancario",
        "posible_facturable",
        "match_cfdi_uuid",
        "match_score",
        "match_status",
        "parse_confidence",
    ]
    HEAD_C = [
        "movimiento_id",
        "fecha_mov",
        "monto_gasto",
        "contraparte_hint",
        "categoria",
        "cfdi_uuid_sugerido",
        "cfdi_fecha",
        "cfdi_total",
        "cfdi_rfc_emisor",
        "cfdi_nombre_emisor",
        "score_sugerido",
        "decision_usuario",
        "cfdi_uuid_final",
        "nota",
    ]
    HEAD_GSF = ["movimiento_id", "fecha", "monto", "contraparte_hint", "categoria", "motivo"]

    def _freeze_filter(ws, ncols: int, nrows: int) -> None:
        ws.freeze_panes = "A2"
        if ncols >= 1 and nrows >= 1:
            ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}{nrows}"

    def _autosize(ws, ncols: int, max_width: int = 60) -> None:
        for col in range(1, ncols + 1):
            letter = get_column_letter(col)
            best = 0
            for cell in ws[letter]:
                v = cell.value
                if v is None:
                    continue
                s = str(v)
                if len(s) > best:
                    best = len(s)
            ws.column_dimensions[letter].width = min(max(10, best + 2), max_width)

    def _write_table(ws, headers: list[str], rows: list[list[Any]], money_cols: Iterable[int] = ()) -> None:
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for r in rows:
            ws.append(r)
        nrows = 1 + len(rows)
        ncols = len(headers)
        _freeze_filter(ws, ncols, nrows)
        for cidx in money_cols:
            for r in range(2, nrows + 1):
                cell = ws.cell(row=r, column=cidx)
                if isinstance(cell.value, (int, float)):
                    cell.number_format = '"$"#,##0.00'
        _autosize(ws, ncols)

    if pdfplumber is None:
        ensure_parent_dir(xlsx_path_abs)
        wb = Workbook()
        wb.remove(wb.active)
        _write_table(wb.create_sheet("Movimientos"), HEAD_MOV, [], money_cols=[12, 14])
        _write_table(wb.create_sheet("Gastos"), HEAD_MOV, [], money_cols=[12, 14])
        _write_table(wb.create_sheet("Ingresos"), HEAD_MOV, [], money_cols=[12, 14])
        ws_r = wb.create_sheet("Resumen")
        ws_r.append(["campo", "valor"])
        ws_r["A1"].font = Font(bold=True)
        ws_r["B1"].font = Font(bold=True)
        ws_r.append(["error", "Falta dependencia: pdfplumber (instala requirements.txt)"])
        ws_r.freeze_panes = "A2"
        _write_table(wb.create_sheet("Conciliacion_CFDI"), HEAD_C, [], money_cols=[3, 8])
        _write_table(wb.create_sheet("Gastos_sin_factura"), HEAD_GSF, [], money_cols=[3])
        _write_table(wb.create_sheet("RAW"), ["page", "line", "text"], [], money_cols=[])
        wb.save(xlsx_path_abs)
        return {
            "rows": 0,
            "raw_lines": 0,
            "mode": "raw",
            "error": "pdfplumber_missing",
            "processed_count": 0,
            "total_ingresos": 0.0,
            "total_gastos": 0.0,
            "sin_factura_count": 0,
        }

    raw_rows: list[dict[str, Any]] = []
    parsed_rows: list[dict[str, Any]] = []  # filas base tipo v1 (fecha/descripcion/cargo/abono/saldo)

    # métricas de extracción (calidad)
    date_lines = 0
    movement_candidate_lines = 0
    parsed_movement_lines = 0
    blank_desc_lines = 0

    prev_saldo: Optional[float] = None
    with pdfplumber.open(pdf_path_abs) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if (ln or "").strip()]
            for li, ln in enumerate(lines, start=1):
                raw_rows.append({"Page": page_idx, "Line": li, "Text": ln})

            for ln in lines:
                # detectar fecha al inicio del renglón (lo más común)
                dt = _detect_date(ln)
                if not dt:
                    continue
                date_lines += 1
                # quitar fecha al inicio para parsear lo demás
                rest = (ln or "").strip()
                rest = re.sub(r"^\s*\d{2}[\/\-]\d{2}[\/\-]\d{2,4}\s+", "", rest)
                rest = re.sub(r"^\s*\d{4}[\/\-]\d{2}[\/\-]\d{2}\s+", "", rest)
                rest = re.sub(r"^\s*\d{2}[\/\-\s][A-Za-zÁÉÍÓÚÜÑ\.]{3,}[\/\-\s]\d{2,4}\s+", "", rest)

                # estrategia columnas (si hay)
                cols = _split_columns(rest)
                if cols and len(cols) >= 2:
                    rest_for_amounts = " ".join(cols)
                else:
                    rest_for_amounts = rest

                desc_wo_amounts, amounts = _extract_amounts_from_end(rest_for_amounts, max_amounts=3)
                if amounts:
                    movement_candidate_lines += 1
                descripcion = (desc_wo_amounts or "").strip()
                if not descripcion:
                    blank_desc_lines += 1
                    continue

                cargo = None
                abono = None
                saldo = None
                if len(amounts) >= 3:
                    cargo = amounts[-3]
                    abono = amounts[-2]
                    saldo = amounts[-1]
                elif len(amounts) == 2:
                    # suele ser (cargo|abono, saldo)
                    saldo = amounts[-1]
                    trans = amounts[-2]
                    dnorm = _norm_text(descripcion)
                    if any(k in dnorm for k in ["ABONO", "DEPOSITO", "DEPÓSITO", "DEPOSITO", "DEPOSITO"]):
                        abono = trans
                    else:
                        cargo = trans
                elif len(amounts) == 1:
                    # a veces solo viene un monto; usar heurística por keywords y/o delta de saldo si existe
                    trans = amounts[0]
                    dnorm = _norm_text(descripcion)
                    if any(k in dnorm for k in ["ABONO", "DEPOSITO", "DEPÓSITO", "DEPOSITO"]):
                        abono = trans
                    elif any(k in dnorm for k in ["CARGO", "COMPRA", "PAGO", "COMISION", "RETIRO"]):
                        cargo = trans
                    else:
                        # desconocido -> cargo por defecto (es más común en estados)
                        cargo = trans

                # delta por saldo (si hay)
                if saldo is not None and prev_saldo is not None and (cargo is None and abono is None):
                    delta = saldo - prev_saldo
                    if delta >= 0:
                        abono = delta
                    else:
                        cargo = abs(delta)
                if saldo is not None:
                    prev_saldo = saldo

                parsed_movement_lines += 1
                parsed_rows.append(
                    {
                        "Fecha": dt,
                        "Descripción": descripcion,
                        "Referencia": "",
                        "Cargo": cargo,
                        "Abono": abono,
                        "Saldo": saldo,
                    }
                )

    ensure_parent_dir(xlsx_path_abs)
    mode = "parsed" if parsed_rows else "raw"

    all_text_norm = _norm_text(" ".join([r["Text"] for r in raw_rows]))
    has_text = len(raw_rows) > 0 and bool(all_text_norm.strip())
    section_found = any(
        kw in all_text_norm
        for kw in [
            "DETALLE DE MOVIMIENTOS",
            "DETALLE MOVIMIENTOS",
            "RELACION DE MOVIMIENTOS",
            "RELACIÓN DE MOVIMIENTOS",
            "MOVIMIENTOS DEL PERIODO",
            "MOVIMIENTOS DEL MES",
        ]
    )
    bank_name = _detect_bank_name(all_text_norm)
    account_last4 = _detect_account_last4(all_text_norm)
    period_start, period_end = _detect_period(all_text_norm)

    # normalizar movimientos a la estructura nueva
    movimientos: list[dict[str, Any]] = []
    fechas_ok: list[date] = []

    low_confidence_count = 0
    for idx, r in enumerate(parsed_rows, start=1):
        fecha_s = r.get("Fecha") or ""
        fd = _to_date(fecha_s)
        if fd:
            fechas_ok.append(fd)
        desc_raw = str(r.get("Descripción") or "").strip()
        desc_norm = _norm_text(desc_raw)
        referencia = _extract_referencia(desc_norm)

        cargo = r.get("Cargo")
        abono = r.get("Abono")
        saldo = r.get("Saldo")
        tipo = ""
        monto = None
        if abono is not None and float(abono or 0) > 0:
            tipo = "INGRESO"
            monto = abs(float(abono))
        elif cargo is not None and float(cargo or 0) > 0:
            tipo = "GASTO"
            monto = abs(float(cargo))
        else:
            # si no se pudo inferir, skip (o dejar vacío)
            tipo = ""
            monto = None

        confidence = "OK"
        if not tipo or monto is None or saldo is None or len(desc_raw) < 6:
            confidence = "BAJA"
        if confidence == "BAJA" and tipo in ("INGRESO", "GASTO"):
            low_confidence_count += 1

        categoria, subcategoria, es_com, es_imp, fact = _clasificar(desc_norm)
        metodo = _metodo_pago_hint(desc_norm)
        contraparte = _contraparte_hint(desc_norm)

        # movimiento_id estable por contenido (evita colisiones al reordenar)
        base = f"{issuer_id or 0}|{fecha_s}|{desc_norm}|{monto or ''}|{saldo or ''}"
        h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
        mov_id = f"{issuer_id or 0}-{fecha_s.replace('-', '')}-{h}-{idx}"

        movimientos.append(
            {
                "movimiento_id": mov_id,
                "issuer_id": int(issuer_id or 0) if issuer_id is not None else "",
                "bank_name": bank_name,
                "account_last4": account_last4,
                "period_start": period_start,
                "period_end": period_end,
                "fecha": fecha_s,
                "descripcion_raw": desc_raw,
                "descripcion_norm": desc_norm,
                "referencia": referencia,
                "tipo": tipo,
                "monto": float(monto) if monto is not None else "",
                "moneda": "MXN",
                "saldo": float(saldo) if saldo is not None else "",
                "categoria": categoria,
                "subcategoria": subcategoria,
                "metodo_pago_hint": metodo,
                "contraparte_hint": contraparte,
                "es_comision_bancaria": int(es_com),
                "es_impuesto_bancario": int(es_imp),
                "posible_facturable": int(fact) if tipo == "GASTO" else 0,
                "match_cfdi_uuid": "",
                "match_score": "",
                "match_status": "PENDIENTE",
                "parse_confidence": confidence,
            }
        )

    # si no detectó periodo del texto, usar min/max de fechas
    if (not period_start or not period_end) and fechas_ok:
        dmin = min(fechas_ok).isoformat()
        dmax = max(fechas_ok).isoformat()
        period_start = period_start or dmin
        period_end = period_end or dmax
        for m in movimientos:
            m["period_start"] = period_start
            m["period_end"] = period_end

    # cargar CFDIs recibidos (una sola vez) y sugerir match para gastos
    cfdis: list[dict[str, Any]] = []
    concilia_rows: list[list[Any]] = []
    sugerencias: dict[str, dict[str, Any]] = {}
    if issuer_id and fechas_ok:
        try:
            from database import db, has_column
        except Exception:
            db = None
            has_column = None
        if db:
            conn = db()
            try:
                has_tipo = has_column(conn, "sat_cfdi", "tipo_comprobante") if has_column else True
                where_extra = " AND (tipo_comprobante IS NULL OR UPPER(TRIM(tipo_comprobante)) != 'N')" if has_tipo else ""
                d0 = (min(fechas_ok) - timedelta(days=7)).isoformat()
                d1 = (max(fechas_ok) + timedelta(days=7)).isoformat()
                rows = conn.execute(
                    f"""
                    SELECT uuid, fecha_emision, total, rfc_emisor, COALESCE(nombre_emisor, '') AS nombre_emisor
                    FROM sat_cfdi
                    WHERE issuer_id = ? AND direction = 'received'
                      AND fecha_emision IS NOT NULL
                      AND substr(fecha_emision,1,10) >= ? AND substr(fecha_emision,1,10) <= ?
                      AND total IS NOT NULL AND total >= 0.01
                      {where_extra}
                    """,
                    (int(issuer_id), d0, d1),
                ).fetchall()
                cfdis = [dict(x) for x in rows] if rows else []
            finally:
                conn.close()

    # preparar conciliación (solo gastos)
    for m in movimientos:
        if m.get("tipo") != "GASTO":
            continue
        mov_date = _to_date(m.get("fecha"))
        mov_amount = m.get("monto")
        if not mov_date or not mov_amount or not isinstance(mov_amount, (int, float)):
            best, score = None, 0
        else:
            best, score = _best_cfdi_for_movement(mov_date, float(mov_amount), m.get("contraparte_hint") or "", cfdis)
        suger = {
            "cfdi_uuid_sugerido": (best.get("uuid") if best else "") if score > 0 else "",
            "cfdi_fecha": (best.get("fecha_emision") or "")[:10] if best else "",
            "cfdi_total": float(best.get("total")) if (best and best.get("total") is not None) else "",
            "cfdi_rfc_emisor": (best.get("rfc_emisor") or "") if best else "",
            "cfdi_nombre_emisor": (best.get("nombre_emisor") or "") if best else "",
            "score": int(score) if score else "",
        }
        sugerencias[m["movimiento_id"]] = suger
        concilia_rows.append(
            [
                m["movimiento_id"],
                m.get("fecha") or "",
                m.get("monto") if isinstance(m.get("monto"), (int, float)) else "",
                m.get("contraparte_hint") or "",
                m.get("categoria") or "",
                suger["cfdi_uuid_sugerido"],
                suger["cfdi_fecha"],
                suger["cfdi_total"],
                suger["cfdi_rfc_emisor"],
                suger["cfdi_nombre_emisor"],
                suger["score"],
                "",
                "",
                "",
            ]
        )

    # gastos sin factura
    gastos_sin_factura_rows: list[list[Any]] = []
    for m in movimientos:
        if m.get("tipo") != "GASTO":
            continue
        if (m.get("categoria") or "").strip().upper() == "COMISIONES BANCARIAS":
            continue
        sug = sugerencias.get(m["movimiento_id"]) or {}
        score = sug.get("score")
        score_ok = isinstance(score, int) and score >= 70
        if score_ok:
            continue
        gastos_sin_factura_rows.append(
            [
                m["movimiento_id"],
                m.get("fecha") or "",
                m.get("monto") if isinstance(m.get("monto"), (int, float)) else "",
                m.get("contraparte_hint") or "",
                m.get("categoria") or "",
                "SIN MATCH CFDI",
            ]
        )

    # resumen
    ingresos = [m for m in movimientos if m.get("tipo") == "INGRESO" and isinstance(m.get("monto"), (int, float))]
    gastos = [m for m in movimientos if m.get("tipo") == "GASTO" and isinstance(m.get("monto"), (int, float))]
    total_ingresos = sum(float(m["monto"]) for m in ingresos)
    total_gastos = sum(float(m["monto"]) for m in gastos)
    neto = total_ingresos - total_gastos
    n_movs = len([m for m in movimientos if (m.get("tipo") in ("INGRESO", "GASTO"))])
    total_comisiones = sum(float(m["monto"]) for m in gastos if int(m.get("es_comision_bancaria") or 0) == 1)

    partial_parse = False
    partial_reason = ""
    no_movements_reason = ""
    if has_text and (date_lines > 0 or movement_candidate_lines > 0):
        if n_movs == 0:
            partial_parse = True
            if not section_found:
                no_movements_reason = (
                    "No se encontró la sección “Detalle de Movimientos” (o un bloque similar). "
                    "Si tu banco usa otro formato, intenta con la hoja RAW."
                )
            else:
                no_movements_reason = (
                    "Se detectó texto/fechas, pero no pudimos identificar correctamente montos/columnas. "
                    "Revisa la hoja RAW."
                )
            partial_reason = no_movements_reason
        else:
            # parcial si vimos muchas líneas candidatas pero pocas filas parseadas
            if movement_candidate_lines > max(10, int(n_movs * 2.0)) or blank_desc_lines > max(10, int(n_movs * 1.0)):
                partial_parse = True
                partial_reason = (
                    "Detectamos texto y algunos movimientos, pero el parse fue parcial. "
                    "Si ves movimientos partidos o faltantes, usa la hoja RAW."
                )
    elif not has_text:
        no_movements_reason = (
            "No se detectó texto seleccionable en el PDF. Probablemente es un escaneo; "
            "para eso se necesitará OCR (v2)."
        )

    def _top(items: list[dict], key: str, topn: int = 8) -> list[tuple[str, float]]:
        agg: dict[str, float] = {}
        for it in items:
            k = (it.get(key) or "").strip() or "—"
            v = float(it.get("monto") or 0)
            agg[k] = agg.get(k, 0.0) + v
        return sorted(agg.items(), key=lambda x: x[1], reverse=True)[:topn]

    top_cats = _top(gastos, "categoria", 10)
    top_cps = _top([g for g in gastos if (g.get("contraparte_hint") or "").strip()], "contraparte_hint", 10)

    wb = Workbook()
    # remover sheet default
    wb.remove(wb.active)

    # Movimientos
    rows_mov = [
        [
            m.get("movimiento_id", ""),
            m.get("issuer_id", ""),
            m.get("bank_name", ""),
            m.get("account_last4", ""),
            m.get("period_start", ""),
            m.get("period_end", ""),
            m.get("fecha", ""),
            m.get("descripcion_raw", ""),
            m.get("descripcion_norm", ""),
            m.get("referencia", ""),
            m.get("tipo", ""),
            m.get("monto", ""),
            m.get("moneda", "MXN"),
            m.get("saldo", ""),
            m.get("categoria", ""),
            m.get("subcategoria", ""),
            m.get("metodo_pago_hint", ""),
            m.get("contraparte_hint", ""),
            m.get("es_comision_bancaria", 0),
            m.get("es_impuesto_bancario", 0),
            m.get("posible_facturable", 0),
            "",
            "",
            m.get("match_status", "PENDIENTE"),
            m.get("parse_confidence", ""),
        ]
        for m in movimientos
    ]
    ws_mov = wb.create_sheet("Movimientos")
    _write_table(ws_mov, HEAD_MOV, rows_mov, money_cols=[12, 14])

    # Gastos
    ws_g = wb.create_sheet("Gastos")
    gastos_rows = [r for r in rows_mov if r[10] == "GASTO"]
    _write_table(ws_g, HEAD_MOV, gastos_rows, money_cols=[12, 14])
    if gastos_rows:
        ws_g.append([""] * (len(HEAD_MOV)))
        ws_g.append(["TOTAL", "", "", "", "", "", "", "", "", "", "", total_gastos, "MXN", "", "", "", "", "", "", "", "", "", "", ""])
        ws_g.cell(row=ws_g.max_row, column=1).font = Font(bold=True)
        ws_g.cell(row=ws_g.max_row, column=12).number_format = '"$"#,##0.00'

    # Ingresos
    ws_i = wb.create_sheet("Ingresos")
    ingresos_rows = [r for r in rows_mov if r[10] == "INGRESO"]
    _write_table(ws_i, HEAD_MOV, ingresos_rows, money_cols=[12, 14])
    if ingresos_rows:
        ws_i.append([""] * (len(HEAD_MOV)))
        ws_i.append(["TOTAL", "", "", "", "", "", "", "", "", "", "", total_ingresos, "MXN", "", "", "", "", "", "", "", "", "", "", ""])
        ws_i.cell(row=ws_i.max_row, column=1).font = Font(bold=True)
        ws_i.cell(row=ws_i.max_row, column=12).number_format = '"$"#,##0.00'

    # Resumen
    ws_r = wb.create_sheet("Resumen")
    ws_r.append(["campo", "valor"])
    ws_r["A1"].font = Font(bold=True)
    ws_r["B1"].font = Font(bold=True)
    ws_r.append(["period_start", period_start or ""])
    ws_r.append(["period_end", period_end or ""])
    ws_r.append(["total_ingresos", total_ingresos])
    ws_r.append(["total_gastos", total_gastos])
    ws_r.append(["neto", neto])
    ws_r.append(["#movimientos", n_movs])
    ws_r.append(["comisiones_bancarias_total", total_comisiones])
    for r in range(2, ws_r.max_row + 1):
        if ws_r.cell(row=r, column=2).value and isinstance(ws_r.cell(row=r, column=2).value, (int, float)):
            if ws_r.cell(row=r, column=1).value in ("total_ingresos", "total_gastos", "neto", "comisiones_bancarias_total"):
                ws_r.cell(row=r, column=2).number_format = '"$"#,##0.00'
    ws_r.freeze_panes = "A2"
    ws_r.column_dimensions["A"].width = 30
    ws_r.column_dimensions["B"].width = 22
    ws_r.append([])
    ws_r.append(["Top categorías de gasto", "monto", "%"])
    ws_r["A" + str(ws_r.max_row)].font = Font(bold=True)
    ws_r["B" + str(ws_r.max_row)].font = Font(bold=True)
    ws_r["C" + str(ws_r.max_row)].font = Font(bold=True)
    for k, v in top_cats:
        pct = (v / total_gastos) if total_gastos > 0 else 0.0
        ws_r.append([k, v, pct])
        ws_r.cell(row=ws_r.max_row, column=2).number_format = '"$"#,##0.00'
        ws_r.cell(row=ws_r.max_row, column=3).number_format = "0.0%"
    ws_r.append([])
    ws_r.append(["Top contrapartes por gasto", "monto", "%"])
    ws_r["A" + str(ws_r.max_row)].font = Font(bold=True)
    ws_r["B" + str(ws_r.max_row)].font = Font(bold=True)
    ws_r["C" + str(ws_r.max_row)].font = Font(bold=True)
    for k, v in top_cps:
        pct = (v / total_gastos) if total_gastos > 0 else 0.0
        ws_r.append([k, v, pct])
        ws_r.cell(row=ws_r.max_row, column=2).number_format = '"$"#,##0.00'
        ws_r.cell(row=ws_r.max_row, column=3).number_format = "0.0%"

    # Conciliacion_CFDI
    ws_c = wb.create_sheet("Conciliacion_CFDI")
    _write_table(ws_c, HEAD_C, concilia_rows, money_cols=[3, 8])

    # Gastos_sin_factura
    ws_gsf = wb.create_sheet("Gastos_sin_factura")
    _write_table(ws_gsf, HEAD_GSF, gastos_sin_factura_rows, money_cols=[3])

    # RAW (siempre)
    ws_raw = wb.create_sheet("RAW")
    raw_table = [[r["Page"], r["Line"], r["Text"]] for r in raw_rows]
    _write_table(ws_raw, ["page", "line", "text"], raw_table, money_cols=[])

    wb.save(xlsx_path_abs)

    return {
        "rows": len(movimientos),
        "raw_lines": len(raw_rows),
        "mode": mode,
        "bank_name": bank_name,
        "account_last4": account_last4,
        "period_start": period_start,
        "period_end": period_end,
        "cfdis_loaded": len(cfdis) if cfdis else 0,
        "processed_count": int(n_movs),
        "total_ingresos": float(total_ingresos),
        "total_gastos": float(total_gastos),
        "sin_factura_count": int(len(gastos_sin_factura_rows)),
        "low_confidence_count": int(low_confidence_count),
        "has_text": bool(has_text),
        "section_found": bool(section_found),
        "date_lines": int(date_lines),
        "movement_candidate_lines": int(movement_candidate_lines),
        "parsed_movement_lines": int(parsed_movement_lines),
        "partial_parse": bool(partial_parse),
        "partial_reason": partial_reason,
        "no_movements_reason": no_movements_reason,
    }


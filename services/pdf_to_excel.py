import hashlib
import os
import re
from dataclasses import dataclass
from typing import Optional, Iterable, Any


_DATE_PATTERNS = [
    re.compile(r"^(?P<d>\d{2})[\/\-](?P<m>\d{2})[\/\-](?P<y>\d{4})\b"),
    re.compile(r"^(?P<y>\d{4})[\/\-](?P<m>\d{2})[\/\-](?P<d>\d{2})\b"),
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


def _detect_date(line: str) -> Optional[str]:
    s = (line or "").strip()
    for pat in _DATE_PATTERNS:
        m = pat.match(s)
        if m:
            d = m.groupdict()
            try:
                if "y" in d and len(d["y"]) == 4:
                    y = d["y"]
                    mth = d["m"]
                    day = d["d"]
                    return f"{y}-{mth}-{day}"
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
    t = t.replace("$", "").replace(",", "").replace(" ", "")
    if t.startswith("-"):
        neg = True
        t = t[1:]
    # permitir 1234.56 o 1234
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


@dataclass
class ConvertMeta:
    rows: int
    raw_lines: int
    mode: str  # 'parsed' | 'raw'


def convert_pdf_to_xlsx(pdf_path_abs: str, xlsx_path_abs: str) -> dict[str, Any]:
    """
    Convierte un PDF de estado de cuenta a Excel.
    - Intenta heurística simple (fecha + montos).
    - Siempre genera un XLSX válido.
    - Si no detecta estructura, genera hoja RAW con líneas.
    """
    import pdfplumber  # lazy import (dependencia opcional hasta instalar)
    import pandas as pd

    if not os.path.isfile(pdf_path_abs):
        raise FileNotFoundError("PDF no encontrado")

    all_lines: list[str] = []
    parsed_rows: list[dict[str, Any]] = []

    with pdfplumber.open(pdf_path_abs) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if (ln or "").strip()]
            all_lines.extend(lines)

            for ln in lines:
                dt = _detect_date(ln)
                if not dt:
                    continue
                cols = _split_columns(ln)
                if not cols:
                    continue

                # quitar la fecha del primer col si viene pegada
                first = cols[0]
                if first.startswith(dt.replace("-", "/")) or first.startswith(dt.replace("-", "-")):
                    pass

                # buscar montos desde el final
                amounts: list[float] = []
                for tok in reversed(cols):
                    a = _parse_amount(tok)
                    if a is None:
                        break
                    amounts.append(a)
                amounts = list(reversed(amounts))

                # armar campos
                fecha = dt
                cargo = None
                abono = None
                saldo = None
                referencia = ""

                if len(amounts) >= 3:
                    cargo = amounts[-3]
                    abono = amounts[-2]
                    saldo = amounts[-1]
                elif len(amounts) == 2:
                    cargo = amounts[-2]
                    saldo = amounts[-1]
                elif len(amounts) == 1:
                    saldo = amounts[-1]

                # descripción = todo lo que no sean montos (y sin la fecha al inicio)
                desc_parts: list[str] = []
                for c in cols:
                    if _parse_amount(c) is not None:
                        continue
                    # remover fecha del primer token si viene como token aislado
                    if re.match(r"^\d{2}[\/\-]\d{2}[\/\-]\d{4}$", c) or re.match(r"^\d{4}[\/\-]\d{2}[\/\-]\d{2}$", c):
                        continue
                    desc_parts.append(c)
                descripcion = " ".join(desc_parts).strip()

                if not descripcion:
                    # si no quedó descripción, guardar como RAW
                    continue

                parsed_rows.append(
                    {
                        "Fecha": fecha,
                        "Descripción": descripcion,
                        "Referencia": referencia,
                        "Cargo": cargo,
                        "Abono": abono,
                        "Saldo": saldo,
                    }
                )

    ensure_parent_dir(xlsx_path_abs)
    mode = "parsed" if parsed_rows else "raw"

    with pd.ExcelWriter(xlsx_path_abs, engine="openpyxl") as writer:
        if parsed_rows:
            df = pd.DataFrame(parsed_rows, columns=["Fecha", "Descripción", "Referencia", "Cargo", "Abono", "Saldo"])
            df.to_excel(writer, sheet_name="Movimientos", index=False)
        raw_df = pd.DataFrame([{"Linea": ln} for ln in all_lines], columns=["Linea"])
        raw_df.to_excel(writer, sheet_name="RAW", index=False)

    return {
        "rows": len(parsed_rows),
        "raw_lines": len(all_lines),
        "mode": mode,
    }


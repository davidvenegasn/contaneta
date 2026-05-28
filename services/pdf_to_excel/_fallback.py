"""Fallback line-by-line parser for bank statements without structured sections."""
import re
from typing import Any

from services.pdf_to_excel._helpers import (
    _clasificar,
    _contraparte_hint,
    _detect_date,
    _extract_amounts_from_end,
    _extract_referencia,
    _metodo_pago_hint,
    _norm_text,
    _split_columns,
)


def fallback_simple_parse(raw_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fallback parser for banks without structured DETALLE section."""
    simple_txs: list[dict[str, Any]] = []
    rfc_re = re.compile(r"\b([A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})\b")
    rast_re = re.compile(r"\b(?:CVE\\s*RAST(?:REO)?)\s*[:=\-]?\s*([A-Z0-9]{8,40})\b")
    for rr in raw_rows:
        ln = str(rr.get("Text") or "").strip()
        dt = _detect_date(ln)
        if not dt:
            continue
        rest = re.sub(r"^\s*\d{2}[\/\-]\d{2}[\/\-]\d{2,4}\s+", "", ln.strip())
        rest = re.sub(r"^\s*\d{4}[\/\-]\d{2}[\/\-]\d{2}\s+", "", rest)
        rest = re.sub(r"^\s*\d{2}[\/\-\s][A-Za-zÁÉÍÓÚÜÑ\.]{3,}[\/\-\s]\d{2,4}\s+", "", rest)
        cols = _split_columns(rest)
        rest_for_amounts = " ".join(cols) if (cols and len(cols) >= 2) else rest
        desc_wo_amounts, amounts = _extract_amounts_from_end(rest_for_amounts, max_amounts=3)
        desc_raw = (desc_wo_amounts or "").strip()
        if not desc_raw:
            continue
        cargo = None
        abono = None
        saldo = None
        if len(amounts) >= 3:
            cargo, abono, saldo = amounts[-3], amounts[-2], amounts[-1]
        elif len(amounts) == 2:
            cargo, saldo = amounts[-2], amounts[-1]
        elif len(amounts) == 1:
            cargo = amounts[-1]
        desc_norm = _norm_text(desc_raw)
        categoria, _, _, _, _ = _clasificar(desc_norm)
        contraparte = _contraparte_hint(desc_norm)
        metodo_raw = _metodo_pago_hint(desc_norm)
        if metodo_raw in ("SPEI",):
            metodo_hint = "SPEI"
        elif metodo_raw in ("TARJETA", "TPV"):
            metodo_hint = "TARJETA"
        elif metodo_raw in ("EFECTIVO",):
            metodo_hint = "EFECTIVO"
        else:
            metodo_hint = "OTRO"
        tipo = "DESCONOCIDO"
        deposito = abs(float(abono)) if (abono is not None and float(abono or 0) > 0) else None
        retiro = abs(float(cargo)) if (cargo is not None and float(cargo or 0) > 0) else None
        if deposito:
            tipo = "INGRESO"
        elif retiro:
            tipo = "GASTO"
        ref = _extract_referencia(desc_norm)
        rast = (rast_re.search(desc_norm).group(1) if rast_re.search(desc_norm) else "")
        rfc = (rfc_re.search(desc_norm).group(1) if rfc_re.search(desc_norm) else "")
        score = 35
        if deposito or retiro:
            score += 25
        if saldo is not None:
            score += 15
        if dt:
            score += 15
        score = min(100, score)
        pg = int(rr.get("Page") or 0)
        simple_txs.append(
            {
                "fecha": dt,
                "descripcion_full": " ".join(desc_raw.split()),
                "descripcion_norm": desc_norm,
                "deposito": deposito,
                "retiro": retiro,
                "saldo": float(saldo) if saldo is not None else None,
                "tipo": tipo,
                "categoria": categoria,
                "contraparte_hint": contraparte,
                "metodo_hint": metodo_hint,
                "referencia": ref,
                "cve_rastreo": rast,
                "rfc_encontrado": rfc,
                "confidence_score": score,
                "source_page_first": pg,
                "source_page_last": pg,
            }
        )
    metrics = {
        "sections_detected": 0,
        "transactions_grouped": len(simple_txs),
        "movements_count": sum(1 for t in simple_txs if (t.get("deposito") or 0) or (t.get("retiro") or 0)),
        "sin_parse_count": 0,
        "saldo_count": sum(1 for t in simple_txs if isinstance(t.get("saldo"), (int, float))),
        "rfc_count": sum(1 for t in simple_txs if (t.get("rfc_encontrado") or "").strip()),
        "rastreo_count": sum(1 for t in simple_txs if (t.get("cve_rastreo") or "").strip()),
        "avg_confidence": (sum(float(t.get("confidence_score") or 0) for t in simple_txs) / len(simple_txs)) if simple_txs else 0.0,
        "low_confidence_count": sum(1 for t in simple_txs if int(t.get("confidence_score") or 0) < 60),
        "total_ingresos": sum(float(t.get("deposito") or 0) for t in simple_txs),
        "total_gastos": sum(float(t.get("retiro") or 0) for t in simple_txs),
    }
    return simple_txs, metrics

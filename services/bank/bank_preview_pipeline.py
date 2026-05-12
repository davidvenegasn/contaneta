"""
Pipeline de preview por archivo: detectar banco → parsear → normalizar → clasificar.
Un archivo que falla no tumba el resto; errores por archivo.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from services.bank.bank_classifier import classify_bank_preview_movement, extract_spei_counterparty_for_display
from services.bank.bank_detection import detect_bank_from_pdf_text_pages, extract_account_holder_from_pdf_text
from services.bank.bank_preview_models import make_preview_movement, normalize_preview_movement
from services.pdf_to_excel import detect_statement_period_from_text

logger = logging.getLogger(__name__)


def _infer_account_holder_from_spei_movements(
    txs_grouped: list[list[dict]],
    norm_text_fn,
) -> Optional[str]:
    """
    Si el PDF no trae el nombre del titular, lo inferimos del primer movimiento SPEI
    que diga "SPEI A [nombre]" o "SPEI DE [nombre]" (ese nombre es el dueño del estado de cuenta).
    """
    for g in txs_grouped[:50]:
        raw_lines = [str(r.get("Text") or "").strip() for r in g if (r.get("Text") or "").strip()]
        joined = " ".join(raw_lines).strip()
        norm = norm_text_fn(joined)
        if "SPEI" not in norm and "SEPEI" not in norm:
            continue
        # SPEI A nombre (gasto a cuenta propia)
        m = re.search(r"(?:SPEI|SEPEI)\s+A\s+([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            name = " ".join(m.group(1).split()).strip()
            if len(name) >= 4:
                return name[:80]
        # SPEI RECIBIDO DE nombre / SPEI DE nombre (ingreso desde cuenta propia)
        m = re.search(r"SPEI\s+RECIBIDO\s+(?:DE\s+)?([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            name = " ".join(m.group(1).split()).strip()
            if len(name) >= 4:
                return name[:80]
        m = re.search(r"(?:SPEI|SEPEI)\s+DE\s+([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            name = " ".join(m.group(1).split()).strip()
            if len(name) >= 4:
                return name[:80]
    return None


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> tuple[list[dict[str, Any]], list[str], Optional[str]]:
    """
    Extrae texto por página. Returns (raw_rows, pages_text, error_msg).
    raw_rows: list of {Page, Line, Text} para compatibilidad con bank_statement_parser.
    """
    try:
        import pdfplumber
    except ModuleNotFoundError:
        return [], [], "No se pudo cargar el lector de PDF (pdfplumber)."
    if not pdf_bytes or len(pdf_bytes) < 100:
        return [], [], "El archivo PDF está vacío o es demasiado pequeño."
    try:
        import io
        raw_rows: list[dict[str, Any]] = []
        pages_text: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                pages_text.append(text)
                for li, ln in enumerate((text or "").splitlines(), start=1):
                    ln = (ln or "").strip()
                    if ln:
                        raw_rows.append({"Page": page_idx, "Line": li, "Text": ln})
        return raw_rows, pages_text, None
    except Exception as e:
        logger.exception("bank_preview_pipeline: error extrayendo texto PDF")
        return [], [], "No se pudo extraer texto del PDF."


def _parse_banorte(raw_rows: list[dict], pages_text: list[str], file_name: str, file_index: int) -> tuple[list[dict], dict, Optional[str]]:
    """
    Usa el parser Banorte existente (bank_statement_parser + bank_parse_preview._build_movement).
    Returns (movements_preview_format, file_summary, error).
    """
    try:
        from services.bank.bank_classifier_presets import PRESET_CONSERVATIVE, get_preset
        from services.bank.bank_parse_preview import _build_movement
        from services.bank.bank_statement_parser import (
            _parse_banorte_date_from_start,
            build_transactions,
            extract_money_candidates,
            locate_sections,
            norm_text,
        )
    except ImportError as e:
        return [], {}, f"Error importando módulos: {e}"
    sections = locate_sections(raw_rows)
    txs_grouped: list[list[dict]] = []
    for sec in sections:
        start = int(sec["start_idx"])
        end = int(sec["end_idx"])
        txs_grouped.extend(build_transactions(raw_rows[start : end + 1]))
    if not txs_grouped:
        return [], {"movements_count": 0, "bank_name": "BANORTE"}, "No se encontraron movimientos parseables."
    account_holder_name, account_holder_rfc = extract_account_holder_from_pdf_text(pages_text)

    # Si el PDF no trae titular, inferirlo del primer movimiento SPEI que diga "SPEI A [nombre]" o "SPEI DE [nombre]"
    if not account_holder_name:
        account_holder_name = _infer_account_holder_from_spei_movements(txs_grouped, norm_text)

    movements: list[dict] = []
    prev_saldo: Optional[float] = None
    preset_dict = get_preset(PRESET_CONSERVATIVE)
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
        md = mov.to_dict()
        ext = md.get("extracted") or {}
        preview_mov = make_preview_movement(
            source_file_name=file_name,
            source_file_index=file_index,
            bank_name="BANORTE",
            page_number=int(g[0].get("Page") or 0) if g else None,
            raw_text_original=joined_raw,
            raw_text_normalized=joined_norm,
            fecha=date_str or None,
            fecha_original=date_str or "",
            tipo_movimiento="INGRESO" if direction == "IN" else ("GASTO" if direction == "OUT" else "INFO"),
            monto_deposito=deposit,
            monto_retiro=withdraw,
            saldo=balance,
            canal=md.get("method") or "OTRO",
            categoria_sugerida=md.get("category") or "OTROS",
            subcategoria_sugerida="",
            contraparte_nombre=(ext.get("counterparty") or ""),
            referencia=(ext.get("reference") or ""),
            clabe_detectada=(ext.get("clabe") or ""),
            cve_rastreo=(ext.get("tracking") or ""),
            rfc_detectado=(ext.get("rfc") or ""),
            concepto_resumen=md.get("description_short") or "",
            es_movimiento_financiero=(md.get("bucket") == "FINANCIERO" or md.get("category") == "FINANCIERO_PAGO_TARJETA"),
            es_pago_tarjeta_probable=("TARJETA" in (md.get("method") or "") or "PAGO CONCENTRACION" in joined_norm),
            confianza_clasificacion=int(md.get("confidence") or 0),
            warnings=md.get("warnings") or [],
            parser_version="1",
            parser_bank_profile="banorte_v1",
        )
        preview_mov["idx"] = len(movements) + 1
        preview_mov = classify_bank_preview_movement(
            preview_mov,
            account_holder_name=account_holder_name,
            account_holder_rfc=account_holder_rfc,
        )
        # Si la contraparte no se extrajo por BENEF/DEL CLIENTE, usar "SPEI A NOMBRE" / "SPEI DE NOMBRE"
        if not (preview_mov.get("contraparte_nombre") or "").strip() and ("SPEI" in joined_norm or "SEPEI" in joined_norm):
            is_income = "SPEI RECIBIDO" in joined_norm or "DEPOSITO" in joined_norm or "ABONO" in joined_norm
            cp = extract_spei_counterparty_for_display(joined_raw, is_income=is_income)
            if cp:
                preview_mov["contraparte_nombre"] = cp
        movements.append(preview_mov)
    total_dep = sum(m.get("monto_deposito") or 0 for m in movements)
    total_ret = sum(m.get("monto_retiro") or 0 for m in movements)
    # Periodo explícito del encabezado (ej. "01/01/2026 al 31/01/2026"); no usar fechas de movimientos como "Saldo anterior"
    full_text = " ".join(p or "" for p in pages_text)
    period_start, period_end = detect_statement_period_from_text(full_text)
    file_summary = {
        "file_name": file_name,
        "bank_name": "BANORTE",
        "movements_count": len(movements),
        "total_deposito": round(total_dep, 2),
        "total_retiro": round(total_ret, 2),
        "profile": "banorte_v1",
        "account_holder_name": account_holder_name,
        "account_holder_rfc": account_holder_rfc,
        "period_start": period_start or None,
        "period_end": period_end or None,
    }
    return movements, file_summary, None


def parse_bank_statement_preview(
    pdf_bytes: bytes,
    file_name: str = "documento.pdf",
    file_index: int = 0,
) -> dict[str, Any]:
    """
    Procesa un PDF en memoria: extrae texto, detecta banco, parsea, devuelve movimientos + resumen por archivo.
    No lanza excepciones; errores se devuelven en file_error.
    Returns:
      movements: list[dict] (formato preview)
      file_summary: dict
      file_error: str | None
      file_warnings: list[str]
    """
    file_warnings: list[str] = []
    raw_rows, pages_text, extract_error = _extract_text_from_pdf_bytes(pdf_bytes)
    if extract_error:
        return {
            "movements": [],
            "file_summary": {"file_name": file_name, "bank_name": "", "movements_count": 0, "error": extract_error},
            "file_error": extract_error,
            "file_warnings": file_warnings,
        }
    detection = detect_bank_from_pdf_text_pages(pages_text)
    bank_name = detection.get("bank_name") or "DESCONOCIDO"
    profile = detection.get("profile") or "generic_v1"
    if bank_name == "DESCONOCIDO":
        file_warnings.append("Banco no reconocido (parser genérico).")
    if profile == "banorte_v1":
        movements, file_summary, file_error = _parse_banorte(raw_rows, pages_text, file_name, file_index)
        if file_error:
            return {
                "movements": [],
                "file_summary": {"file_name": file_name, "bank_name": bank_name, "movements_count": 0, "error": file_error},
                "file_error": file_error,
                "file_warnings": file_warnings,
            }
        for m in movements:
            m["bank_name"] = bank_name
        return {
            "movements": movements,
            "file_summary": file_summary,
            "file_error": None,
            "file_warnings": file_warnings,
        }
    # Fallback genérico: intentar mismo parser Banorte por si acaso (muchos formatos se parecen)
    movements, file_summary, file_error = _parse_banorte(raw_rows, pages_text, file_name, file_index)
    if file_error and not movements:
        file_error = "No se pudo reconocer el formato del estado de cuenta."
        return {
            "movements": [],
            "file_summary": {"file_name": file_name, "bank_name": bank_name, "movements_count": 0, "error": file_error},
            "file_error": file_error,
            "file_warnings": file_warnings,
        }
    for m in movements:
        m["bank_name"] = bank_name
    if file_summary:
        file_summary["bank_name"] = bank_name
        file_summary["profile"] = profile
    return {
        "movements": movements,
        "file_summary": file_summary or {"file_name": file_name, "bank_name": bank_name, "movements_count": len(movements)},
        "file_error": None,
        "file_warnings": file_warnings,
    }

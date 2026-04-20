"""
Modelo interno para preview de movimientos bancarios (sin DB).
Estructura estandarizada en memoria para el flujo multi-PDF.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional


def _stable_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def compute_dedupe_fingerprint(mov: dict[str, Any]) -> str:
    """Fingerprint para detectar duplicados: fecha + monto + concepto + cve.
    No incluye source_file_name ni saldo (depende de posición) para que funcione cross-file."""
    f = mov.get("fecha") or ""
    dep = mov.get("monto_deposito") or 0
    ret = mov.get("monto_retiro") or 0
    concept = (mov.get("concepto_resumen") or "")[:200]
    cve = (mov.get("cve_rastreo") or "")[:64]
    payload = f"{f}|{dep}|{ret}|{concept}|{cve}"
    return _stable_hash(payload)


def make_preview_movement(
    *,
    source_file_name: str = "",
    source_file_index: int = 0,
    bank_name: str = "",
    account_hint: str = "",
    statement_period_start: Optional[str] = None,
    statement_period_end: Optional[str] = None,
    page_number: Optional[int] = None,
    raw_text_original: str = "",
    raw_text_normalized: str = "",
    fecha: Optional[str] = None,
    fecha_original: str = "",
    tipo_movimiento: str = "INFO",
    monto_deposito: float = 0.0,
    monto_retiro: float = 0.0,
    saldo: Optional[float] = None,
    moneda: str = "MXN",
    canal: str = "OTRO",
    categoria_sugerida: str = "OTROS",
    subcategoria_sugerida: str = "",
    contraparte_nombre: str = "",
    contraparte_banco: str = "",
    referencia: str = "",
    clabe_detectada: str = "",
    cve_rastreo: str = "",
    rfc_detectado: str = "",
    folio_detectado: str = "",
    concepto_detectado: str = "",
    concepto_resumen: str = "",
    es_movimiento_financiero: bool = False,
    es_transferencia_propia_probable: bool = False,
    es_pago_tarjeta_probable: bool = False,
    impacta_contabilidad: bool = True,
    requiere_revision: bool = False,
    confianza_clasificacion: int = 0,
    warnings: Optional[list[str]] = None,
    parser_version: str = "1",
    parser_bank_profile: str = "generic_v1",
    dedupe_fingerprint: str = "",
    posible_duplicado: bool = False,
    preview_id: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Construye un dict de movimiento preview. preview_id y dedupe_fingerprint se pueden calcular después."""
    mov = {
        "source_file_name": source_file_name,
        "source_file_index": source_file_index,
        "bank_name": bank_name,
        "account_hint": account_hint,
        "statement_period_start": statement_period_start,
        "statement_period_end": statement_period_end,
        "page_number": page_number,
        "raw_text_original": raw_text_original or "",
        "raw_text_normalized": raw_text_normalized or "",
        "fecha": fecha,
        "fecha_original": fecha_original or "",
        "tipo_movimiento": tipo_movimiento or "INFO",
        "monto_deposito": float(monto_deposito) if monto_deposito is not None else 0.0,
        "monto_retiro": float(monto_retiro) if monto_retiro is not None else 0.0,
        "saldo": float(saldo) if saldo is not None else None,
        "moneda": moneda or "MXN",
        "canal": canal or "OTRO",
        "categoria_sugerida": categoria_sugerida or "OTROS",
        "subcategoria_sugerida": subcategoria_sugerida or "",
        "contraparte_nombre": contraparte_nombre or "",
        "contraparte_banco": contraparte_banco or "",
        "referencia": referencia or "",
        "clabe_detectada": clabe_detectada or "",
        "cve_rastreo": cve_rastreo or "",
        "rfc_detectado": rfc_detectado or "",
        "folio_detectado": folio_detectado or "",
        "concepto_detectado": concepto_detectado or "",
        "concepto_resumen": concepto_resumen or "",
        "es_movimiento_financiero": bool(es_movimiento_financiero),
        "es_transferencia_propia_probable": bool(es_transferencia_propia_probable),
        "es_pago_tarjeta_probable": bool(es_pago_tarjeta_probable),
        "impacta_contabilidad": bool(impacta_contabilidad),
        "requiere_revision": bool(requiere_revision),
        "confianza_clasificacion": max(0, min(100, int(confianza_clasificacion or 0))),
        "warnings": list(warnings) if warnings is not None else [],
        "parser_version": parser_version or "1",
        "parser_bank_profile": parser_bank_profile or "generic_v1",
        "dedupe_fingerprint": dedupe_fingerprint or "",
        "posible_duplicado": bool(posible_duplicado),
        "preview_id": preview_id or "",
    }
    if not mov["dedupe_fingerprint"]:
        mov["dedupe_fingerprint"] = compute_dedupe_fingerprint(mov)
    if not mov["preview_id"]:
        mov["preview_id"] = _stable_hash(mov["dedupe_fingerprint"] + "|" + str(source_file_index))
    return mov


def normalize_preview_movement(mov: dict[str, Any]) -> dict[str, Any]:
    """
    Asegura que un movimiento preview tenga todos los campos y tipos correctos.
    Idempotente; no modifica lógica de negocio.
    """
    out = make_preview_movement(
        source_file_name=mov.get("source_file_name", ""),
        source_file_index=int(mov.get("source_file_index") or 0),
        bank_name=mov.get("bank_name") or "",
        account_hint=mov.get("account_hint") or "",
        statement_period_start=mov.get("statement_period_start"),
        statement_period_end=mov.get("statement_period_end"),
        page_number=mov.get("page_number"),
        raw_text_original=mov.get("raw_text_original") or "",
        raw_text_normalized=mov.get("raw_text_normalized") or "",
        fecha=mov.get("fecha"),
        fecha_original=mov.get("fecha_original") or "",
        tipo_movimiento=mov.get("tipo_movimiento") or mov.get("direction") or "INFO",
        monto_deposito=mov.get("monto_deposito") if "monto_deposito" in mov else mov.get("deposit", 0),
        monto_retiro=mov.get("monto_retiro") if "monto_retiro" in mov else mov.get("withdraw", 0),
        saldo=mov.get("saldo") if mov.get("saldo") is not None else mov.get("balance"),
        moneda=mov.get("moneda") or "MXN",
        canal=mov.get("canal") or mov.get("method") or "OTRO",
        categoria_sugerida=mov.get("categoria_sugerida") or mov.get("category") or "OTROS",
        subcategoria_sugerida=mov.get("subcategoria_sugerida") or "",
        contraparte_nombre=mov.get("contraparte_nombre") or (mov.get("extracted") or {}).get("counterparty") or "",
        contraparte_banco=mov.get("contraparte_banco") or "",
        referencia=mov.get("referencia") or (mov.get("extracted") or {}).get("reference") or "",
        clabe_detectada=mov.get("clabe_detectada") or (mov.get("extracted") or {}).get("clabe") or "",
        cve_rastreo=mov.get("cve_rastreo") or (mov.get("extracted") or {}).get("tracking") or "",
        rfc_detectado=mov.get("rfc_detectado") or (mov.get("extracted") or {}).get("rfc") or "",
        folio_detectado=mov.get("folio_detectado") or "",
        concepto_detectado=mov.get("concepto_detectado") or "",
        concepto_resumen=mov.get("concepto_resumen") or mov.get("description_short") or "",
        es_movimiento_financiero=bool(mov.get("es_movimiento_financiero", False)),
        es_transferencia_propia_probable=bool(mov.get("es_transferencia_propia_probable", False)),
        es_pago_tarjeta_probable=bool(mov.get("es_pago_tarjeta_probable", False)),
        impacta_contabilidad=bool(mov.get("impacta_contabilidad", True)),
        requiere_revision=bool(mov.get("requiere_revision", False)),
        confianza_clasificacion=mov.get("confianza_clasificacion") if "confianza_clasificacion" in mov else mov.get("confidence", 0),
        warnings=mov.get("warnings"),
        parser_version=mov.get("parser_version") or "1",
        parser_bank_profile=mov.get("parser_bank_profile") or "generic_v1",
        dedupe_fingerprint=mov.get("dedupe_fingerprint", ""),
        posible_duplicado=bool(mov.get("posible_duplicado", False)),
        preview_id=mov.get("preview_id", ""),
    )
    return out


def to_ui_preview_row(mov: dict[str, Any]) -> dict[str, Any]:
    """
    Solo campos simples para la lista (no técnicos).
    Campos visibles: Fecha, Banco/Archivo, Concepto, Tipo, Categoría, Monto, Estado (chips).
    """
    tipo = (mov.get("tipo_movimiento") or "INFO").upper()
    dep = float(mov.get("monto_deposito") or 0)
    ret = float(mov.get("monto_retiro") or 0)
    monto = dep if tipo == "INGRESO" else (-ret if tipo == "GASTO" else None)
    return {
        "preview_id": mov.get("preview_id"),
        "fecha": mov.get("fecha"),
        "bank_or_file": mov.get("bank_name") or mov.get("source_file_name") or "—",
        "source_file_name": mov.get("source_file_name"),
        "concepto": mov.get("concepto_resumen") or "—",
        "tipo": "Ingreso" if tipo == "INGRESO" else ("Gasto" if tipo == "GASTO" else "Info"),
        "tipo_movimiento": tipo,
        "categoria": mov.get("categoria_sugerida") or "—",
        "monto": monto,
        "saldo": mov.get("saldo"),
        "es_financiero": bool(mov.get("es_movimiento_financiero")),
        "es_cuenta_propia": bool(mov.get("es_transferencia_propia_probable")),
        "requiere_revision": bool(mov.get("requiere_revision")),
        "posible_duplicado": bool(mov.get("posible_duplicado")),
        "confianza": mov.get("confianza_clasificacion"),
    }

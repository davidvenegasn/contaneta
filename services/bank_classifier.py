"""
Clasificador por reglas (IFs) para movimientos preview.
Asigna tipo_movimiento, canal, categoria_sugerida, flags y confianza.
Sin persistencia; solo en memoria.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

# Palabras que no cuentan como parte del nombre del titular
_STOP_WORDS_NAME = frozenset({"DEL", "LA", "DE", "LOS", "LAS", "CLIENTE", "BENEF", "BENEFICIARIO", "ORDENANTE", "Y", "E", "SA", "CV", "SAPI", "RFC", "REF", "CVE"})


def _normalize_name(s: str) -> str:
    """Normaliza para comparación: sin acentos, mayúsculas, un solo espacio."""
    if not s:
        return ""
    t = unicodedata.normalize("NFKD", (s or "").strip().upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _name_tokens(name: str) -> list[str]:
    """Tokens significativos del nombre (longitud >= 2, no stop words)."""
    n = _normalize_name(name)
    return [w for w in n.split() if len(w) >= 2 and w not in _STOP_WORDS_NAME]


def _names_match(account_holder: str, other_party: str) -> bool:
    """
    True si other_party corresponde al mismo titular que account_holder.
    Compara por subcadena normalizada o por al menos 2 tokens del titular presentes en other_party.
    """
    if not account_holder or not other_party:
        return False
    ah_norm = _normalize_name(account_holder)
    op_norm = _normalize_name(other_party)
    if ah_norm in op_norm or op_norm in ah_norm:
        return True
    ah_tokens = _name_tokens(account_holder)
    op_set = set(_name_tokens(other_party))
    if not ah_tokens:
        return False
    matches = sum(1 for t in ah_tokens if t in op_set)
    if matches >= 2:
        return True
    if matches >= 1 and len(ah_tokens) == 1 and len(ah_tokens[0]) >= 4:
        return True
    return False


def extract_spei_counterparty_for_display(raw: str, is_income: bool) -> Optional[str]:
    """
    Extrae el nombre de la contraparte SPEI para mostrar/uso en detección de cuenta propia.
    is_income=True → SPEI recibido (quien envía); False → SPEI enviado (beneficiario).
    """
    return _extract_spei_counterparty_from_text(raw, is_income=is_income)


def _extract_spei_counterparty_from_text(raw: str, is_income: bool) -> Optional[str]:
    """
    Extrae el nombre de la contraparte del movimiento SPEI desde el texto crudo del concepto.
    is_income=True → SPEI recibido (quien envía); is_income=False → SPEI enviado (quien recibe).
    Prioriza "SPEI A NOMBRE" y "SEPEI A NOMBRE" (tal como sale en el estado de cuenta).
    """
    if not raw:
        return None
    norm = _normalize_name(raw)
    # BENEF: / BENEFICIARIO: es común en ambos
    m = re.search(r"\bBENEF[:\s]+([^,\(\n]{4,50}?)(?:\s*,\s*|\s*\(|\s+REF|\s+CVE|$)", norm)
    if m:
        return " ".join(m.group(1).split()).strip() or None
    if is_income:
        # SPEI RECIBIDO DE X / DEL CLIENTE X
        m = re.search(r"SPEI\s+RECIBIDO\s+(?:DE\s+)?([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            return " ".join(m.group(1).split()).strip() or None
        m = re.search(r"(?:SPEI|SEPEI)\s+DE\s+([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            return " ".join(m.group(1).split()).strip() or None
        m = re.search(r"DEL\s+CLIENTE\s+([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|$)", norm)
        if m:
            return " ".join(m.group(1).split()).strip() or None
    else:
        # "SPEI A NOMBRE" y "SEPEI A NOMBRE" (lo que dice el usuario: en el concepto sale "spei a" + nombre)
        m = re.search(r"(?:SPEI|SEPEI)\s+A\s+([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            return " ".join(m.group(1).split()).strip() or None
        m = re.search(r"(?:SPEI|SEPEI)\s+PARA\s+([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            return " ".join(m.group(1).split()).strip() or None
        # COMPRA ORDEN DE PAGO SPEI A NOMBRE / SPEI NOMBRE (nombre justo después de SPEI)
        m = re.search(r"COMPRA\s+ORDEN\s+DE\s+PAGO\s+(?:SPEI|SEPEI)\s+(?:A\s+)?([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            return " ".join(m.group(1).split()).strip() or None
        m = re.search(r"ORDEN\s+DE\s+PAGO\s+(?:SPEI|SEPEI)\s+(?:A\s+)?([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d|$)", norm)
        if m:
            return " ".join(m.group(1).split()).strip() or None
        # SPEI seguido de nombre (sin "A") por si el banco no pone "A"
        m = re.search(r"(?:SPEI|SEPEI)\s+([A-Z0-9\s&Ñ]{4,50}?)(?:\s+REF|\s+CVE|\s+RFC|\d{2,}|$)", norm)
        if m:
            name = " ".join(m.group(1).split()).strip()
            if name and not name.startswith("RECIBIDO") and "ORDEN" not in name:
                return name[:50] or None
    return None


def _detect_own_transfer(
    mov: dict[str, Any],
    account_holder_name: Optional[str] = None,
    account_holder_rfc: Optional[str] = None,
) -> bool:
    """
    True si el movimiento SPEI es transferencia hacia/desde el mismo titular del estado de cuenta.
    - SPEI recibido DE (nombre del titular) → cuenta propia.
    - SPEI A / PARA (nombre del titular) → cuenta propia.
    Usa contraparte extraída, RFC o nombre extraído del texto del movimiento.
    """
    raw = (mov.get("raw_text_normalized") or mov.get("raw_text_original") or "").strip()
    if not raw:
        return False
    raw_upper = raw.upper()
    if "SPEI" not in raw_upper and "TRANSFERENCIA" not in raw_upper:
        return False

    rfc = (mov.get("rfc_detectado") or "").strip().upper()
    if account_holder_rfc and rfc and rfc == (account_holder_rfc or "").strip().upper():
        return True

    if not account_holder_name:
        return False

    contraparte = (mov.get("contraparte_nombre") or "").strip()
    if contraparte and _names_match(account_holder_name, contraparte):
        return True

    is_income = "SPEI RECIBIDO" in raw_upper or ("SPEI" in raw_upper and ("DEPOSITO" in raw_upper or "ABONO" in raw_upper))
    extracted = _extract_spei_counterparty_from_text(raw, is_income=is_income)
    if extracted and _names_match(account_holder_name, extracted):
        return True

    return False


def classify_bank_preview_movement(
    mov: dict[str, Any],
    account_holder_name: Optional[str] = None,
    account_holder_rfc: Optional[str] = None,
) -> dict[str, Any]:
    """
    Actualiza el movimiento con tipo_movimiento, canal, categoria_sugerida,
    es_movimiento_financiero, es_pago_tarjeta_probable, es_transferencia_propia_probable,
    impacta_contabilidad, requiere_revision, confianza_clasificacion y warnings.
    Devuelve el mismo dict actualizado.
    """
    raw = (mov.get("raw_text_normalized") or mov.get("raw_text_original") or "").upper()
    out = dict(mov)
    warnings = list(out.get("warnings") or [])
    conf = int(out.get("confianza_clasificacion") or 60)
    bank = (out.get("bank_name") or "").upper()
    if "SALDO ANTERIOR" in raw:
        out["tipo_movimiento"] = "INFO"
        out["canal"] = "OTRO"
        out["categoria_sugerida"] = "OTROS"
        out["es_movimiento_financiero"] = False
        out["confianza_clasificacion"] = min(100, conf + 20)
        out["impacta_contabilidad"] = False
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    if "SPEI RECIBIDO" in raw or ("SPEI" in raw and ("DEPOSITO" in raw or "ABONO" in raw)):
        out["tipo_movimiento"] = "INGRESO"
        out["canal"] = "SPEI"
        out["categoria_sugerida"] = "TRANSFERENCIAS"
        out["confianza_clasificacion"] = min(100, conf + 25)
        out["es_transferencia_propia_probable"] = _detect_own_transfer(out, account_holder_name, account_holder_rfc)
        out["impacta_contabilidad"] = not out.get("es_transferencia_propia_probable", False)
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    if "COMPRA ORDEN DE PAGO SPEI" in raw or ("SPEI" in raw and "CARGO" in raw):
        out["tipo_movimiento"] = "GASTO"
        out["canal"] = "SPEI"
        out["categoria_sugerida"] = "TRANSFERENCIAS"
        out["confianza_clasificacion"] = min(100, conf + 20)
        out["es_transferencia_propia_probable"] = _detect_own_transfer(out, account_holder_name, account_holder_rfc)
        out["impacta_contabilidad"] = not out.get("es_transferencia_propia_probable", False)
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    # Pago de tarjeta de crédito (no es gasto real: solo mueve dinero al plástico)
    if (
        ("CARGO POR PAGO CONCENTRACION" in raw and "TARJETA" in raw)
        or ("PAGO CONCENTRACION" in raw and ("TARJETA" in raw or "TDC" in raw))
        or ("PAGO DE TARJETA" in raw or "PAGO TARJETA" in raw or "PAGO A TARJETA" in raw)
    ):
        out["tipo_movimiento"] = "GASTO"
        out["canal"] = "TARJETA"
        out["categoria_sugerida"] = "TARJETAS_CREDITO"
        out["es_movimiento_financiero"] = True
        out["es_pago_tarjeta_probable"] = True
        out["confianza_clasificacion"] = min(100, 95)
        out["impacta_contabilidad"] = False
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    # Disposición de efectivo TDC (ingreso o cargo: movimiento financiero, no impacta)
    if (
        "ABONO POR DISPOSICION" in raw
        or ("CARGO" in raw and "DISPOSICION" in raw)
        or ("DISPOSICION" in raw and ("TDC" in raw or "TARJETA" in raw or "EFECTIVO" in raw))
    ):
        if "ABONO" in raw or "DEPOSITO" in raw:
            out["tipo_movimiento"] = "INGRESO"
        else:
            out["tipo_movimiento"] = "GASTO"
        out["canal"] = "TARJETA"
        out["categoria_sugerida"] = "MOVIMIENTO_FINANCIERO"
        out["es_movimiento_financiero"] = True
        out["confianza_clasificacion"] = min(100, 88)
        out["impacta_contabilidad"] = False
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    if "AMERICAN EXPRES" in raw or "AMERICAN EXPRESS" in raw:
        out["subcategoria_sugerida"] = "AMEX"
        if out.get("categoria_sugerida") == "OTROS":
            out["categoria_sugerida"] = "TARJETAS_CREDITO"
            out["es_pago_tarjeta_probable"] = True
        out["confianza_clasificacion"] = max(conf, 85)
        out["impacta_contabilidad"] = not out.get("es_movimiento_financiero", False)
        out["requiere_revision"] = int(out.get("confianza_clasificacion") or 0) < 60
        out["warnings"] = warnings
        return out
    if "OXXO" in raw:
        out["tipo_movimiento"] = "GASTO"
        out["canal"] = "OTRO"
        out["categoria_sugerida"] = "TIENDA_CONVENIENCIA"
        out["confianza_clasificacion"] = min(100, 95)
        out["impacta_contabilidad"] = True
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    if "PAGO REFERENCIADO" in raw and "IMPUESTO" in raw:
        out["tipo_movimiento"] = "GASTO"
        out["canal"] = "IMPUESTO"
        out["categoria_sugerida"] = "IMPUESTOS"
        out["confianza_clasificacion"] = min(100, 95)
        out["impacta_contabilidad"] = True
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    if "DEPOSITO DE NOMINA" in raw or "NOMINA" in raw:
        out["tipo_movimiento"] = "INGRESO"
        out["canal"] = "NOMINA"
        out["categoria_sugerida"] = "NOMINA"
        out["confianza_clasificacion"] = min(100, 95)
        out["impacta_contabilidad"] = True
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    if "CARGO DOMICILIACION" in raw or "DOMICILIACION" in raw:
        out["tipo_movimiento"] = "GASTO"
        out["canal"] = "DOMICILIACION"
        out["categoria_sugerida"] = "SERVICIOS"
        out["confianza_clasificacion"] = min(100, conf + 15)
        out["impacta_contabilidad"] = True
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    if "RETIRO DE EFECTIVO" in raw or "CAJERO" in raw:
        out["tipo_movimiento"] = "GASTO"
        out["canal"] = "EFECTIVO"
        out["categoria_sugerida"] = "RETIRO_EFECTIVO"
        out["confianza_clasificacion"] = min(100, 90)
        out["impacta_contabilidad"] = True
        out["requiere_revision"] = False
        out["warnings"] = warnings
        return out
    if conf < 60:
        warnings.append("Clasificación de baja confianza")
    out["impacta_contabilidad"] = not out.get("es_movimiento_financiero", False)
    out["requiere_revision"] = (
        int(out.get("confianza_clasificacion") or 0) < 60
        or bank == "DESCONOCIDO"
        or any("ambiguo" in (w or "").lower() or "baja" in (w or "").lower() for w in warnings)
    )
    out["es_transferencia_propia_probable"] = _detect_own_transfer(out, account_holder_name, account_holder_rfc)
    if out.get("es_transferencia_propia_probable"):
        out["impacta_contabilidad"] = False
    out["warnings"] = warnings
    return out

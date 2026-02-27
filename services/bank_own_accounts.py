"""
Detección de transferencias a/de cuentas propias del usuario.
Usa issuer_bank_accounts (CLABE, últimos 4, holder_name, rfc_titular) y datos del movimiento.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

# Palabras que no cuentan como parte del nombre
_STOP = frozenset({"DEL", "LA", "DE", "LOS", "LAS", "CLIENTE", "BENEF", "SA", "CV", "SAPI", "RFC", "REF", "CVE"})


def _norm(s: str) -> str:
    if not s:
        return ""
    t = unicodedata.normalize("NFKD", (s or "").strip().upper())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


def _name_tokens(s: str) -> set[str]:
    return {w for w in _norm(s).split() if len(w) >= 2 and w not in _STOP}


def _names_match(name1: str, name2: str) -> bool:
    if not name1 or not name2:
        return False
    n1, n2 = _norm(name1), _norm(name2)
    if n1 in n2 or n2 in n1:
        return True
    t1, t2 = _name_tokens(name1), _name_tokens(name2)
    overlap = len(t1 & t2)
    return overlap >= 2 or (overlap >= 1 and len(t1) == 1 and len(next(iter(t1), "")) >= 4)


def _normalize_clabe(s: str) -> str:
    """Deja solo dígitos de una CLABE (para comparar)."""
    if not s:
        return ""
    return re.sub(r"\D", "", str(s).strip())


def _clabe_from_movement(mov: dict[str, Any]) -> Optional[str]:
    """
    Extrae CLABE del texto del movimiento (18 dígitos).
    Prioridad: 1) clabe_detectada o extracted.clabe (ya extraída por el parser),
    2) patrón SPEI "REFERENCIA CTA/CLABE: 18dígitos" o "CLABE: 18dígitos",
    3) cualquier secuencia de 18 dígitos en raw_text/referencia.
    """
    # Ya extraída por el parser (pipeline la guarda en clabe_detectada)
    pre = (mov.get("clabe_detectada") or "").strip() or (mov.get("extracted") or {}).get("clabe") or ""
    if pre and len(re.sub(r"\D", "", pre)) == 18:
        return re.sub(r"\D", "", pre)
    sources = [
        (mov.get("raw_text_normalized") or mov.get("raw_text_original") or ""),
        (mov.get("referencia") or ""),
    ]
    for raw in sources:
        if not raw:
            continue
        text = str(raw).upper()
        # Patrón SPEI: "REFERENCIA CTA/CLABE: 059975010014577226" o "=REFERENCIA CTA/CLABE: 0599..."
        m = re.search(r"=?\s*(?:REFERENCIA\s+)?(?:CTA\s*/\s*CLABE|CLABE)\s*[:\s]*(\d{18})\b", text, re.IGNORECASE)
        if m:
            return m.group(1)
        # Alternativa: "CLABE" seguido de 18 dígitos
        m = re.search(r"\bCLABE\s*[:\s]*(\d{18})\b", text, re.IGNORECASE)
        if m:
            return m.group(1)
        # Fallback: quitar espacios y buscar cualquier bloque de 18 dígitos (evitar montos tipo 1,234.56)
        sin_espacios = re.sub(r"\s+", "", text)
        m = re.search(r"\d{18}", sin_espacios)
        if m:
            return m.group(0)
    return None


def _last4_from_movement(mov: dict[str, Any]) -> Optional[str]:
    """Intenta extraer últimos 4 dígitos de cuenta del movimiento (REF CTA, etc.)."""
    raw = (mov.get("raw_text_normalized") or mov.get("raw_text_original") or "").upper()
    # REF CTA 1234 o CUENTA ****1234
    m = re.search(r"(?:REF\s+CTA|CTA|CUENTA)\s*[\*\d]*(\d{4})\b", raw)
    if m:
        return m.group(1)
    return None


def detect_own_account_transfer(
    mov: dict[str, Any],
    user_bank_accounts: list[dict[str, Any]],
    statement_owner_name: Optional[str] = None,
    statement_owner_rfc: Optional[str] = None,
) -> dict[str, Any]:
    """
    Marca si el movimiento es transferencia a/de una cuenta propia registrada.
    Actualiza mov in-place. Devuelve el mismo mov (con flags/reasons).
    user_bank_accounts: listas de dicts con clabe, account_last4, holder_name, rfc_titular, alias, bank_name.
    """
    reasons: list[str] = []
    raw = (mov.get("raw_text_normalized") or mov.get("raw_text_original") or "").upper()
    if "SPEI" not in raw and "TRASPASO" not in raw:
        return mov

    contraparte = (mov.get("contraparte_nombre") or "").strip()
    rfc_mov = (mov.get("rfc_detectado") or "").strip().upper()

    # Regla 1: CLABE coincide (comparación normalizada: solo dígitos)
    mov_clabe = _clabe_from_movement(mov)
    if mov_clabe and user_bank_accounts:
        mov_clabe_norm = _normalize_clabe(mov_clabe)
        if len(mov_clabe_norm) == 18:
            for acc in user_bank_accounts:
                ac = (acc.get("clabe") or "").strip()
                if not ac:
                    continue
                ac_norm = _normalize_clabe(ac)
                if ac_norm == mov_clabe_norm:
                    mov["es_transferencia_propia_probable"] = True
                    mov["impacta_contabilidad"] = False
                    mov["categoria_sugerida"] = "CUENTA_PROPIA"
                    mov["subcategoria_sugerida"] = "TRASPASO_INTERNO"
                    reasons.append("Coincide CLABE con cuenta propia registrada")
                    if "confianza_clasificacion" in mov:
                        mov["confianza_clasificacion"] = max(mov.get("confianza_clasificacion", 0), 90)
                    w = mov.get("warnings") or []
                    if "Coincide CLABE con cuenta propia" not in w:
                        w.append("Coincide CLABE con cuenta propia")
                    mov["warnings"] = w
                    return mov

    # Regla 2: últimos 4 dígitos (solo si la cuenta NO tiene CLABE; la CLABE es el identificador principal)
    mov_last4 = _last4_from_movement(mov) or (mov.get("account_hint") or "").replace("*", "").strip()[-4:]
    if mov_last4 and len(mov_last4) >= 4 and user_bank_accounts:
        for acc in user_bank_accounts:
            if (acc.get("clabe") or "").strip():
                continue  # Si tiene CLABE, no emparejar por últimos 4 (prioridad CLABE)
            a4 = (acc.get("account_last4") or "").strip()
            if a4 and a4 == mov_last4:
                mov["es_transferencia_propia_probable"] = True
                mov["impacta_contabilidad"] = False
                mov["categoria_sugerida"] = "CUENTA_PROPIA"
                mov["subcategoria_sugerida"] = "TRASPASO_INTERNO"
                reasons.append("Cuenta coincide con últimos 4 dígitos registrados")
                w = mov.get("warnings") or []
                if "Cuenta propia (últimos 4 dígitos)" not in w:
                    w.append("Cuenta propia (últimos 4 dígitos)")
                mov["warnings"] = w
                return mov

    # Regla 3 y 4: nombre contraparte = titular del estado o holder_name de cuenta registrada
    if statement_owner_name and contraparte and _names_match(statement_owner_name, contraparte):
        mov["es_transferencia_propia_probable"] = True
        mov["impacta_contabilidad"] = False
        mov["categoria_sugerida"] = "CUENTA_PROPIA"
        mov["subcategoria_sugerida"] = "TRASPASO_INTERNO"
        reasons.append("Beneficiario coincide con titular del estado de cuenta")
        w = mov.get("warnings") or []
        if "Cuenta propia (titular)" not in w:
            w.append("Cuenta propia (titular)")
        mov["warnings"] = w
        return mov

    if user_bank_accounts and contraparte:
        for acc in user_bank_accounts:
            holder = (acc.get("holder_name") or "").strip()
            if holder and _names_match(holder, contraparte):
                mov["es_transferencia_propia_probable"] = True
                mov["impacta_contabilidad"] = False
                mov["categoria_sugerida"] = "CUENTA_PROPIA"
                mov["subcategoria_sugerida"] = "TRASPASO_INTERNO"
                reasons.append("Beneficiario coincide con cuenta propia registrada")
                w = mov.get("warnings") or []
                if "Cuenta propia (registrada)" not in w:
                    w.append("Cuenta propia (registrada)")
                mov["warnings"] = w
                return mov

    # Regla 5: RFC
    if statement_owner_rfc and rfc_mov and statement_owner_rfc.strip().upper() == rfc_mov:
        mov["es_transferencia_propia_probable"] = True
        mov["impacta_contabilidad"] = False
        mov["categoria_sugerida"] = "CUENTA_PROPIA"
        mov["subcategoria_sugerida"] = "TRASPASO_INTERNO"
        reasons.append("RFC coincide con titular")
        w = mov.get("warnings") or []
        if "Cuenta propia (RFC)" not in w:
            w.append("Cuenta propia (RFC)")
        mov["warnings"] = w
        return mov

    if user_bank_accounts:
        for acc in user_bank_accounts:
            rfc_acc = (acc.get("rfc_titular") or "").strip().upper()
            if rfc_acc and rfc_mov and rfc_acc == rfc_mov:
                mov["es_transferencia_propia_probable"] = True
                mov["impacta_contabilidad"] = False
                mov["categoria_sugerida"] = "CUENTA_PROPIA"
                mov["subcategoria_sugerida"] = "TRASPASO_INTERNO"
                reasons.append("RFC coincide con cuenta registrada")
                w = mov.get("warnings") or []
                if "Cuenta propia (RFC)" not in w:
                    w.append("Cuenta propia (RFC)")
                mov["warnings"] = w
                return mov

    return mov

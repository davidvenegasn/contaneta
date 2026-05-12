"""
Clasificación automática de movimientos bancarios.

Reglas:
- Si CLABE destino/origen coincide con mis cuentas → TRASPASO_PROPIO (alias CUENTA_PROPIA)
- Pagos tarjeta de crédito → FINANCIERO_PAGO_TARJETA
- Comisiones / cargos bancarios → COMISION_BANCARIA
- Nómina keywords → NOMINA
"""
from __future__ import annotations

import re
from typing import Any

from database import db, table_exists

# Regex patterns for classification
_CARD_PAYMENT_RE = re.compile(
    r"(PAGO\s*(DE\s*)?TARJETA|TAR\s*CR[EÉ]DITO|T\.?C\.?\s+PAGO|PAGO\s+TC|"
    r"CREDITO\s+PAGO|AMEX\s+PAGO|VISA\s+PAGO|MASTERCARD\s+PAGO)",
    re.IGNORECASE,
)
_COMMISSION_RE = re.compile(
    r"(COMISI[OÓ]N|CARGO\s+BANCARIO|ANUALIDAD|IVA\s+COMISI[OÓ]N|MANEJO\s+DE\s+CUENTA|"
    r"COMI?\s+BANCARIA|COSTO\s+MANEJO)",
    re.IGNORECASE,
)
_NOMINA_RE = re.compile(
    r"(N[OÓ]MINA|PAYROLL|SUELDO|SALARIO|PAGO\s+EMPLE)",
    re.IGNORECASE,
)
_OWN_TRANSFER_RE = re.compile(
    r"(TRASPASO\s+(PROPIO|ENTRE\s+CUENTAS|MISMO\s+TITULAR)|TRASPASO\s+A\s+MI\s+CUENTA)",
    re.IGNORECASE,
)
_FINANCIAL_RE = re.compile(
    r"(INTERESES|RENDIMIENTO|GAT\s|REND\s+DIARIO|INTERES\s+NETO)",
    re.IGNORECASE,
)


def classify_movement(
    movement: dict[str, Any],
    own_clabes: set[str] | None = None,
    own_last4s: set[str] | None = None,
) -> str:
    """
    Classify a bank movement. Returns a category string.
    """
    desc = (
        movement.get("descripcion")
        or movement.get("raw_description")
        or movement.get("concepto")
        or ""
    ).strip().upper()

    clabe_dest = (movement.get("clabe_destino") or movement.get("clabe_contraparte") or "").strip()
    clabe_orig = (movement.get("clabe_origen") or "").strip()

    # 1) Own account transfer: CLABE matches one of our accounts
    if own_clabes:
        for clabe in [clabe_dest, clabe_orig]:
            if clabe and clabe in own_clabes:
                return "CUENTA_PROPIA"

    # 2) Own transfer by last4 in description
    if own_last4s:
        for last4 in own_last4s:
            if last4 and last4 in desc:
                # Only if it looks like a transfer
                if _OWN_TRANSFER_RE.search(desc) or "TRASPASO" in desc:
                    return "CUENTA_PROPIA"

    # 3) Own transfer by keyword
    if _OWN_TRANSFER_RE.search(desc):
        return "CUENTA_PROPIA"

    # 4) Credit card payment
    if _CARD_PAYMENT_RE.search(desc):
        return "FINANCIERO_PAGO_TARJETA"

    # 5) Bank commission
    if _COMMISSION_RE.search(desc):
        return "COMISION_BANCARIA"

    # 6) Payroll
    if _NOMINA_RE.search(desc):
        return "NOMINA"

    # 7) Financial movements (interest, yields)
    if _FINANCIAL_RE.search(desc):
        return "MOVIMIENTO_FINANCIERO"

    return ""


def classify_movements_batch(
    issuer_id: int,
    movements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Classify a batch of movements for an issuer.
    Returns movements with 'suggested_categoria' field added.
    """
    from services.bank.bank_accounts import list_active_accounts_raw as list_active_accounts

    accounts = list_active_accounts(issuer_id)
    own_clabes = {(a.get("clabe") or "").strip() for a in accounts if a.get("clabe")}
    own_last4s = {(a.get("account_last4") or "").strip() for a in accounts if a.get("account_last4")}

    for m in movements:
        existing_cat = (m.get("categoria") or "").strip()
        if not existing_cat:
            suggested = classify_movement(m, own_clabes=own_clabes, own_last4s=own_last4s)
            m["suggested_categoria"] = suggested
        else:
            m["suggested_categoria"] = existing_cat

    return movements


def auto_classify_unclassified(issuer_id: int, ym: str) -> int:
    """
    Auto-classify movements without a category for a given month.
    Returns count of movements updated.
    """
    from services.bank.bank_accounts import list_active_accounts_raw as list_active_accounts

    conn = db()
    try:
        if not table_exists(conn, "bank_movements"):
            return 0

        accounts = list_active_accounts(issuer_id)
        own_clabes = {(a.get("clabe") or "").strip() for a in accounts if a.get("clabe")}
        own_last4s = {(a.get("account_last4") or "").strip() for a in accounts if a.get("account_last4")}

        movs = conn.execute(
            """SELECT id, descripcion, raw_description, concepto, clabe_destino, clabe_origen,
                      clabe_contraparte
               FROM bank_movements
               WHERE issuer_id = ? AND period_month = ? AND (categoria IS NULL OR categoria = '')""",
            (issuer_id, ym),
        ).fetchall()

        updated = 0
        for m in movs:
            m_dict = dict(m) if hasattr(m, "keys") else m
            cat = classify_movement(m_dict, own_clabes=own_clabes, own_last4s=own_last4s)
            if cat:
                conn.execute(
                    "UPDATE bank_movements SET categoria = ? WHERE id = ? AND issuer_id = ?",
                    (cat, m_dict["id"], issuer_id),
                )
                updated += 1

        if updated:
            conn.commit()
        return updated
    except Exception:
        return 0
    finally:
        conn.close()

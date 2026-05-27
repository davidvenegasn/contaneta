"""Pre-flight checks before CFDI invoice emission.

Validates that the issuer's account is fully configured and within plan limits
before attempting to create and stamp an invoice via Facturapi.
"""
import logging
import os
import re
from typing import Any

from database import db, db_rows, has_column, table_exists

logger = logging.getLogger(__name__)

_RFC_PF = re.compile(r"^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$")  # Persona física (13)
_RFC_PM = re.compile(r"^[A-ZÑ&]{3}\d{6}[A-Z0-9]{3}$")  # Persona moral (12)


def _is_valid_rfc(rfc: str) -> bool:
    """Return True if RFC matches PF or PM format."""
    rfc = (rfc or "").strip().upper()
    return bool(_RFC_PF.match(rfc) or _RFC_PM.match(rfc))


def validate_can_issue_invoice(issuer_id: int, user_id: int = 0) -> dict[str, Any]:
    """Run all pre-flight checks for invoice emission.

    Args:
        issuer_id: Tenant ID.
        user_id: Current user ID (for plan checks).

    Returns:
        Dict with keys:
            ok (bool): True if all checks pass.
            errors (list[dict]): Each error has 'code', 'message', 'action'.
    """
    errors: list[dict[str, str]] = []

    # --- 1. Facturapi API key ---
    facturapi_key = (os.getenv("FACTURAPI_SECRET_KEY") or "").strip()
    if not facturapi_key:
        errors.append({
            "code": "NO_FACTURAPI_KEY",
            "message": "Falta la clave de Facturapi para timbrar.",
            "action": "Contacta a soporte para configurar la conexión de facturación.",
        })

    # --- 2. Issuer basic data ---
    conn = db()
    try:
        row = conn.execute(
            "SELECT rfc, razon_social, regimen_fiscal, facturapi_org_id, active FROM issuers WHERE id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        errors.append({
            "code": "ISSUER_NOT_FOUND",
            "message": "No se encontró la empresa emisora.",
            "action": "Verifica tu cuenta.",
        })
        return {"ok": False, "errors": errors}

    if not row["active"]:
        errors.append({
            "code": "ISSUER_INACTIVE",
            "message": "La empresa emisora está inactiva.",
            "action": "Contacta a soporte.",
        })

    rfc = (row["rfc"] or "").strip()
    if not rfc or rfc == "PENDIENTE" or not _is_valid_rfc(rfc):
        errors.append({
            "code": "INVALID_RFC",
            "message": "El RFC del emisor no está configurado o es inválido.",
            "action": "Ve a Configuración → Datos fiscales y captura tu RFC.",
        })

    razon = (row["razon_social"] or "").strip()
    if not razon or razon == "PENDIENTE":
        errors.append({
            "code": "NO_RAZON_SOCIAL",
            "message": "La razón social del emisor no está configurada.",
            "action": "Ve a Configuración → Datos fiscales y captura tu razón social.",
        })

    regimen = (row["regimen_fiscal"] or "").strip()
    if not regimen or len(regimen) != 3:
        errors.append({
            "code": "NO_REGIMEN_FISCAL",
            "message": "El régimen fiscal del emisor no está configurado.",
            "action": "Ve a Configuración → Datos fiscales y selecciona tu régimen.",
        })

    org_id = (row["facturapi_org_id"] or "").strip()
    if not org_id:
        errors.append({
            "code": "NO_FACTURAPI_ORG",
            "message": "La organización de Facturapi no está vinculada.",
            "action": "Contacta a soporte para vincular tu cuenta de facturación.",
        })

    # --- 3. FIEL credentials ---
    conn = db()
    try:
        if table_exists(conn, "sat_credentials"):
            cred = conn.execute(
                "SELECT validation_ok, validation_message FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
                (issuer_id,),
            ).fetchone()
            if not cred:
                errors.append({
                    "code": "NO_FIEL",
                    "message": "No se han cargado los archivos FIEL (e.firma).",
                    "action": "Ve a Configuración → SAT / e.firma y sube tu .cer y .key.",
                })
            elif not cred["validation_ok"]:
                msg = cred["validation_message"] or "Error de validación"
                errors.append({
                    "code": "FIEL_INVALID",
                    "message": f"La e.firma (FIEL) no pasó validación: {msg}",
                    "action": "Ve a Configuración → SAT / e.firma y vuelve a cargar tus archivos.",
                })
    finally:
        conn.close()

    # --- 4. Plan limits ---
    try:
        from services.billing.plans import check_limit
        limit_check = check_limit(issuer_id, "invoice")
        if not limit_check["allowed"]:
            errors.append({
                "code": "PLAN_LIMIT",
                "message": limit_check["reason"],
                "action": "Actualiza tu plan para emitir más facturas.",
            })
    except Exception as e:
        logger.warning("preflight plan check failed: %s", e)

    return {"ok": len(errors) == 0, "errors": errors}

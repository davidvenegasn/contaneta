"""Emisores (issuers) y tokens legacy."""
import secrets

from config import DEMO_ISSUER_ID, DEV_MODE, DEV_TOKEN
from database import db, has_column

# Días de trial al registrar (sin Stripe aún). Configurable por env si se desea.
TRIAL_DAYS_DEFAULT = 14


def _row_to_dict(row):
    """Convierte fila (dict o sqlite3.Row) a dict con .get() seguro."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return dict(zip(row.keys(), row))
    try:
        return dict(row)
    except Exception:
        return None


def get_issuer_by_token(token: str):
    if DEV_MODE and (not token or token == DEV_TOKEN):
        return {
            "id": -1,
            "alias": "Contaneta",
            "rfc": "XIA190128J61",
            "regimen_fiscal": None,
            "facturapi_org_id": None,
            "active": 1,
        }

    conn = db()
    row = conn.execute(
        """
        SELECT i.id, i.rfc, i.razon_social, i.regimen_fiscal, i.active, i.facturapi_org_id, t.token
        FROM issuer_tokens t
        JOIN issuers i ON i.id = t.issuer_id
        WHERE t.token = ? AND t.active = 1 AND i.active = 1 LIMIT 1
        """,
        (token,),
    ).fetchone()
    conn.close()

    if not row:
        raise ValueError("Token inválido o inactivo.")

    d = _row_to_dict(row)
    if not d:
        raise ValueError("Token inválido o inactivo.")
    regimen = (d.get("regimen_fiscal") or "").strip().upper()
    return {
        "id": d["id"],
        "rfc": d.get("rfc") or "",
        "alias": d.get("razon_social") or d.get("rfc") or "Emisor",
        "regimen_fiscal": regimen or None,
        "facturapi_org_id": d.get("facturapi_org_id"),
        "active": d.get("active", 1),
    }


def get_issuer_by_id(issuer_id: int):
    if DEV_MODE and issuer_id == -1:
        return {
            "id": -1,
            "alias": "Contaneta",
            "rfc": "XIA190128J61",
            "regimen_fiscal": None,
            "facturapi_org_id": None,
            "active": 1,
        }
    conn = db()
    row = conn.execute(
        "SELECT id, rfc, razon_social, regimen_fiscal, fiscal_zip, active, facturapi_org_id FROM issuers WHERE id = ? AND active = 1 LIMIT 1",
        (issuer_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = _row_to_dict(row)
    if not d:
        return None
    regimen = (d.get("regimen_fiscal") or "").strip().upper()
    return {
        "id": d["id"],
        "rfc": d.get("rfc") or "",
        "alias": d.get("razon_social") or d.get("rfc") or "Emisor",
        "regimen_fiscal": regimen or None,
        "fiscal_zip": (d.get("fiscal_zip") or "").strip() or None,
        "facturapi_org_id": d.get("facturapi_org_id"),
        "active": d.get("active", 1),
    }


def get_issuer_by_rfc(rfc: str):
    """Devuelve el issuer activo con el RFC dado (normalizado). None si no existe."""
    if not rfc or not str(rfc).strip():
        return None
    rfc_norm = str(rfc).strip().upper()
    if DEV_MODE and rfc_norm == "XIA190128J61":
        return get_issuer_by_id(-1)
    conn = db()
    row = conn.execute(
        "SELECT id, rfc, razon_social, regimen_fiscal, active, facturapi_org_id FROM issuers WHERE UPPER(TRIM(rfc)) = ? AND active = 1 LIMIT 1",
        (rfc_norm,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = _row_to_dict(row)
    if not d:
        return None
    regimen = (d.get("regimen_fiscal") or "").strip().upper()
    return {
        "id": d["id"],
        "rfc": d.get("rfc") or "",
        "alias": d.get("razon_social") or d.get("rfc") or "Emisor",
        "regimen_fiscal": regimen or None,
        "facturapi_org_id": d.get("facturapi_org_id"),
        "active": d.get("active", 1),
    }


def get_demo_issuer():
    if DEMO_ISSUER_ID:
        return get_issuer_by_id(DEMO_ISSUER_ID)
    if DEV_MODE:
        try:
            return get_issuer_by_token(DEV_TOKEN)
        except ValueError:
            pass
    return None


def update_issuer_profile(
    issuer_id: int,
    razon_social: str | None = None,
    regimen_fiscal: str | None = None,
    fiscal_zip: str | None = None,
) -> None:
    """Update the issuer's razon_social, regimen_fiscal and/or fiscal_zip.

    Args:
        issuer_id: Tenant ID.
        razon_social: New legal name (or None to skip).
        regimen_fiscal: New tax regime code (or None to skip).
        fiscal_zip: New fiscal postal code (or None to skip).
    """
    set_parts: list[str] = []
    params: list = []
    if razon_social is not None:
        razon_social = razon_social.strip()
        set_parts.append("razon_social = ?")
        params.append(razon_social)
    if regimen_fiscal is not None:
        regimen_fiscal = regimen_fiscal.strip().upper() or None
        set_parts.append("regimen_fiscal = ?")
        params.append(regimen_fiscal)
    if fiscal_zip is not None:
        fiscal_zip = fiscal_zip.strip() or None
        set_parts.append("fiscal_zip = ?")
        params.append(fiscal_zip)
    if not set_parts:
        return
    set_parts.append("updated_at = datetime('now')")
    params.append(issuer_id)
    conn = db()
    try:
        conn.execute(
            f"UPDATE issuers SET {', '.join(set_parts)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    finally:
        conn.close()


def create_issuer_with_token(
    rfc: str,
    razon_social: str,
    regimen_fiscal: str | None = None,
    trial_days: int | None = None,
) -> tuple[int, str]:
    """
    Crea un issuer y un token activo. Devuelve (issuer_id, token).
    Si existe la columna trial_expires_at, la setea a now + trial_days (default 14).
    """
    rfc = (rfc or "").strip().upper()
    razon_social = (razon_social or "").strip() or ""
    regimen_fiscal = (regimen_fiscal or "").strip() or None
    days = trial_days if trial_days is not None else TRIAL_DAYS_DEFAULT
    conn = db()
    try:
        cur = conn.execute(
            """INSERT INTO issuers (rfc, razon_social, regimen_fiscal, active)
               VALUES (?, ?, ?, 1)""",
            (rfc, razon_social, regimen_fiscal),
        )
        issuer_id = cur.lastrowid
        if has_column(conn, "issuers", "trial_expires_at") and days > 0:
            conn.execute(
                "UPDATE issuers SET trial_expires_at = datetime('now', ?) WHERE id = ?",
                (f"+{days} days", issuer_id),
            )
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO issuer_tokens (issuer_id, token, active) VALUES (?, ?, 1)",
            (issuer_id, token),
        )
        conn.commit()
    finally:
        conn.close()

    # Provision Facturapi org synchronously so the user lands on the portal
    # with everything ready (no "still being created" message). Adds ~1-2s to
    # signup, but means CSD upload + emission work immediately. If Facturapi
    # is down or unreachable, fall back to the job queue so the org gets
    # created when service returns.
    import logging
    log = logging.getLogger(__name__)
    try:
        from services.facturapi.provision import ensure_provisioned
        ensure_provisioned(issuer_id)
    except Exception as e:
        log.warning(
            "Sync provision failed for issuer_id=%s (%s); falling back to job queue",
            issuer_id, e,
        )
        try:
            from services import jobs as jobs_service
            jobs_service.enqueue_job(
                name="facturapi_provision_org",
                issuer_id=issuer_id,
                payload={"reason": "signup_fallback"},
                max_attempts=5,
            )
        except Exception:
            log.exception("Failed to enqueue facturapi_provision_org fallback for issuer_id=%s", issuer_id)

    return (issuer_id, token)

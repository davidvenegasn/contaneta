"""Account API routes."""
import logging

from fastapi import Depends, HTTPException, Query, Request

from database import db_execute, db_rows
from routers.deps import get_portal_issuer

logger = logging.getLogger(__name__)

try:
    from cfdi_pdf import CLAVE_UNIDAD, FORMA_PAGO, MONEDA, REGIMEN_FISCAL, USO_CFDI
except Exception:
    USO_CFDI = {"G03": "Gastos en general", "G01": "Adquisición de mercancías", "CN01": "Nómina"}
    REGIMEN_FISCAL = {"601": "General de Ley Personas Morales", "612": "Personas Físicas con Actividades Empresariales", "616": "Sin obligaciones fiscales", "626": "Régimen Simplificado de Confianza"}
    FORMA_PAGO = {"03": "Transferencia electrónica", "01": "Efectivo", "99": "Por definir"}
    MONEDA = {"MXN": "Peso Mexicano", "USD": "Dólar Americano"}
    CLAVE_UNIDAD = {"E48": "Unidad de servicio", "EA": "Cada uno", "H87": "Pieza"}

from services import jobs as jobs_service
from services.billing import subscription as subscription_service
from services.http import ok, ok_list


def register_account_routes(router):
    """Register Account routes on the API router."""

    # ----- Account status (checklist activación + P36 chips topbar) -----
    @router.get("/account/status")
    def api_account_status(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """
        Estado de activación del emisor para el checklist del dropdown "Mi cuenta" y chips del topbar.
        Requiere sesión o token (get_portal_issuer).
        Retorna: issuer_ok, sat_ok, has_customer, has_product, completed, total,
                 sat_status, last_sync_at, sync_status, plan_label (P36).
        """
        from services.tenant import require_issuer_id

        issuer_id = require_issuer_id(issuer)
        user_id = getattr(request.state, "user_id", 0) or 0
        issuer_ok = False
        sat_ok = False
        has_customer = False
        has_product = False
        sat_status = "none"
        last_sync_at = None
        sync_status = "ok"
        plan_label = None

        if issuer_id > 0:
            # 1) Datos fiscales: RFC, razón social, régimen no vacíos (CP opcional si existe en DB)
            ir = db_rows(
                "SELECT rfc, razon_social, regimen_fiscal FROM issuers WHERE id = ? LIMIT 1",
                (issuer_id,),
            )
            if ir:
                r = ir[0]
                rfc = (r.get("rfc") or "").strip()
                razon = (r.get("razon_social") or "").strip()
                regimen = (r.get("regimen_fiscal") or "").strip()
                issuer_ok = bool(rfc and razon and regimen)

            # 2) SAT FIEL: credenciales válidas (validation_ok = 1); P36 sat_status: ok / none / error
            sc_valid = db_rows(
                "SELECT 1 FROM sat_credentials WHERE issuer_id = ? AND validation_ok = 1 LIMIT 1",
                (issuer_id,),
            )
            sc_any = db_rows(
                "SELECT 1 FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
                (issuer_id,),
            )
            sat_ok = bool(sc_valid)
            if sc_valid:
                sat_status = "ok"
            elif sc_any:
                sat_status = "error"
            else:
                sat_status = "none"

            # 3) Al menos un cliente
            cust = db_rows("SELECT COUNT(*) AS n FROM customer_profiles WHERE issuer_id = ?", (issuer_id,))
            has_customer = (cust[0]["n"] if cust else 0) >= 1

            # 4) Al menos un producto
            prod = db_rows("SELECT COUNT(*) AS n FROM issuer_products WHERE issuer_id = ?", (issuer_id,))
            has_product = (prod[0]["n"] if prod else 0) >= 1

            # P36: sync status (shared logic from services.sat.sat_sync)
            from services.sat.sat_sync import get_sat_sync_status
            _sync = get_sat_sync_status(issuer_id)
            last_sync_at = _sync["last_sync_at"]
            sync_status = _sync["status"]

            # P36: plan_label — use canonical plan from plans service for consistency
            from services.billing.plans import get_issuer_plan, get_plan_config
            _plan_name = get_issuer_plan(issuer_id)
            _plan_cfg = get_plan_config(_plan_name)
            trial_days_left = None
            if _plan_name == "free":
                # For free plan, show Trial if trial active, else hide badge
                if subscription_service.is_issuer_trial_active(issuer_id):
                    plan_label = "Trial"
                    # Calculate days remaining
                    _trial_row = db_rows(
                        "SELECT trial_expires_at FROM issuers WHERE id = ? LIMIT 1",
                        (issuer_id,),
                    )
                    if _trial_row and _trial_row[0].get("trial_expires_at"):
                        from datetime import datetime, timezone
                        try:
                            _exp = datetime.fromisoformat(_trial_row[0]["trial_expires_at"].replace("Z", "+00:00"))
                            if _exp.tzinfo is None:
                                _exp = _exp.replace(tzinfo=timezone.utc)
                            _now = datetime.now(timezone.utc)
                            trial_days_left = max(0, (_exp - _now).days)
                        except Exception:
                            pass
                else:
                    plan_label = "Gratis"
            else:
                plan_label = _plan_cfg["label"]

        completed = sum([issuer_ok, sat_ok, has_customer, has_product])
        return {
            "issuer_ok": issuer_ok,
            "sat_ok": sat_ok,
            "has_customer": has_customer,
            "has_product": has_product,
            "completed": completed,
            "total": 4,
            "sat_status": sat_status,
            "last_sync_at": last_sync_at,
            "sync_status": sync_status,
            "plan_label": plan_label,
            "trial_days_left": trial_days_left,
        }


    # ----- Global search -----

    @router.get("/jobs")
    def api_jobs(
        issuer: dict = Depends(get_portal_issuer),
        limit: int = Query(20, ge=1, le=200, description="Máximo de registros"),
    ):
        items = jobs_service.list_jobs(issuer["id"], limit=limit)
        total = jobs_service.count_jobs(issuer["id"])
        return ok_list(items, total=total)


    @router.get("/jobs/{job_id}")
    def api_job_get(job_id: int, issuer: dict = Depends(get_portal_issuer)):
        job = jobs_service.get_job_for_issuer(job_id, issuer["id"])
        if not job:
            raise HTTPException(status_code=404, detail="Job no encontrado.")
        payload = {
            "id": job.get("id"),
            "issuer_id": job.get("issuer_id"),
            "name": job.get("name"),
            "status": job.get("status"),
            "progress": job.get("progress"),
            "message": job.get("message"),
            "payload": job.get("payload"),
            "result": job.get("result"),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        }
        return ok(payload)


    # ----- LFPDPPP: Data export (Derecho de Acceso) -----
    @router.get("/account/my-data")
    def api_my_data_export(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Export all personal data for the authenticated user (LFPDPPP Art. 23)."""
        from routers.api._helpers import _api_rate_check
        _api_rate_check(request, f"my-data-export:{issuer['user_id']}", max_attempts=3, window=86400.0)

        user_id = issuer["user_id"]
        issuer_id = issuer["id"]

        user_rows = db_rows("SELECT id, email, phone, name, created_at FROM users WHERE id = ?", [user_id])
        user_data = dict(user_rows[0]) if user_rows else {}

        memberships = db_rows(
            "SELECT issuer_id, role, created_at FROM memberships WHERE user_id = ?", [user_id]
        )

        customers = db_rows(
            "SELECT rfc, legal_name, email, zip, alias, created_at FROM customer_profiles WHERE issuer_id = ?",
            [issuer_id],
        )

        audit = db_rows(
            "SELECT action, details, created_at FROM audit_log WHERE user_id = ? ORDER BY created_at DESC LIMIT 200",
            [user_id],
        )

        return ok({
            "user": user_data,
            "memberships": [dict(m) for m in memberships],
            "customers": [dict(c) for c in customers],
            "audit_log": [dict(a) for a in audit],
            "exported_at": __import__("datetime").datetime.utcnow().isoformat(),
        })


    # ----- LFPDPPP: Deletion request (Derecho de Cancelación) -----
    @router.post("/account/delete-request")
    async def api_delete_request(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Request account deletion (LFPDPPP Art. 26). Creates a pending request for review."""
        from services.auth.csrf import csrf_service
        csrf_service.verify_api_csrf(request)

        user_id = issuer["user_id"]

        # Check for existing pending request
        existing = db_rows(
            "SELECT id FROM account_deletion_requests WHERE user_id = ? AND status = 'pending'",
            [user_id],
        )
        if existing:
            return ok({"message": "Ya existe una solicitud de eliminación pendiente.", "request_id": existing[0]["id"]})

        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        reason = body.get("reason", "")

        db_execute(
            "INSERT INTO account_deletion_requests (user_id, reason) VALUES (?, ?)",
            [user_id, reason[:500]],
        )
        new_row = db_rows(
            "SELECT id, status, requested_at FROM account_deletion_requests WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            [user_id],
        )

        return ok({
            "message": "Solicitud de eliminación registrada. Será procesada en un plazo máximo de 20 días hábiles.",
            "request_id": new_row[0]["id"] if new_row else None,
        })

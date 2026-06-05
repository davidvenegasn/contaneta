"""Portal routes for Facturapi tenant setup.

Three concerns:
  * GET /portal/setup/manifiesto — page that loads the embedded carta manifesto iframe.
  * GET /portal/api/facturapi/status — JSON poll for the page (org provisioned? CSD uploaded? manifest signed?).
  * POST /portal/api/facturapi/upload-csd — multipart upload of .cer + .key + password → Facturapi.
  * POST /portal/api/facturapi/retry-provision — re-enqueue the provisioning job if it failed.

All routes require an authenticated portal session.
"""
from __future__ import annotations

import logging
import os

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from database import db
from routers.deps import get_portal_issuer
from routers.portal._helpers import render_portal
from services.auth import csrf as csrf_service
from services.facturapi import orgs as fpi_orgs

logger = logging.getLogger(__name__)

# Public iframe published by Facturapi. Overridable via env in case Facturapi
# changes the URL or we need a tenant-specific signed link.
MANIFEST_IFRAME_BASE = (
    os.getenv("FACTURAPI_MANIFEST_IFRAME_URL")
    or "https://www.facturapi.io/embedded/manifiesto"
)

# Multipart upload size caps. CSDs are tiny (1-3 KB); cap generously at 50 KB.
MAX_CSD_FILE_SIZE = 50 * 1024


def _read_issuer_facturapi_state(issuer_id: int) -> dict:
    """Returns: { facturapi_org_id, facturapi_provisioned_at, manifest_signed_at }."""
    conn = db()
    try:
        row = conn.execute(
            """SELECT facturapi_org_id, facturapi_provisioned_at, manifest_signed_at
               FROM issuers WHERE id = ? LIMIT 1""",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"facturapi_org_id": None, "facturapi_provisioned_at": None, "manifest_signed_at": None}
    return dict(row) if hasattr(row, "keys") else dict(zip(row.keys(), row))


def register_facturapi_setup_routes(router, templates):

    @router.get("/setup/manifiesto")
    def portal_setup_manifiesto(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        state = _read_issuer_facturapi_state(issuer["id"])
        org_id = state.get("facturapi_org_id")
        iframe_url = None
        if org_id and not state.get("manifest_signed_at"):
            iframe_url = f"{MANIFEST_IFRAME_BASE}?organization_id={org_id}"

        return render_portal(
            templates,
            request,
            issuer=issuer,
            template_name="portal_manifesto.html",
            active_page="setup_manifiesto",
            title="Configurar facturación — Carta manifiesto",
            facturapi_org_id=org_id,
            facturapi_provisioned_at=state.get("facturapi_provisioned_at"),
            manifest_signed_at=state.get("manifest_signed_at"),
            iframe_url=iframe_url,
        )

    @router.get("/api/facturapi/status")
    def portal_facturapi_status(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        state = _read_issuer_facturapi_state(issuer["id"])
        return {
            "ok": True,
            "provisioned": bool(state.get("facturapi_org_id")),
            "org_id": state.get("facturapi_org_id"),
            "provisioned_at": state.get("facturapi_provisioned_at"),
            "manifest_signed": bool(state.get("manifest_signed_at")),
            "manifest_signed_at": state.get("manifest_signed_at"),
        }

    @router.post("/api/facturapi/upload-csd")
    async def portal_facturapi_upload_csd(
        request: Request,
        cer_file: UploadFile = File(...),
        key_file: UploadFile = File(...),
        password: str = Form(...),
        csrf_token: str = Form(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        if not csrf_service.verify_csrf_token((csrf_token or "").strip()):
            raise HTTPException(status_code=400, detail="CSRF inválido")

        state = _read_issuer_facturapi_state(issuer["id"])
        org_id = state.get("facturapi_org_id")
        if not org_id:
            raise HTTPException(
                status_code=409,
                detail="Tu organización en Facturapi aún se está creando. Intenta de nuevo en unos segundos.",
            )

        for upload in (cer_file, key_file):
            name = (upload.filename or "").lower()
            ext_ok = name.endswith(".cer") if upload is cer_file else name.endswith(".key")
            if not ext_ok:
                raise HTTPException(status_code=400, detail=f"Extensión inválida: {upload.filename}")

        cer_bytes = await cer_file.read()
        key_bytes = await key_file.read()
        if len(cer_bytes) > MAX_CSD_FILE_SIZE or len(key_bytes) > MAX_CSD_FILE_SIZE:
            raise HTTPException(status_code=413, detail="Archivo demasiado grande")
        if len(cer_bytes) < 100 or len(key_bytes) < 100:
            raise HTTPException(status_code=400, detail="Archivo vacío o corrupto")

        password = (password or "").strip()
        if not password:
            raise HTTPException(status_code=400, detail="Contraseña requerida")

        try:
            result = fpi_orgs.upload_csd(
                org_id,
                cer_bytes=cer_bytes,
                key_bytes=key_bytes,
                password=password,
            )
        except fpi_orgs.FacturapiOrgsError as e:
            logger.warning(
                "CSD upload failed for issuer=%s org=%s: %s", issuer["id"], org_id, e
            )
            # Surface Facturapi's message — typically "no es CSD", "password incorrecta",
            # or "RFC no coincide", which the user needs to act on.
            return JSONResponse(
                status_code=400 if e.status in (400, 422) else 502,
                content={"ok": False, "error": {"code": "CSD_UPLOAD_FAILED", "message": e.body}},
            )

        return {"ok": True, "organization": result}

    @router.post("/api/facturapi/retry-provision")
    def portal_facturapi_retry_provision(
        request: Request,
        csrf_token: str = Form(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        if not csrf_service.verify_csrf_token((csrf_token or "").strip()):
            raise HTTPException(status_code=400, detail="CSRF inválido")

        state = _read_issuer_facturapi_state(issuer["id"])
        if state.get("facturapi_org_id"):
            return {"ok": True, "already_provisioned": True, "org_id": state["facturapi_org_id"]}

        try:
            from services import jobs as jobs_service
            jobs_service.enqueue_job(
                name="facturapi_provision_org",
                issuer_id=issuer["id"],
                payload={"reason": "manual_retry"},
                max_attempts=5,
            )
        except Exception as e:
            logger.exception("retry-provision enqueue failed: %s", e)
            raise HTTPException(status_code=500, detail="No se pudo encolar el reintento")

        return {"ok": True, "enqueued": True}

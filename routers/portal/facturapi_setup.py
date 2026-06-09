"""Portal routes for Facturapi tenant onboarding.

Unified single-screen onboarding:
  * GET /portal/setup/credenciales — page with FIEL + CSD upload (single screen).
  * POST /portal/api/facturapi/onboard — accepts FIEL + CSD multipart, orchestrates:
      1) sign_manifesto via PUT /v2/organizations/{id}/fiel (headless, no iframe)
      2) upload_csd via PUT /v2/organizations/{id}/certificate
      3) updates issuers DB with timestamps
  * GET /portal/api/facturapi/status — JSON poll for the page.
  * POST /portal/api/facturapi/upload-csd — legacy CSD-only upload (kept for compat).
  * POST /portal/api/facturapi/retry-provision — re-enqueue the provisioning job.
  * GET /portal/setup/manifiesto — legacy URL, 302 to /portal/setup/credenciales.

All routes require an authenticated portal session.
"""
from __future__ import annotations

import logging
import os

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

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

# Multipart upload size caps. Real CSDs and FIELes are tiny (1-3 KB).
# Cap generously at 50 KB to reject mistaken uploads of other files.
MAX_CSD_FILE_SIZE = 50 * 1024
MAX_FIEL_FILE_SIZE = 50 * 1024


def _mark_csd_uploaded(issuer_id: int) -> None:
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET csd_uploaded_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_manifest_signed(issuer_id: int) -> None:
    conn = db()
    try:
        conn.execute(
            "UPDATE issuers SET manifest_signed_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (issuer_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _save_ciec_password(issuer_id: int, ciec_password: str) -> None:
    """Encrypt and persist the CIEC (SAT portal password) on sat_credentials.

    INSERT-or-UPDATE so that uploading CIEC works whether or not the issuer
    has previously uploaded a FIEL via /portal/config/sat. The encryption is
    per-issuer (services.sat.crypto_at_rest), the same scheme used for FIEL
    passwords elsewhere in the codebase.
    """
    from services.sat.crypto_at_rest import encrypt_text
    enc = encrypt_text(issuer_id=int(issuer_id), plaintext=ciec_password)
    conn = db()
    try:
        existing = conn.execute(
            "SELECT id FROM sat_credentials WHERE issuer_id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sat_credentials SET ciec_password_encrypted = ?, updated_at = datetime('now') WHERE issuer_id = ?",
                (enc, issuer_id),
            )
        else:
            # Bare row with just CIEC; FIEL fields stay empty until the user
            # uploads them via the existing /portal/config/sat flow.
            conn.execute(
                """INSERT INTO sat_credentials
                   (issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, ciec_password_encrypted)
                   VALUES (?, '', '', '', ?)""",
                (issuer_id, enc),
            )
        conn.commit()
    finally:
        conn.close()


def _maybe_complete_onboarding(issuer_id: int) -> None:
    """If both CSD and manifest are done, stamp onboarding_completed_at."""
    conn = db()
    try:
        row = conn.execute(
            """SELECT csd_uploaded_at, manifest_signed_at, onboarding_completed_at
               FROM issuers WHERE id = ?""",
            (issuer_id,),
        ).fetchone()
        if not row:
            return
        d = dict(row) if hasattr(row, "keys") else dict(zip(row.keys(), row))
        if d.get("csd_uploaded_at") and d.get("manifest_signed_at") and not d.get("onboarding_completed_at"):
            conn.execute(
                "UPDATE issuers SET onboarding_completed_at = datetime('now') WHERE id = ?",
                (issuer_id,),
            )
            conn.commit()
    finally:
        conn.close()


def _validate_cert_pair_upload(cer: UploadFile, key: UploadFile, *, label: str, cer_bytes: bytes, key_bytes: bytes) -> None:
    """Shared validation for FIEL and CSD pairs. Raises HTTPException on failure."""
    for upload in (cer, key):
        name = (upload.filename or "").lower()
        ext_ok = name.endswith(".cer") if upload is cer else name.endswith(".key")
        if not ext_ok:
            raise HTTPException(status_code=400, detail=f"{label}: extensión inválida en {upload.filename}")
    if len(cer_bytes) > MAX_FIEL_FILE_SIZE or len(key_bytes) > MAX_FIEL_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"{label}: archivo demasiado grande")
    if len(cer_bytes) < 100 or len(key_bytes) < 100:
        raise HTTPException(status_code=400, detail=f"{label}: archivo vacío o corrupto")


def _read_issuer_facturapi_state(issuer_id: int) -> dict:
    """Returns full onboarding lifecycle state for the issuer."""
    conn = db()
    try:
        row = conn.execute(
            """SELECT facturapi_org_id, facturapi_provisioned_at,
                      manifest_signed_at, csd_uploaded_at, onboarding_completed_at
               FROM issuers WHERE id = ? LIMIT 1""",
            (issuer_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {
            "facturapi_org_id": None, "facturapi_provisioned_at": None,
            "manifest_signed_at": None, "csd_uploaded_at": None,
            "onboarding_completed_at": None,
        }
    return dict(row) if hasattr(row, "keys") else dict(zip(row.keys(), row))


def _ensure_state_with_org(issuer_id: int) -> dict:
    """Read state and, if `facturapi_org_id` is missing, provision it synchronously.

    This makes the Facturapi onboarding transparent to the user — they never see
    "still being created" because the org is created on-demand the first time
    they hit a flow that needs it. Idempotent; subsequent calls are free.

    Returns the state dict (with `facturapi_org_id` populated if provision
    succeeded, or None if Facturapi was unreachable — caller decides how to
    handle that case).
    """
    state = _read_issuer_facturapi_state(issuer_id)
    if state.get("facturapi_org_id"):
        return state
    try:
        from services.facturapi.provision import ensure_provisioned
        ensure_provisioned(issuer_id)
        # Re-read after provisioning so caller sees the updated state
        return _read_issuer_facturapi_state(issuer_id)
    except Exception as e:
        logger.warning(
            "On-demand provision failed for issuer=%s: %s", issuer_id, e
        )
        return state


def register_facturapi_setup_routes(router, templates):

    @router.get("/setup/credenciales")
    def portal_setup_credenciales(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        # On-demand provision: the onboarding screen renders with the org
        # already created, no "still being created" message ever shown.
        state = _ensure_state_with_org(issuer["id"])
        return render_portal(
            templates,
            request,
            issuer=issuer,
            template_name="portal_onboarding.html",
            active_page="setup_credenciales",
            title="Configurar facturación",
            facturapi_org_id=state.get("facturapi_org_id"),
            facturapi_provisioned_at=state.get("facturapi_provisioned_at"),
            manifest_signed_at=state.get("manifest_signed_at"),
            csd_uploaded_at=state.get("csd_uploaded_at"),
            onboarding_completed_at=state.get("onboarding_completed_at"),
        )

    @router.get("/setup/manifiesto")
    def portal_setup_manifiesto_redirect():
        """Legacy URL — 302 to the unified onboarding screen."""
        return RedirectResponse(url="/portal/setup/credenciales", status_code=302)

    @router.get("/api/facturapi/status")
    def portal_facturapi_status(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        # On-demand provision so the user never sees the "still being created"
        # state — by the time they hit settings, the org exists.
        state = _ensure_state_with_org(issuer["id"])
        return {
            "ok": True,
            "provisioned": bool(state.get("facturapi_org_id")),
            "org_id": state.get("facturapi_org_id"),
            "provisioned_at": state.get("facturapi_provisioned_at"),
            "manifest_signed": bool(state.get("manifest_signed_at")),
            "manifest_signed_at": state.get("manifest_signed_at"),
            "csd_uploaded": bool(state.get("csd_uploaded_at")),
            "csd_uploaded_at": state.get("csd_uploaded_at"),
            "onboarding_completed": bool(state.get("onboarding_completed_at")),
        }

    @router.post("/api/facturapi/onboard")
    async def portal_facturapi_onboard(
        request: Request,
        fiel_cer: UploadFile = File(...),
        fiel_key: UploadFile = File(...),
        fiel_password: str = Form(...),
        csd_cer: UploadFile = File(...),
        csd_key: UploadFile = File(...),
        csd_password: str = Form(...),
        csrf_token: str = Form(...),
        ciec_password: str = Form(""),
        fiscal_zip: str = Form(""),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Unified onboarding: FIEL + CSD + CP fiscal in one shot.

        Backend orchestrates:
          0) save fiscal_zip + push legal info to Facturapi (sets RFC/régimen/CP
             so the org leaves "test generic" and becomes live-ready)
          1) sign manifesto via PUT /v2/organizations/{id}/fiel (headless)
          2) upload CSD via PUT /v2/organizations/{id}/certificate
          3) update DB timestamps

        If step 1 fails, step 2 is skipped (manifesto required first).
        If step 2 fails, step 1 result is preserved (issuer is partial).
        """
        if not csrf_service.verify_csrf_token((csrf_token or "").strip()):
            raise HTTPException(status_code=400, detail="CSRF inválido")

        state = _ensure_state_with_org(issuer["id"])
        org_id = state.get("facturapi_org_id")
        if not org_id:
            raise HTTPException(
                status_code=502,
                detail="No pudimos preparar tu organización en Facturapi. Revisa tu conexión e intenta de nuevo en unos minutos.",
            )

        # Step 0: persist fiscal_zip and push legal info to Facturapi
        fiscal_zip = (fiscal_zip or "").strip()
        if fiscal_zip:
            if not fiscal_zip.isdigit() or len(fiscal_zip) != 5:
                raise HTTPException(status_code=400, detail="CP fiscal debe ser de 5 dígitos")
            conn = db()
            try:
                conn.execute(
                    "UPDATE issuers SET fiscal_zip = ?, updated_at = datetime('now') WHERE id = ?",
                    (fiscal_zip, issuer["id"]),
                )
                conn.commit()
            finally:
                conn.close()
        try:
            from services.facturapi.provision import push_legal_info_to_facturapi
            push_legal_info_to_facturapi(issuer["id"])
        except Exception as e:
            logger.warning("push_legal_info failed for issuer=%s: %s", issuer["id"], e)

        fiel_cer_bytes = await fiel_cer.read()
        fiel_key_bytes = await fiel_key.read()
        csd_cer_bytes = await csd_cer.read()
        csd_key_bytes = await csd_key.read()
        _validate_cert_pair_upload(fiel_cer, fiel_key, label="FIEL", cer_bytes=fiel_cer_bytes, key_bytes=fiel_key_bytes)
        _validate_cert_pair_upload(csd_cer, csd_key, label="CSD", cer_bytes=csd_cer_bytes, key_bytes=csd_key_bytes)

        fiel_password = (fiel_password or "").strip()
        csd_password = (csd_password or "").strip()
        if not fiel_password or not csd_password:
            raise HTTPException(status_code=400, detail="Contraseñas requeridas")

        # Step 1: sign manifesto with FIEL (the breakthrough endpoint)
        manifest_signed = False
        if not state.get("manifest_signed_at"):
            try:
                fpi_orgs.sign_manifesto(
                    org_id,
                    cer_bytes=fiel_cer_bytes,
                    key_bytes=fiel_key_bytes,
                    password=fiel_password,
                )
                _mark_manifest_signed(issuer["id"])
                manifest_signed = True
            except fpi_orgs.FacturapiOrgsError as e:
                logger.warning(
                    "Manifesto sign failed for issuer=%s org=%s: %s", issuer["id"], org_id, e
                )
                return JSONResponse(
                    status_code=400 if e.status in (400, 422) else 502,
                    content={
                        "ok": False,
                        "step": "manifesto",
                        "error": {"code": "MANIFESTO_SIGN_FAILED", "message": e.body},
                    },
                )
        else:
            manifest_signed = True

        # Step 2: upload CSD
        csd_uploaded = False
        if not state.get("csd_uploaded_at"):
            try:
                fpi_orgs.upload_csd(
                    org_id,
                    cer_bytes=csd_cer_bytes,
                    key_bytes=csd_key_bytes,
                    password=csd_password,
                )
                _mark_csd_uploaded(issuer["id"])
                csd_uploaded = True
            except fpi_orgs.FacturapiOrgsError as e:
                logger.warning(
                    "CSD upload failed for issuer=%s org=%s: %s", issuer["id"], org_id, e
                )
                return JSONResponse(
                    status_code=400 if e.status in (400, 422) else 502,
                    content={
                        "ok": False,
                        "step": "csd",
                        "error": {"code": "CSD_UPLOAD_FAILED", "message": e.body},
                        "manifest_signed": manifest_signed,
                    },
                )
        else:
            csd_uploaded = True

        # Optional CIEC — saves encrypted for future SAT portal features.
        # Doesn't block onboarding if it fails (best-effort).
        ciec_saved = False
        if (ciec_password or "").strip():
            try:
                _save_ciec_password(issuer["id"], ciec_password.strip())
                ciec_saved = True
            except Exception as e:
                logger.warning("CIEC save failed for issuer=%s: %s", issuer["id"], e)

        _maybe_complete_onboarding(issuer["id"])
        return {
            "ok": True,
            "manifest_signed": manifest_signed,
            "csd_uploaded": csd_uploaded,
            "ciec_saved": ciec_saved,
            "onboarding_completed": manifest_signed and csd_uploaded,
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

        state = _ensure_state_with_org(issuer["id"])
        org_id = state.get("facturapi_org_id")
        if not org_id:
            raise HTTPException(
                status_code=502,
                detail="No pudimos preparar tu organización en Facturapi. Revisa tu conexión e intenta de nuevo en unos minutos.",
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

        _mark_csd_uploaded(issuer["id"])
        _maybe_complete_onboarding(issuer["id"])
        return {"ok": True, "organization": result}

    @router.post("/api/facturapi/upload-fiel")
    async def portal_facturapi_upload_fiel(
        request: Request,
        cer_file: UploadFile = File(...),
        key_file: UploadFile = File(...),
        password: str = Form(...),
        csrf_token: str = Form(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Upload FIEL alone: signs the manifesto via the headless endpoint.

        Used by the per-card UI in /portal/settings. The unified /onboard
        endpoint still does FIEL+CSD together for the wizard flow.
        """
        if not csrf_service.verify_csrf_token((csrf_token or "").strip()):
            raise HTTPException(status_code=400, detail="CSRF inválido")
        state = _ensure_state_with_org(issuer["id"])
        org_id = state.get("facturapi_org_id")
        if not org_id:
            raise HTTPException(
                status_code=502,
                detail="No pudimos preparar tu organización en Facturapi. Revisa tu conexión e intenta de nuevo en unos minutos.",
            )
        cer_bytes = await cer_file.read()
        key_bytes = await key_file.read()
        _validate_cert_pair_upload(cer_file, key_file, label="FIEL",
                                   cer_bytes=cer_bytes, key_bytes=key_bytes)
        password = (password or "").strip()
        if not password:
            raise HTTPException(status_code=400, detail="Contraseña requerida")
        try:
            fpi_orgs.sign_manifesto(
                org_id, cer_bytes=cer_bytes, key_bytes=key_bytes, password=password,
            )
        except fpi_orgs.FacturapiOrgsError as e:
            logger.warning("FIEL upload failed issuer=%s: %s", issuer["id"], e)
            return JSONResponse(
                status_code=400 if e.status in (400, 422) else 502,
                content={"ok": False, "error": {"code": "FIEL_UPLOAD_FAILED", "message": e.body}},
            )
        _mark_manifest_signed(issuer["id"])
        _maybe_complete_onboarding(issuer["id"])
        return {"ok": True}

    @router.post("/api/facturapi/save-ciec")
    def portal_facturapi_save_ciec(
        request: Request,
        ciec_password: str = Form(...),
        csrf_token: str = Form(...),
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Save CIEC (SAT portal password) encrypted at rest."""
        if not csrf_service.verify_csrf_token((csrf_token or "").strip()):
            raise HTTPException(status_code=400, detail="CSRF inválido")
        ciec_password = (ciec_password or "").strip()
        if not ciec_password:
            raise HTTPException(status_code=400, detail="Contraseña requerida")
        try:
            _save_ciec_password(issuer["id"], ciec_password)
        except Exception as e:
            logger.exception("CIEC save failed issuer=%s: %s", issuer["id"], e)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": {"code": "CIEC_SAVE_FAILED", "message": str(e)}},
            )
        return {"ok": True}

    @router.get("/api/facturapi/refresh-manifesto-status")
    def portal_facturapi_refresh_manifesto_status(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
    ):
        """Poll Facturapi for current org state and mark manifest_signed_at in
        DB if the manifesto step is no longer pending. Frontend calls this
        every few seconds while the embedded Facturapi iframe is open.

        The manifesto signing is the only step we can't do programmatically —
        per Facturapi support, it's only available via their dashboard or the
        embedded iframe at https://www.facturapi.io/embedded/manifiesto.
        We detect completion by re-fetching org state.
        """
        state = _read_issuer_facturapi_state(issuer["id"])
        org_id = (state.get("facturapi_org_id") or "").strip()
        if not org_id:
            return {"ok": False, "error": "no_org"}

        try:
            org_data = fpi_orgs.get_organization(org_id)
        except Exception as e:
            logger.warning("refresh-manifesto-status: get_org failed issuer=%s: %s", issuer["id"], e)
            return {"ok": False, "error": "facturapi_unreachable"}

        pending_types = {s.get("type") for s in (org_data.get("pending_steps") or []) if isinstance(s, dict)}
        manifesto_pending = "manifiesto" in pending_types or "manifesto" in pending_types

        was_already_marked = bool(state.get("manifest_signed_at"))
        if not manifesto_pending and not was_already_marked:
            _mark_manifest_signed(issuer["id"])
            _maybe_complete_onboarding(issuer["id"])
            logger.info("Manifesto detected as signed for issuer=%s org=%s", issuer["id"], org_id)
            was_already_marked = True

        return {
            "ok": True,
            "manifesto_signed": (not manifesto_pending),
            "marked_in_db": was_already_marked,
            "pending_steps": sorted(pending_types),
            "is_production_ready": bool(org_data.get("is_production_ready")),
        }

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

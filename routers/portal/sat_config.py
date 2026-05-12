"""Portal sat_config routes."""
import logging
import os

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import (
    BASE_DIR,
    DB_PATH,
)
from database import db, has_column
from routers.deps import get_portal_issuer
from routers.portal._helpers import (
    render_portal,
)
from services import audit
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.auth import rate_limit as rate_limit_service
from services.billing import subscription as subscription_service
from services.errors import ExternalServiceError
from services.sat.sat_sync import get_month_totals, get_sat_sync_status
from services.sat.subprocess_utils import run_php

logger = logging.getLogger(__name__)

MAX_FIEL_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_CER = (".cer",)
ALLOWED_KEY = (".key",)

_get_month_totals = get_month_totals
_get_sat_sync_status = get_sat_sync_status


def _ensure_sat_credentials_validation_columns(conn) -> None:
    """Añade columnas validation_* a sat_credentials si no existen."""
    for col, col_type in [("validation_at", "TEXT"), ("validation_ok", "INTEGER"), ("validation_message", "TEXT")]:
        if not has_column(conn, "sat_credentials", col):
            conn.execute(f"ALTER TABLE sat_credentials ADD COLUMN {col} {col_type};")


def _credentials_dir(issuer_id: int) -> str:
    """Ruta al directorio storage/credentials/{issuer_id}/ (creado si no existe)."""
    path = os.path.join(BASE_DIR, "storage", "credentials", str(issuer_id))
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _run_fiel_validation(issuer_id: int) -> tuple:
    """Ejecuta check_fiel.php para issuer_id, actualiza sat_credentials y devuelve (ok, message)."""
    php_script = os.path.join(BASE_DIR, "sat_sync", "check_fiel.php")
    if not os.path.isfile(php_script):
        return False, "No se encontró el script de validación."
    env = os.environ.copy()
    env["APP_DB_PATH"] = str(DB_PATH)
    stdout = ""
    try:
        from services.sat.sat_credentials_secure import decrypted_fiel_env
        with decrypted_fiel_env(int(issuer_id)) as fiel_env:
            env.update(fiel_env)
            stdout, stderr = run_php(
                [php_script, str(issuer_id)],
                timeout=30,
                cwd=BASE_DIR,
                env=env,
            )
        ok = True
        message = (stdout or "").strip() or "FIEL validada correctamente."
    except ExternalServiceError as e:
        ok = False
        message = (e.internal_message or e.public_message or "Error al validar la FIEL.").strip()
    conn = db()
    try:
        _ensure_sat_credentials_validation_columns(conn)
        if has_column(conn, "sat_credentials", "validation_at"):
            conn.execute(
                """
                UPDATE sat_credentials SET validation_at = datetime('now'), validation_ok = ?, validation_message = ?
                WHERE issuer_id = ?
                """,
                (1 if ok else 0, message[:500], issuer_id),
            )
            conn.commit()
        if ok and stdout:
            cert_rfc = ""
            cert_name = ""
            for line in stdout.splitlines():
                if line.startswith("CERT_RFC="):
                    cert_rfc = line[len("CERT_RFC="):].strip()
                elif line.startswith("CERT_NAME="):
                    cert_name = line[len("CERT_NAME="):].strip()
            if cert_rfc:
                current = conn.execute(
                    "SELECT rfc, razon_social FROM issuers WHERE id = ?", (issuer_id,)
                ).fetchone()
                if current:
                    cur_rfc = (current["rfc"] if isinstance(current, dict) else current[0]) or ""
                    cur_name = (current["razon_social"] if isinstance(current, dict) else current[1]) or ""
                    updates = []
                    params = []
                    if not cur_rfc or cur_rfc == "PENDIENTE":
                        updates.append("rfc = ?")
                        params.append(cert_rfc.upper())
                    if cert_name and (not cur_name or cur_name.startswith("PENDIENTE") or "@" in cur_name):
                        updates.append("razon_social = ?")
                        params.append(cert_name)
                    if updates:
                        updates.append("updated_at = datetime('now')")
                        params.append(issuer_id)
                        conn.execute(
                            f"UPDATE issuers SET {', '.join(updates)} WHERE id = ?",
                            tuple(params),
                        )
                        conn.commit()
                        logger.info(
                            "Auto-filled issuer %s from FIEL cert: rfc=%s name=%s",
                            issuer_id, cert_rfc, cert_name,
                        )
    finally:
        conn.close()
    return ok, message


def register_sat_config_routes(router, templates):
    """Register Sat Config routes on the portal router."""

    def _render_portal(request, **kwargs):
        return render_portal(templates, request, **kwargs)

    @router.post("/sat/sync", response_class=JSONResponse)
    def portal_sat_sync(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Encola sincronización SAT (issued + received). Requiere FIEL configurada y validada."""
        if rate_limit_service.is_rate_limited(request, "sat_sync"):
            return JSONResponse({"ok": False, "message": "Demasiados intentos. Espera un minuto."}, status_code=429)
        issuer_id = issuer["id"]
        user_id = getattr(request.state, "user_id", 0) or 0
        if not subscription_service.can_issuer_use_sync_and_timbrado(issuer_id, user_id):
            return JSONResponse(
                {"ok": False, "message": "Tu periodo de prueba ha terminado. Actualiza tu plan para seguir sincronizando."},
                status_code=402,
            )
        conn = db()
        try:
            _ensure_sat_credentials_validation_columns(conn)
            cred = conn.execute(
                "SELECT validation_ok FROM sat_credentials WHERE issuer_id = ?",
                (issuer_id,),
            ).fetchone()
            if not cred:
                return JSONResponse({"ok": False, "message": "Configura y valida tu FIEL en Ajustes primero."}, status_code=400)
            if cred["validation_ok"] != 1:
                return JSONResponse({"ok": False, "message": "Valida tu FIEL en Ajustes antes de sincronizar."}, status_code=400)
            # No encolar si ya hay jobs en cola o en ejecución para este issuer
            pending = conn.execute(
                "SELECT 1 FROM sat_jobs WHERE issuer_id = ? AND status IN ('queued','running') LIMIT 1",
                (issuer_id,),
            ).fetchone()
            if pending:
                return JSONResponse({"ok": False, "message": "Ya hay una sincronización en curso. Espera a que termine."}, status_code=409)
            conn.execute(
                """
                INSERT INTO sat_jobs (issuer_id, job_type, direction, status, created_at, updated_at)
                VALUES (?, 'xml', 'issued', 'queued', datetime('now'), datetime('now')),
                       (?, 'xml', 'received', 'queued', datetime('now'), datetime('now'))
                """,
                (issuer_id, issuer_id),
            )
            conn.commit()
        finally:
            conn.close()
        # Auditoría: inicio de sync SAT
        audit.log(
            action="sat_sync_started",
            user_id=user_id,
            issuer_id=issuer_id,
            request=request,
            entity="sat_jobs",
            entity_id=str(issuer_id),
        )
        log_action(request, "sat_sync_started", user_id=user_id, issuer_id=issuer_id)
        return JSONResponse({"ok": True, "message": "Sincronización iniciada."})

    @router.get("/sat/status", response_class=JSONResponse)
    def portal_sat_status(request: Request, issuer: dict = Depends(get_portal_issuer)):
        """Estado del sync SAT para este issuer: último sync, en proceso / ok / error."""
        issuer_id = issuer["id"]
        conn = db()
        try:
            running = conn.execute(
                "SELECT 1 FROM sat_jobs WHERE issuer_id = ? AND status IN ('queued','running') LIMIT 1",
                (issuer_id,),
            ).fetchone()
            last_ok = conn.execute(
                "SELECT MAX(finished_at) AS t FROM sat_jobs WHERE issuer_id = ? AND status = 'ok'",
                (issuer_id,),
            ).fetchone()
            last_error = conn.execute(
                "SELECT finished_at, last_error FROM sat_jobs WHERE issuer_id = ? AND status = 'error' ORDER BY finished_at DESC LIMIT 1",
                (issuer_id,),
            ).fetchone()
            sync_state = conn.execute(
                "SELECT MAX(last_run_at) AS t FROM sat_sync_state WHERE issuer_id = ?",
                (issuer_id,),
            ).fetchone()
        finally:
            conn.close()
        last_sync_at = (sync_state and sync_state["t"]) or (last_ok and last_ok["t"]) or None
        if running:
            status = "running"
            message = "Sincronización en proceso"
        elif last_error and last_ok and last_error["t"] and last_ok["t"] and last_error["t"] > last_ok["t"]:
            status = "error"
            message = (last_error["last_error"] or "Error en la última sincronización")[:200]
        elif last_error and not last_ok:
            status = "error"
            message = (last_error["last_error"] or "Error en la última sincronización")[:200]
        else:
            status = "ok"
            message = None
        return JSONResponse({
            "ok": True,
            "last_sync_at": last_sync_at,
            "status": status,
            "message": message,
        })

    @router.get("/config/sat", response_class=HTMLResponse)
    def portal_config_sat(request: Request, issuer: dict = Depends(get_portal_issuer)):
        issuer_id = issuer["id"]
        conn = db()
        try:
            _ensure_sat_credentials_validation_columns(conn)
            row = conn.execute(
                "SELECT fiel_cer_path, fiel_key_path, validation_at, validation_ok, validation_message FROM sat_credentials WHERE issuer_id = ?",
                (issuer_id,),
            ).fetchone()
        finally:
            conn.close()
        cred = dict(row) if row else None
        return _render_portal(
            request,
            issuer=issuer,
            template_name="portal_config_sat.html",
            active_page="config_sat",
            title="FIEL / Credenciales SAT",
            extra={
                "sat_cred": cred,
                "has_fiel": cred is not None,
                "validation_at": cred.get("validation_at") if cred else None,
                "validation_ok": cred.get("validation_ok") if cred else None,
                "validation_message": cred.get("validation_message") if cred else None,
            },
        )

    @router.post("/config/sat")
    async def portal_config_sat_save(
        request: Request,
        issuer: dict = Depends(get_portal_issuer),
        fiel_cer: UploadFile = File(...),
        fiel_key: UploadFile = File(...),
        fiel_password: str = Form(""),
        csrf_token: str | None = Form(None),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        if rate_limit_service.is_rate_limited(request, "upload"):
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera un minuto.")
        issuer_id = issuer["id"]
        # Validar extensiones
        cer_name = (fiel_cer.filename or "").lower()
        key_name = (fiel_key.filename or "").lower()
        if not any(cer_name.endswith(e) for e in ALLOWED_CER):
            raise HTTPException(status_code=400, detail="El archivo del certificado debe ser .cer")
        if not any(key_name.endswith(e) for e in ALLOWED_KEY):
            raise HTTPException(status_code=400, detail="El archivo de la clave debe ser .key")
        if not (fiel_password and fiel_password.strip()):
            raise HTTPException(status_code=400, detail="La contraseña FIEL es obligatoria")
        cer_body = await fiel_cer.read()
        key_body = await fiel_key.read()
        if len(cer_body) > MAX_FIEL_SIZE or len(key_body) > MAX_FIEL_SIZE:
            raise HTTPException(status_code=400, detail="Cada archivo debe medir como máximo 2 MB")
        cred_dir = _credentials_dir(issuer_id)
        # Cifrado at-rest: guardar solo blobs cifrados (AES-GCM). Nunca persistir .cer/.key en claro.
        cer_enc_path = os.path.join(cred_dir, "fiel.cer.enc")
        key_enc_path = os.path.join(cred_dir, "fiel.key.enc")
        rel_cer = f"storage/credentials/{issuer_id}/fiel.cer.enc"
        rel_key = f"storage/credentials/{issuer_id}/fiel.key.enc"
        from services.sat.crypto_at_rest import encrypt_bytes, encrypt_text

        cer_blob = encrypt_bytes(issuer_id=int(issuer_id), plaintext=cer_body, aad=b"fiel.cer")
        key_blob = encrypt_bytes(issuer_id=int(issuer_id), plaintext=key_body, aad=b"fiel.key")
        with open(cer_enc_path, "wb") as f:
            f.write(cer_blob)
        with open(key_enc_path, "wb") as f:
            f.write(key_blob)
        os.chmod(cer_enc_path, 0o600)
        os.chmod(key_enc_path, 0o600)
        # Guardar contraseña tal cual (sin strip) para evitar que espacios válidos rompan el descifrado,
        # pero cifrada en DB.
        password_plain = fiel_password if fiel_password is not None else ""
        password = encrypt_text(issuer_id=int(issuer_id), plaintext=password_plain)
        conn = db()
        try:
            _ensure_sat_credentials_validation_columns(conn)
            conn.execute(
                """
                INSERT INTO sat_credentials (issuer_id, fiel_cer_path, fiel_key_path, fiel_key_password, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(issuer_id) DO UPDATE SET
                    fiel_cer_path = excluded.fiel_cer_path,
                    fiel_key_path = excluded.fiel_key_path,
                    fiel_key_password = excluded.fiel_key_password,
                    updated_at = datetime('now')
                """,
                (issuer_id, rel_cer, rel_key, password),
            )
            conn.commit()
        finally:
            conn.close()
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(action="credentials_uploaded", user_id=uid, issuer_id=issuer_id, request=request, entity="sat_credentials", entity_id=str(issuer_id))
        log_action(request, "credentials_uploaded", issuer_id=issuer_id)
        # Validación post-upload: ejecutar check_fiel y persistir estado para mostrar en UI
        valid_ok, valid_message = _run_fiel_validation(issuer_id)
        audit.log(action="credentials_validated", user_id=uid, issuer_id=issuer_id, request=request, entity="sat_credentials", entity_id=str(issuer_id), details=f"ok={valid_ok}")
        log_action(request, "credentials_validated", issuer_id=issuer_id)
        # Auto-enqueue initial SAT sync on successful credential validation
        if valid_ok:
            try:
                from services.sat.sat_autosync import enqueue_onboarding_sync
                enqueue_onboarding_sync(issuer_id)
                logger.info("Onboarding SAT sync enqueued for issuer %s", issuer_id)
            except Exception:
                logger.exception("Failed to enqueue onboarding sync for issuer %s", issuer_id)
        if request.headers.get("accept", "").find("application/json") >= 0:
            msg = "Credenciales guardadas. Tus facturas de los últimos 2 meses se descargarán en ~5 minutos." if valid_ok else "Credenciales guardadas."
            return JSONResponse({"ok": True, "message": msg, "validation_ok": valid_ok, "validation_message": valid_message})
        return RedirectResponse(url="/portal/config/sat?saved=1", status_code=302)

    @router.post("/config/sat/validate", response_class=JSONResponse)
    def portal_config_sat_validate(request: Request, issuer: dict = Depends(get_portal_issuer)):
        if rate_limit_service.is_rate_limited(request, "validate"):
            return JSONResponse({"ok": False, "message": "Demasiados intentos. Espera un minuto."}, status_code=429)
        issuer_id = issuer["id"]
        ok, message = _run_fiel_validation(issuer_id)
        if not message:
            message = "FIEL válida." if ok else "Error al validar la FIEL."
        uid = getattr(request.state, "user_id", None) or 0
        audit.log(action="credentials_validated", user_id=uid, issuer_id=issuer_id, request=request, entity="sat_credentials", entity_id=str(issuer_id), details=f"ok={ok}")
        log_action(request, "credentials_validated", issuer_id=issuer_id)
        return JSONResponse({"ok": ok, "message": message})


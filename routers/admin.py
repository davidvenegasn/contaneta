"""Rutas solo admin/owner: dashboard, listas, impersonación con auditoría, ops."""
import os
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from config import DB_PATH
from database import db, db_rows
from migrations_runner import apply_migrations
from services import session, issuers, users, audit


def _get_session_user_and_issuer(request: Request) -> tuple[int, int, int | None]:
    """Obtiene (user_id, issuer_id, restore_issuer_id) de la cookie. Lanza 403 si no hay sesión válida."""
    cookie_val = request.cookies.get(session.get_session_cookie_name())
    data = session.verify_session(cookie_val)
    if not data or data[0] <= 0:
        raise HTTPException(status_code=403, detail="Solo usuarios autenticados")
    user_id, issuer_id = data[0], data[1]
    restore_issuer_id = data[2] if len(data) >= 3 else None
    return user_id, issuer_id, restore_issuer_id


def require_admin(request: Request) -> tuple[int, int, int | None]:
    """Dependency: exige sesión válida y rol admin. Devuelve (user_id, issuer_id, restore_issuer_id)."""
    user_id, issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
    if not users.user_has_admin_role(user_id):
        raise HTTPException(status_code=403, detail="Solo administradores pueden usar esta acción")
    return user_id, issuer_id, restore_issuer_id


def require_admin_or_owner(request: Request) -> tuple[int, int, int | None]:
    """Dependency: exige sesión válida y rol admin u owner. Devuelve (user_id, issuer_id, restore_issuer_id)."""
    user_id, issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
    if not users.user_has_admin_or_owner_role(user_id):
        raise HTTPException(status_code=403, detail="Solo administradores u owners pueden acceder al panel admin")
    return user_id, issuer_id, restore_issuer_id


def get_admin_router(templates):
    """Construye el router de admin con rutas HTML y acciones. Requiere Jinja2 templates."""

    router = APIRouter(prefix="/admin", tags=["admin"])

    def _ym_now():
        return datetime.now().strftime("%Y-%m")

    # ---------- GET: Dashboard ----------
    @router.get("", response_class=HTMLResponse)
    def admin_dashboard(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        ym = _ym_now()
        count_users = db_rows("SELECT COUNT(*) AS n FROM users")
        count_issuers = db_rows("SELECT COUNT(*) AS n FROM issuers")
        count_memberships = db_rows("SELECT COUNT(*) AS n FROM memberships")
        sat_cfdi_by_direction = db_rows(
            """SELECT direction, COUNT(*) AS n FROM sat_cfdi
               WHERE fecha_emision IS NOT NULL AND substr(fecha_emision, 1, 7) = ?
               GROUP BY direction""",
            (ym,),
        )
        sat_requests_by_status = db_rows(
            "SELECT status, COUNT(*) AS n FROM sat_requests GROUP BY status"
        )
        audit_events = db_rows(
            "SELECT id, created_at, action, user_id, issuer_id, target_issuer_id, details FROM audit_log ORDER BY id DESC LIMIT 20"
        )
        return templates.TemplateResponse(
            "admin_dashboard.html",
            {
                "request": request,
                "active_page": "dashboard",
                "count_users": count_users[0]["n"] if count_users else 0,
                "count_issuers": count_issuers[0]["n"] if count_issuers else 0,
                "count_memberships": count_memberships[0]["n"] if count_memberships else 0,
                "sat_cfdi_by_direction": sat_cfdi_by_direction,
                "sat_requests_by_status": sat_requests_by_status,
                "audit_events": audit_events,
            },
        )

    # ---------- GET: Users ----------
    @router.get("/users", response_class=HTMLResponse)
    def admin_users(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        rows = db_rows(
            """SELECT u.id, u.email, u.name, u.created_at,
                      (SELECT m.role FROM memberships m WHERE m.user_id = u.id
                       ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 WHEN 'accountant' THEN 3 ELSE 4 END
                       LIMIT 1) AS max_role
               FROM users u ORDER BY u.id"""
        )
        for r in rows:
            if r.get("max_role") is None:
                r["max_role"] = "-"
        return templates.TemplateResponse(
            "admin_users.html",
            {"request": request, "active_page": "users", "users": rows},
        )

    # ---------- GET: Issuers ----------
    @router.get("/issuers", response_class=HTMLResponse)
    def admin_issuers(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        rows = db_rows(
            """SELECT id, rfc, razon_social, regimen_fiscal, active, facturapi_org_id
               FROM issuers ORDER BY id"""
        )
        return templates.TemplateResponse(
            "admin_issuers.html",
            {"request": request, "active_page": "issuers", "issuers": rows},
        )

    # ---------- GET: Memberships ----------
    @router.get("/memberships", response_class=HTMLResponse)
    def admin_memberships(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        rows = db_rows(
            """SELECT m.user_id, m.issuer_id, m.role, m.created_at,
                      u.email AS user_email, i.rfc AS issuer_rfc
               FROM memberships m
               LEFT JOIN users u ON u.id = m.user_id
               LEFT JOIN issuers i ON i.id = m.issuer_id
               ORDER BY m.id"""
        )
        return templates.TemplateResponse(
            "admin_memberships.html",
            {"request": request, "active_page": "memberships", "memberships": rows},
        )

    # ---------- GET: Admin status/health (conteos) ----------
    @router.get("/status", response_class=HTMLResponse)
    @router.get("/health", response_class=HTMLResponse)
    def admin_status(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        n_users = 0
        n_issuers = 0
        cfdi_by_status: list[dict] = []
        jobs_pending = 0
        try:
            r = db_rows("SELECT COUNT(*) AS n FROM users")
            n_users = r[0]["n"] if r else 0
        except Exception:
            pass
        try:
            r = db_rows("SELECT COUNT(*) AS n FROM issuers")
            n_issuers = r[0]["n"] if r else 0
        except Exception:
            pass
        try:
            cfdi_by_status = db_rows(
                "SELECT COALESCE(status, 'null') AS status, COUNT(*) AS n FROM sat_cfdi GROUP BY status"
            )
        except Exception:
            pass
        try:
            r = db_rows(
                "SELECT COUNT(*) AS n FROM sat_jobs WHERE status IN ('queued', 'running')"
            )
            jobs_pending = r[0]["n"] if r else 0
        except Exception:
            pass
        status_rows = "".join(
            f'<tr><td>{row["status"]}</td><td>{row["n"]}</td></tr>'
            for row in cfdi_by_status
        ) or "<tr><td colspan=\"2\">—</td></tr>"
        html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"/><title>Admin Status</title>
<style>
  body {{ font-family: system-ui,sans-serif; margin: 24px; background: #f8fafc; }}
  .card {{ max-width: 520px; background: #fff; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  h1 {{ margin: 0 0 16px; font-size: 1.25rem; }}
  .row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e2e8f0; }}
  table {{ width: 100%; margin-top: 12px; border-collapse: collapse; }}
  th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
  a {{ color: #0369a1; }}
</style>
</head>
<body>
  <div class="card">
    <h1>Estado del sistema (admin)</h1>
    <div class="row"><span>Usuarios</span><strong>{n_users}</strong></div>
    <div class="row"><span>Issuers</span><strong>{n_issuers}</strong></div>
    <div class="row"><span>Jobs pendientes (queued/running)</span><strong>{jobs_pending}</strong></div>
    <h2 style="font-size:1rem; margin-top:16px;">CFDI por estado</h2>
    <table><thead><tr><th>Estado</th><th>Cantidad</th></tr></thead><tbody>{status_rows}</tbody></table>
    <p style="margin-top:16px;"><a href="/admin">Volver al panel admin</a></p>
  </div>
</body>
</html>"""
        return HTMLResponse(html)

    # ---------- GET / POST: Ops ----------
    @router.get("/ops", response_class=HTMLResponse)
    def admin_ops_get(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        return templates.TemplateResponse(
            "admin_ops.html",
            {"request": request, "active_page": "ops", "message": None, "result": None},
        )

    @router.post("/ops", response_class=HTMLResponse)
    def admin_ops_post(
        request: Request,
        action: str = Form(...),
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        user_id, issuer_id, _ = _admin
        result_text = ""
        message_ok = True

        if action == "migrations":
            try:
                apply_migrations(DB_PATH)
                result_text = "Migraciones aplicadas correctamente."
                audit.log(
                    action="admin_ops",
                    user_id=user_id,
                    issuer_id=issuer_id,
                    details=f"action=migrations result=ok",
                )
            except Exception as e:
                result_text = str(e)
                message_ok = False
                audit.log(
                    action="admin_ops",
                    user_id=user_id,
                    issuer_id=issuer_id,
                    details=f"action=migrations result=error {result_text}",
                )

        elif action == "verify_db":
            try:
                lines = []
                conn = db()
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [r[0] for r in cur.fetchall()]
                lines.append("Tablas: " + ", ".join(tables))
                if "schema_migrations" in tables:
                    cur = conn.execute(
                        "SELECT version, applied_at FROM schema_migrations ORDER BY version"
                    )
                    for r in cur.fetchall():
                        lines.append(f"  migration {r[0]} @ {r[1]}")
                conn.close()
                result_text = "\n".join(lines)
                audit.log(
                    action="admin_ops",
                    user_id=user_id,
                    issuer_id=issuer_id,
                    details="action=verify_db result=ok",
                )
            except Exception as e:
                result_text = str(e)
                message_ok = False
                audit.log(
                    action="admin_ops",
                    user_id=user_id,
                    issuer_id=issuer_id,
                    details=f"action=verify_db result=error {result_text}",
                )

        elif action == "backup":
            base_dir = Path(__file__).resolve().parent.parent
            script_db = base_dir / "scripts" / "backup_db.sh"
            script_storage = base_dir / "scripts" / "backup_storage_xml.sh"
            env = os.environ.copy()
            env.setdefault("APP_DB_PATH", DB_PATH)
            try:
                out = []
                if script_db.exists():
                    r = subprocess.run(
                        [str(script_db)],
                        capture_output=True,
                        text=True,
                        cwd=str(base_dir),
                        env=env,
                        timeout=60,
                    )
                    out.append(r.stdout or "")
                    if r.stderr:
                        out.append(r.stderr)
                    if r.returncode != 0:
                        out.append(f"Exit code: {r.returncode}")
                else:
                    out.append("scripts/backup_db.sh no encontrado")
                if script_storage.exists():
                    r2 = subprocess.run(
                        [str(script_storage)],
                        capture_output=True,
                        text=True,
                        cwd=str(base_dir),
                        env=env,
                        timeout=120,
                    )
                    out.append(r2.stdout or "")
                    if r2.stderr:
                        out.append(r2.stderr)
                    if r2.returncode != 0:
                        out.append(f"backup_storage exit: {r2.returncode}")
                result_text = "\n".join(out).strip() or "Backup ejecutado."
                audit.log(
                    action="admin_ops",
                    user_id=user_id,
                    issuer_id=issuer_id,
                    details=f"action=backup result=ok",
                )
            except Exception as e:
                result_text = str(e)
                message_ok = False
                audit.log(
                    action="admin_ops",
                    user_id=user_id,
                    issuer_id=issuer_id,
                    details=f"action=backup result=error {result_text}",
                )
        else:
            result_text = f"Acción desconocida: {action}"
            message_ok = False

        return templates.TemplateResponse(
            "admin_ops.html",
            {
                "request": request,
                "active_page": "ops",
                "message": "Listo." if message_ok else "Error (ver resultado).",
                "message_ok": message_ok,
                "result": result_text,
            },
        )

    # ---------- Impersonate (JSON body, API) ----------
    from pydantic import BaseModel

    class ImpersonateBody(BaseModel):
        issuer_id: int | None = None
        rfc: str | None = None

    def _do_impersonate(request: Request, user_id: int, current_issuer_id: int, target_issuer_id: int | None, rfc: str | None):
        target_issuer = None
        if target_issuer_id is not None:
            target_issuer = issuers.get_issuer_by_id(target_issuer_id)
        if target_issuer is None and rfc:
            target_issuer = issuers.get_issuer_by_rfc((rfc or "").strip())
        if not target_issuer:
            raise HTTPException(status_code=400, detail="Issuer no encontrado (issuer_id o rfc válido)")
        ip = (request.client.host if request.client else None) or ""
        ua = request.headers.get("user-agent") or ""
        details = f"admin user_id={user_id} impersonating issuer_id={target_issuer['id']} ip={ip} user_agent={ua[:200]}"
        audit.log(
            action="impersonate",
            user_id=user_id,
            issuer_id=current_issuer_id,
            target_issuer_id=target_issuer["id"],
            details=details,
        )
        cookie_val = session.sign_session(
            user_id,
            target_issuer["id"],
            restore_issuer_id=current_issuer_id,
        )
        response = RedirectResponse(url="/portal/home", status_code=302)
        response.set_cookie(
            session.get_session_cookie_name(),
            cookie_val,
            **session.session_cookie_params(request),
        )
        return response

    @router.post("/impersonate")
    def admin_impersonate(
        request: Request,
        body: ImpersonateBody,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, body.issuer_id, body.rfc)

    @router.post("/impersonate-form", response_class=RedirectResponse)
    def admin_impersonate_form(
        request: Request,
        issuer_id: int | None = Form(None),
        rfc: str | None = Form(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, issuer_id, rfc)

    @router.post("/stop-impersonate")
    def admin_stop_impersonate(request: Request):
        user_id, _current_issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
        if restore_issuer_id is None:
            raise HTTPException(status_code=400, detail="No estás en modo impersonación")
        audit.log(
            action="stop_impersonate",
            user_id=user_id,
            issuer_id=_current_issuer_id,
            target_issuer_id=restore_issuer_id,
            details=f"user_id={user_id} stopped impersonating, restored to issuer_id={restore_issuer_id}",
        )
        cookie_val = session.sign_session(user_id, restore_issuer_id, restore_issuer_id=None)
        response = RedirectResponse(url="/portal/home", status_code=302)
        response.set_cookie(
            session.get_session_cookie_name(),
            cookie_val,
            **session.session_cookie_params(request),
        )
        return response

    return router

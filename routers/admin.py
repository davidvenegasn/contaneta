"""Rutas solo admin/owner: dashboard, listas, impersonación con auditoría, ops."""
import json
import os
import secrets
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config import DB_PATH
from database import db, db_rows, has_column
from migrations_runner import apply_migrations
from services import session, issuers, users, audit, csrf as csrf_service, error_events as error_events_service
from services.action_log import log_action
from services import admin_issuer as admin_issuer_service

basic_auth = HTTPBasic(auto_error=False)


def _get_session_user_and_issuer(request: Request) -> tuple[int, int, int | None]:
    """Obtiene (user_id, issuer_id, restore_issuer_id) de la cookie. Lanza 403 si no hay sesión válida."""
    cookie_val = request.cookies.get(session.get_session_cookie_name())
    data = session.verify_session(cookie_val)
    if not data or data[0] <= 0:
        raise HTTPException(status_code=403, detail="Solo usuarios autenticados")
    user_id, issuer_id = data[0], data[1]
    restore_issuer_id = data[2] if len(data) >= 3 else None
    return user_id, issuer_id, restore_issuer_id


def _require_basic_if_configured(credentials: HTTPBasicCredentials | None) -> None:
    pw = (os.getenv("ADMIN_PASSWORD") or "").strip()
    if not pw:
        return
    if credentials is None or not secrets.compare_digest((credentials.password or ""), pw):
        raise HTTPException(
            status_code=401,
            detail="BasicAuth requerido",
            headers={"WWW-Authenticate": "Basic"},
        )


def require_admin(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic_auth)) -> tuple[int, int, int | None]:
    """Dependency: exige sesión válida y rol admin. Devuelve (user_id, issuer_id, restore_issuer_id)."""
    _require_basic_if_configured(credentials)
    user_id, issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
    if not users.user_has_admin_role(user_id):
        raise HTTPException(status_code=403, detail="Solo administradores pueden usar esta acción")
    return user_id, issuer_id, restore_issuer_id


def require_admin_or_owner(request: Request, credentials: HTTPBasicCredentials | None = Depends(basic_auth)) -> tuple[int, int, int | None]:
    """Dependency: exige sesión válida y rol admin u owner. Devuelve (user_id, issuer_id, restore_issuer_id)."""
    _require_basic_if_configured(credentials)
    user_id, issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
    if not users.user_has_admin_or_owner_role(user_id):
        raise HTTPException(status_code=403, detail="Solo administradores u owners pueden acceder al panel admin")
    return user_id, issuer_id, restore_issuer_id


def get_admin_router(templates):
    """Construye el router de admin con rutas HTML y acciones. Requiere Jinja2 templates."""

    router = APIRouter(prefix="/admin", tags=["admin"])

    def _ym_now():
        return datetime.now().strftime("%Y-%m")

    def _ops_observability_context() -> dict:
        try:
            error_events = error_events_service.list_error_events(limit=50)
        except Exception:
            error_events = []
        try:
            jobs_recent = db_rows(
                """
                SELECT id, issuer_id, name, status, progress, message, created_at, updated_at
                FROM jobs
                ORDER BY id DESC
                LIMIT 50
                """
            )
        except Exception:
            jobs_recent = []
        try:
            sat_recent = db_rows(
                """
                SELECT id, issuer_id, status, started_at, finished_at, last_error
                FROM sat_jobs
                ORDER BY id DESC
                LIMIT 20
                """
            )
        except Exception:
            sat_recent = []
        return {"error_events": error_events, "jobs_recent": jobs_recent, "sat_recent": sat_recent}

    # ---------- GET: Dashboard ----------
    def _render_dashboard(request: Request, _admin: tuple[int, int, int | None]):
        ym = _ym_now()
        count_users = db_rows("SELECT COUNT(*) AS n FROM users")
        count_issuers = db_rows("SELECT COUNT(*) AS n FROM issuers")
        count_memberships = db_rows("SELECT COUNT(*) AS n FROM memberships")
        active_users = db_rows("SELECT COUNT(DISTINCT user_id) AS n FROM memberships")
        jobs_in_queue = db_rows("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running')")
        jobs_failed_today = db_rows("SELECT COUNT(*) AS n FROM jobs WHERE status = 'failed' AND date(updated_at) = date('now')")
        last_logins = db_rows(
            """
            SELECT al.created_at, al.user_id, u.email AS user_email, al.issuer_id, i.rfc AS issuer_rfc
            FROM audit_log al
            LEFT JOIN users u ON u.id = al.user_id
            LEFT JOIN issuers i ON i.id = al.issuer_id
            WHERE al.action = 'login'
            ORDER BY al.id DESC
            LIMIT 20
            """
        )
        errors_today = 0
        try:
            # asegurar tabla si aún no existe
            error_events_service.list_error_events(limit=1)
            r = db_rows("SELECT COUNT(*) AS n FROM error_events WHERE date(created_at) = date('now')")
            errors_today = r[0]["n"] if r else 0
        except Exception:
            errors_today = 0

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
            """SELECT id, created_at, action, user_id, issuer_id, target_issuer_id, details,
                      entity, entity_id, meta_json, ip, user_agent FROM audit_log ORDER BY id DESC LIMIT 20"""
        )
        return templates.TemplateResponse(
            "admin_dashboard.html",
            {
                "request": request,
                "active_page": "dashboard",
                "count_users": count_users[0]["n"] if count_users else 0,
                "count_issuers": count_issuers[0]["n"] if count_issuers else 0,
                "count_memberships": count_memberships[0]["n"] if count_memberships else 0,
                "count_active_users": active_users[0]["n"] if active_users else 0,
                "jobs_in_queue": jobs_in_queue[0]["n"] if jobs_in_queue else 0,
                "jobs_failed_today": jobs_failed_today[0]["n"] if jobs_failed_today else 0,
                "errors_today": errors_today,
                "last_logins": last_logins,
                "sat_cfdi_by_direction": sat_cfdi_by_direction,
                "sat_requests_by_status": sat_requests_by_status,
                "audit_events": audit_events,
            },
        )

    @router.get("", response_class=HTMLResponse)
    def admin_dashboard(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        return _render_dashboard(request, _admin)

    @router.get("/dashboard", response_class=HTMLResponse)
    def admin_dashboard_alias(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        return _render_dashboard(request, _admin)

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

    # ---------- GET: Issuers (con búsqueda RFC/email) ----------
    @router.get("/issuers", response_class=HTMLResponse)
    def admin_issuers(
        request: Request,
        q: str | None = None,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        user_id, _, _ = _admin
        can_impersonate = users.user_has_admin_role(user_id)
        search = (q or "").strip()
        # asegurar tabla error_events para subqueries (si aún no existe)
        try:
            error_events_service.list_error_events(limit=1)
        except Exception:
            pass

        conn = db()
        try:
            has_trial = has_column(conn, "issuers", "trial_expires_at")
        finally:
            conn.close()
        trial_col = "i.trial_expires_at" if has_trial else "NULL AS trial_expires_at"

        if search:
            like = f"%{search}%"
            rows = db_rows(
                f"""SELECT i.id, i.rfc, i.razon_social, i.regimen_fiscal, i.active, i.facturapi_org_id,
                          {trial_col},
                          (SELECT s.plan FROM memberships m JOIN subscriptions s ON s.user_id = m.user_id
                           WHERE m.issuer_id = i.id
                           ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, s.id DESC
                           LIMIT 1) AS plan,
                          (SELECT s.status FROM memberships m JOIN subscriptions s ON s.user_id = m.user_id
                           WHERE m.issuer_id = i.id
                           ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, s.id DESC
                           LIMIT 1) AS plan_status,
                          (SELECT MAX(last_run_at) FROM sat_sync_state st WHERE st.issuer_id = i.id) AS last_sat_sync_at,
                          (SELECT request_id FROM error_events ee WHERE ee.issuer_id = i.id ORDER BY ee.id DESC LIMIT 1) AS last_error_request_id,
                          (SELECT created_at FROM error_events ee WHERE ee.issuer_id = i.id ORDER BY ee.id DESC LIMIT 1) AS last_error_at
                   FROM issuers i
                   WHERE i.rfc LIKE ? OR i.razon_social LIKE ?
                      OR i.id IN (
                        SELECT m.issuer_id FROM memberships m
                        JOIN users u ON u.id = m.user_id
                        WHERE u.email LIKE ?
                      )
                   ORDER BY i.id""",
                (like, like, like),
            )
        else:
            rows = db_rows(
                f"""SELECT i.id, i.rfc, i.razon_social, i.regimen_fiscal, i.active, i.facturapi_org_id,
                          {trial_col},
                          (SELECT s.plan FROM memberships m JOIN subscriptions s ON s.user_id = m.user_id
                           WHERE m.issuer_id = i.id
                           ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, s.id DESC
                           LIMIT 1) AS plan,
                          (SELECT s.status FROM memberships m JOIN subscriptions s ON s.user_id = m.user_id
                           WHERE m.issuer_id = i.id
                           ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, s.id DESC
                           LIMIT 1) AS plan_status,
                          (SELECT MAX(last_run_at) FROM sat_sync_state st WHERE st.issuer_id = i.id) AS last_sat_sync_at,
                          (SELECT request_id FROM error_events ee WHERE ee.issuer_id = i.id ORDER BY ee.id DESC LIMIT 1) AS last_error_request_id,
                          (SELECT created_at FROM error_events ee WHERE ee.issuer_id = i.id ORDER BY ee.id DESC LIMIT 1) AS last_error_at
                   FROM issuers i
                   ORDER BY i.id"""
            )
        return templates.TemplateResponse(
            "admin_issuers.html",
            {
                "request": request,
                "active_page": "issuers",
                "issuers": rows,
                "search_q": search,
                "can_impersonate": can_impersonate,
                "csrf_token": csrf_service.generate_csrf_token(),
            },
        )

    # ---------- GET/POST: Issuer detail (notas, necesita revisión) ----------
    @router.get("/issuers/{issuer_id:int}", response_class=HTMLResponse)
    def admin_issuer_detail(
        request: Request,
        issuer_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        rows = db_rows(
            """
            SELECT i.id, i.rfc, i.razon_social, i.regimen_fiscal, i.active, i.facturapi_org_id,
                   i.trial_expires_at,
                   (SELECT s.plan FROM memberships m JOIN subscriptions s ON s.user_id = m.user_id
                    WHERE m.issuer_id = i.id ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, s.id DESC LIMIT 1) AS plan,
                   (SELECT s.status FROM memberships m JOIN subscriptions s ON s.user_id = m.user_id
                    WHERE m.issuer_id = i.id ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, s.id DESC LIMIT 1) AS plan_status
            FROM issuers i WHERE i.id = ?
            """,
            (issuer_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Issuer no encontrado")
        issuer = rows[0]
        try:
            issuer["trial_expires_at"] = issuer.get("trial_expires_at")
        except Exception:
            issuer["trial_expires_at"] = None
        meta = admin_issuer_service.get_meta(issuer_id) or {}
        user_id, _, _ = _admin
        can_impersonate = users.user_has_admin_role(user_id)
        return templates.TemplateResponse(
            "admin_issuer_detail.html",
            {
                "request": request,
                "active_page": "issuers",
                "issuer": issuer,
                "meta": meta,
                "can_impersonate": can_impersonate,
                "csrf_token": csrf_service.generate_csrf_token(),
            },
        )

    @router.post("/issuers/{issuer_id:int}", response_class=RedirectResponse)
    def admin_issuer_update(
        request: Request,
        issuer_id: int,
        admin_notes: str | None = Form(None),
        needs_review: str | None = Form(None),
        csrf_token: str | None = Form(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido")
        rows = db_rows("SELECT id FROM issuers WHERE id = ? LIMIT 1", (issuer_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Issuer no encontrado")
        need_bool = None
        if needs_review is not None and str(needs_review).strip().lower() in ("1", "true", "on", "yes"):
            need_bool = True
        elif needs_review is not None and str(needs_review).strip().lower() in ("0", "false", "off", "no"):
            need_bool = False
        admin_issuer_service.update_meta(issuer_id, admin_notes=admin_notes if admin_notes is not None else None, needs_review=need_bool)
        log_action(request, "admin_issuer_meta_updated", issuer_id=issuer_id, admin_notes_len=len(admin_notes or ""), needs_review=need_bool)
        return RedirectResponse(url=f"/admin/issuers/{issuer_id}", status_code=302)

    # ---------- GET: Jobs ----------
    @router.get("/jobs", response_class=HTMLResponse)
    def admin_jobs(
        request: Request,
        status: str | None = Query(None),
        issuer_id: int | None = Query(None),
        q: str | None = Query(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        where = ["1=1"]
        params: list = []
        if status and status.strip():
            where.append("j.status = ?")
            params.append(status.strip())
        if issuer_id is not None:
            where.append("j.issuer_id = ?")
            params.append(int(issuer_id))
        if q and q.strip():
            where.append("j.name LIKE ?")
            params.append(f"%{q.strip()}%")
        rows = db_rows(
            f"""
            SELECT j.id, j.issuer_id, i.rfc AS issuer_rfc, i.razon_social AS issuer_name,
                   j.name, j.status, j.progress, j.message,
                   j.attempts, j.max_attempts, j.run_after,
                   j.locked_by, j.locked_at,
                   j.created_at, j.updated_at
            FROM jobs j
            LEFT JOIN issuers i ON i.id = j.issuer_id
            WHERE {' AND '.join(where)}
            ORDER BY j.id DESC
            LIMIT 200
            """,
            tuple(params),
        )
        return templates.TemplateResponse(
            "admin_jobs.html",
            {
                "request": request,
                "active_page": "jobs",
                "jobs": rows,
                "filter_status": (status or "").strip(),
                "filter_issuer_id": issuer_id,
                "filter_q": (q or "").strip(),
            },
        )

    @router.get("/jobs/{job_id:int}", response_class=HTMLResponse)
    def admin_job_detail(
        request: Request,
        job_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        rows = db_rows(
            """
            SELECT j.*, i.rfc AS issuer_rfc, i.razon_social AS issuer_name
            FROM jobs j
            LEFT JOIN issuers i ON i.id = j.issuer_id
            WHERE j.id = ?
            LIMIT 1
            """,
            (int(job_id),),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Job no encontrado")
        job = rows[0]

        payload_pretty = ""
        result_pretty = ""
        try:
            if job.get("payload_json"):
                payload_pretty = json.dumps(json.loads(job["payload_json"]), ensure_ascii=False, indent=2)
        except Exception:
            payload_pretty = job.get("payload_json") or ""
        try:
            if job.get("result_json"):
                result_pretty = json.dumps(json.loads(job["result_json"]), ensure_ascii=False, indent=2)
        except Exception:
            result_pretty = job.get("result_json") or ""

        return templates.TemplateResponse(
            "admin_job_detail.html",
            {
                "request": request,
                "active_page": "jobs",
                "job": job,
                "payload_pretty": payload_pretty,
                "result_pretty": result_pretty,
            },
        )

    # ---------- GET: Errors ----------
    @router.get("/errors", response_class=HTMLResponse)
    def admin_errors(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        user_id, _, _ = _admin
        can_view_internal = users.user_has_admin_role(user_id)
        events = []
        try:
            events = error_events_service.list_error_events(limit=100)
        except Exception:
            events = []
        return templates.TemplateResponse(
            "admin_errors.html",
            {
                "request": request,
                "active_page": "errors",
                "events": events,
                "can_view_internal": can_view_internal,
            },
        )

    @router.get("/errors/{event_id:int}", response_class=HTMLResponse)
    def admin_error_detail(
        request: Request,
        event_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        ev = error_events_service.get_error_event(int(event_id))
        if not ev:
            raise HTTPException(status_code=404, detail="Evento no encontrado")
        return templates.TemplateResponse(
            "admin_error_detail.html",
            {"request": request, "active_page": "errors", "event": ev},
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
            {
                "request": request,
                "active_page": "ops",
                "message": None,
                "result": None,
                "csrf_token": csrf_service.generate_csrf_token(),
                **_ops_observability_context(),
            },
        )

    @router.post("/ops", response_class=HTMLResponse)
    def admin_ops_post(
        request: Request,
        action: str = Form(...),
        csrf_token: str | None = Form(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
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
            script_storage = base_dir / "scripts" / "backup_storage.sh"
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
                "csrf_token": csrf_service.generate_csrf_token(),
                **_ops_observability_context(),
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
        audit.log(
            action="impersonate_start",
            user_id=user_id,
            issuer_id=current_issuer_id,
            target_issuer_id=target_issuer["id"],
            details=f"target_issuer_id={target_issuer['id']} rfc={target_issuer.get('rfc') or ''}",
            request=request,
        )
        # obligatorio: action_log también (sin romper si falla)
        try:
            log_action(request, "impersonate_start", user_id=user_id, issuer_id=current_issuer_id, target_issuer_id=target_issuer["id"])
        except Exception:
            pass
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
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, body.issuer_id, body.rfc)

    @router.get("/impersonate/{issuer_id:int}", response_class=RedirectResponse)
    def admin_impersonate_get(
        request: Request,
        issuer_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, issuer_id, None)

    @router.post("/impersonate/{issuer_id:int}", response_class=RedirectResponse)
    def admin_impersonate_post(
        request: Request,
        issuer_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, issuer_id, None)

    @router.post("/impersonate-form", response_class=RedirectResponse)
    def admin_impersonate_form(
        request: Request,
        issuer_id: int | None = Form(None),
        rfc: str | None = Form(None),
        csrf_token: str | None = Form(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id, current_issuer_id, _ = _admin
        return _do_impersonate(request, user_id, current_issuer_id, issuer_id, rfc)

    @router.post("/stop-impersonate")
    def admin_stop_impersonate(request: Request, csrf_token: str | None = Form(None)):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id, _current_issuer_id, restore_issuer_id = _get_session_user_and_issuer(request)
        if restore_issuer_id is None:
            raise HTTPException(status_code=400, detail="No estás en modo impersonación")
        audit.log(
            action="impersonate_stop",
            user_id=user_id,
            issuer_id=_current_issuer_id,
            target_issuer_id=restore_issuer_id,
            details=f"restored_issuer_id={restore_issuer_id}",
            request=request,
        )
        try:
            log_action(request, "impersonate_stop", user_id=user_id, issuer_id=_current_issuer_id, target_issuer_id=restore_issuer_id)
        except Exception:
            pass
        cookie_val = session.sign_session(user_id, restore_issuer_id, restore_issuer_id=None)
        response = RedirectResponse(url="/portal/home", status_code=302)
        response.set_cookie(
            session.get_session_cookie_name(),
            cookie_val,
            **session.session_cookie_params(request),
        )
        return response

    return router

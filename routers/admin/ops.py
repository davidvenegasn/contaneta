"""Admin ops, errors, status, and config routes."""
import os
import subprocess
from pathlib import Path

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from config import (
    AT_REST_MASTER_KEY_SET,
    COOKIE_SECURE,
    DB_PATH,
    DEV_MODE,
    ENV,
    IS_PROD,
    SESSION_SECRET_FROM_ENV,
    SITE_URL,
    STRIPE_SECRET_KEY,
)
from database import db, db_rows
from migrations_runner import apply_migrations
from routers.admin._deps import require_admin, require_admin_or_owner
from routers.admin.dashboard import _ops_observability_context
from services import audit
from services import error_events as error_events_service
from services.auth import csrf as csrf_service
from services.auth import users


def register_ops_routes(router, templates):
    """Register admin ops, errors, status, and config routes."""

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
            request,
            "admin_errors.html",
            {
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
            request,
            "admin_error_detail.html",
            {"active_page": "errors", "event": ev},
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

    # ---------- GET: Admin config check ----------
    @router.get("/config", response_class=HTMLResponse)
    def admin_config(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        """Show environment config status (no secrets revealed)."""
        checks = [
            ("ENV", ENV, ENV == "prod", "Should be 'prod' in production"),
            ("SESSION_SECRET", "set from .env" if SESSION_SECRET_FROM_ENV else "auto-generated", SESSION_SECRET_FROM_ENV, "Must be set in .env for prod"),
            ("AT_REST_MASTER_KEY", "configured" if AT_REST_MASTER_KEY_SET else "using fallback", AT_REST_MASTER_KEY_SET, "Recommended: dedicated encryption key"),
            ("COOKIE_SECURE", "yes" if COOKIE_SECURE else "no", COOKIE_SECURE or not IS_PROD, "Must be true in prod (HTTPS)"),
            ("DEV_MODE", "on" if DEV_MODE else "off", not DEV_MODE or not IS_PROD, "Must be off in prod"),
            ("SITE_URL", SITE_URL or "not set", bool(SITE_URL), "Required for Stripe callbacks and emails"),
            ("STRIPE_SECRET_KEY", "configured" if STRIPE_SECRET_KEY else "not set", True, "Optional — only if billing enabled"),
            ("DB_PATH", DB_PATH, True, ""),
        ]
        rows_html = ""
        for label, value, ok, hint in checks:
            icon = "✅" if ok else "⚠️"
            rows_html += f'<tr><td><strong>{label}</strong></td><td>{value}</td><td>{icon}</td><td class="muted">{hint}</td></tr>'
        html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"/><title>Config Check</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
body {{ font-family: "Plus Jakarta Sans",system-ui,sans-serif; margin: 16px; background: #f0fdf9; color: #0d1f1c; }}
.wrap {{ max-width: 800px; margin: 0 auto; }}
.card {{ background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
th {{ background: #f8fafc; font-size: 12px; color: #64748b; text-transform: uppercase; }}
.muted {{ color: #64748b; font-size: 13px; }}
a {{ color: #0369a1; text-decoration: none; }}
</style></head><body>
<div class="wrap">
  <p><a href="/admin/dashboard">&larr; Dashboard</a></p>
  <h1>Config Check</h1>
  <div class="card">
    <table><thead><tr><th>Variable</th><th>Value</th><th>Status</th><th>Notes</th></tr></thead>
    <tbody>{rows_html}</tbody></table>
  </div>
</div></body></html>"""
        return HTMLResponse(html)

    # ---------- GET / POST: Ops ----------
    @router.get("/ops", response_class=HTMLResponse)
    def admin_ops_get(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        return templates.TemplateResponse(
            request,
            "admin_ops.html",
            {
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
                    details="action=migrations result=ok",
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
            base_dir = Path(__file__).resolve().parent.parent.parent
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
                    details="action=backup result=ok",
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
            request,
            "admin_ops.html",
            {
                "active_page": "ops",
                "message": "Listo." if message_ok else "Error (ver resultado).",
                "message_ok": message_ok,
                "result": result_text,
                "csrf_token": csrf_service.generate_csrf_token(),
                **_ops_observability_context(),
            },
        )

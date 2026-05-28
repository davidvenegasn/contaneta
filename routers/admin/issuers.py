"""Admin issuer, user, and membership routes."""
from fastapi import Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from database import db, db_rows, has_column
from routers.admin._deps import require_admin, require_admin_or_owner
from services import admin_issuer as admin_issuer_service
from services import error_events as error_events_service
from services.action_log import log_action
from services.auth import csrf as csrf_service
from services.auth import users


def register_issuer_routes(router, templates):
    """Register admin issuer/user/membership routes."""

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
            request,
            "admin_users.html",
            {"active_page": "users", "users": rows},
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

        issuer_select = f"""SELECT i.id, i.rfc, i.razon_social, i.regimen_fiscal, i.active, i.facturapi_org_id,
                          {trial_col},
                          (SELECT s.plan FROM memberships m JOIN subscriptions s ON s.user_id = m.user_id
                           WHERE m.issuer_id = i.id
                           ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, s.id DESC
                           LIMIT 1) AS plan,
                          (SELECT s.status FROM memberships m JOIN subscriptions s ON s.user_id = m.user_id
                           WHERE m.issuer_id = i.id
                           ORDER BY CASE m.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, s.id DESC
                           LIMIT 1) AS plan_status,
                          (SELECT last_success_at FROM sat_sync_state st WHERE st.issuer_id = i.id AND st.direction = 'issued') AS last_sync_issued,
                          (SELECT last_success_at FROM sat_sync_state st WHERE st.issuer_id = i.id AND st.direction = 'received') AS last_sync_received,
                          (SELECT COUNT(*) FROM sat_jobs sj WHERE sj.issuer_id = i.id AND sj.status = 'error' AND sj.updated_at > datetime('now', '-24 hours')) AS jobs_failed_24h,
                          CASE
                            WHEN (SELECT validation_ok FROM sat_credentials sc WHERE sc.issuer_id = i.id) = 1
                              THEN CASE
                                WHEN (SELECT last_error FROM sat_sync_state st WHERE st.issuer_id = i.id ORDER BY st.updated_at DESC LIMIT 1) IS NOT NULL
                                  THEN 'SAT ERROR'
                                ELSE 'SAT OK'
                              END
                            WHEN (SELECT id FROM sat_credentials sc WHERE sc.issuer_id = i.id) IS NOT NULL
                              THEN 'SAT ERROR'
                            ELSE 'NO CONFIG'
                          END AS sat_badge
                   FROM issuers i"""
        if search:
            from services.db_utils import escape_like
            _s = escape_like(search)
            like = f"%{_s}%"
            rows = db_rows(
                f"""{issuer_select}
                   WHERE i.rfc LIKE ? ESCAPE '\\' OR i.razon_social LIKE ? ESCAPE '\\'
                      OR i.id IN (
                        SELECT m.issuer_id FROM memberships m
                        JOIN users u ON u.id = m.user_id
                        WHERE u.email LIKE ? ESCAPE '\\'
                      )
                   ORDER BY i.id""",
                (like, like, like),
            )
        else:
            rows = db_rows(
                f"""{issuer_select}
                   ORDER BY i.id"""
            )
        return templates.TemplateResponse(
            request,
            "admin_issuers.html",
            {
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

        # SAT credentials status (without secrets)
        sat_creds = None
        try:
            creds_rows = db_rows(
                "SELECT validation_ok, validation_at, validation_message, updated_at FROM sat_credentials WHERE issuer_id = ?",
                (issuer_id,),
            )
            sat_creds = creds_rows[0] if creds_rows else None
        except Exception:
            pass

        # Sync state per direction
        sync_states = []
        try:
            sync_states = db_rows(
                "SELECT direction, last_success_at, last_attempt_at, last_error, cooldown_until, updated_at FROM sat_sync_state WHERE issuer_id = ? ORDER BY direction",
                (issuer_id,),
            )
        except Exception:
            pass

        # Recent jobs for this issuer
        issuer_jobs = db_rows(
            """SELECT id, name, status, progress, message, attempts, max_attempts, created_at, updated_at
               FROM jobs WHERE issuer_id = ? ORDER BY id DESC LIMIT 20""",
            (issuer_id,),
        )
        # Recent sat_jobs for this issuer
        issuer_sat_jobs = []
        try:
            issuer_sat_jobs = db_rows(
                """SELECT id, job_type, direction, status, attempts, last_error, started_at, finished_at, created_at
                   FROM sat_jobs WHERE issuer_id = ? ORDER BY id DESC LIMIT 20""",
                (issuer_id,),
            )
        except Exception:
            pass

        # Recent errors for this issuer
        issuer_errors = []
        try:
            issuer_errors = db_rows(
                "SELECT id, created_at, path, status, request_id FROM error_events WHERE issuer_id = ? ORDER BY id DESC LIMIT 10",
                (issuer_id,),
            )
        except Exception:
            pass

        return templates.TemplateResponse(
            request,
            "admin_issuer_detail.html",
            {
                "active_page": "issuers",
                "issuer": issuer,
                "meta": meta,
                "can_impersonate": can_impersonate,
                "csrf_token": csrf_service.generate_csrf_token(),
                "sat_creds": sat_creds,
                "sync_states": sync_states,
                "issuer_jobs": issuer_jobs,
                "issuer_sat_jobs": issuer_sat_jobs,
                "issuer_errors": issuer_errors,
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

    # ---------- POST: Force SAT sync for an issuer ----------
    @router.post("/issuers/{issuer_id:int}/force-sync", response_class=RedirectResponse)
    def admin_force_sync(
        request: Request,
        issuer_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        csrf_service.validate_csrf_token(request)
        from services.sat.sat_autosync import enqueue_sat_sync
        enqueued = []
        for direction in ("issued", "received"):
            jid = enqueue_sat_sync(issuer_id, direction)
            if jid:
                enqueued.append(jid)
        user_id, _, _ = _admin
        from services import audit
        audit.log(
            action="admin_force_sync", user_id=user_id, request=request,
            entity="issuer", entity_id=str(issuer_id),
            details=f"enqueued={enqueued}",
        )
        log_action(request, "admin_force_sync", issuer_id=issuer_id)
        return RedirectResponse(url=f"/admin/issuers/{issuer_id}", status_code=302)

    # ---------- POST: Requeue failed sat_jobs for an issuer ----------
    @router.post("/issuers/{issuer_id:int}/requeue-failed", response_class=RedirectResponse)
    def admin_requeue_failed_jobs(
        request: Request,
        issuer_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        csrf_service.validate_csrf_token(request)
        conn = db()
        try:
            conn.execute(
                "UPDATE sat_jobs SET status = 'queued', locked_at = NULL, updated_at = datetime('now') WHERE issuer_id = ? AND status = 'error'",
                (issuer_id,),
            )
            conn.commit()
        finally:
            conn.close()
        user_id, _, _ = _admin
        from services import audit
        audit.log(action="admin_requeue_failed", user_id=user_id, request=request, entity="issuer", entity_id=str(issuer_id))
        log_action(request, "admin_requeue_failed", issuer_id=issuer_id)
        return RedirectResponse(url=f"/admin/issuers/{issuer_id}", status_code=302)

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
            request,
            "admin_memberships.html",
            {"active_page": "memberships", "memberships": rows},
        )

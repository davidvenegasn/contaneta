"""Admin job and SAT job routes."""
import json

from fastapi import Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from database import db, db_rows
from routers.admin._deps import require_admin, require_admin_or_owner
from services import audit
from services.action_log import log_action
from services.auth import csrf as csrf_service


def register_job_routes(router, templates):
    """Register admin job routes."""

    # ---------- GET: Jobs ----------
    @router.get("/jobs", response_class=HTMLResponse)
    def admin_jobs(
        request: Request,
        status: str | None = Query(None),
        issuer_id: int | None = Query(None),
        q: str | None = Query(None),
        direction: str | None = Query(None),
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
            from services.db_utils import escape_like
            where.append("j.name LIKE ? ESCAPE '\\'")
            params.append(f"%{escape_like(q.strip())}%")
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

        # SAT jobs
        sat_where = ["1=1"]
        sat_params: list = []
        if status and status.strip():
            sat_where.append("sj.status = ?")
            sat_params.append(status.strip())
        if issuer_id is not None:
            sat_where.append("sj.issuer_id = ?")
            sat_params.append(int(issuer_id))
        if direction and direction.strip():
            sat_where.append("sj.direction = ?")
            sat_params.append(direction.strip())
        sat_rows = []
        try:
            sat_rows = db_rows(
                f"""
                SELECT sj.id, sj.issuer_id, i.rfc AS issuer_rfc,
                       sj.job_type, sj.direction, sj.status,
                       sj.attempts, sj.last_error,
                       sj.started_at, sj.finished_at, sj.created_at
                FROM sat_jobs sj
                LEFT JOIN issuers i ON i.id = sj.issuer_id
                WHERE {' AND '.join(sat_where)}
                ORDER BY sj.id DESC
                LIMIT 200
                """,
                tuple(sat_params),
            )
        except Exception:
            pass

        return templates.TemplateResponse(
            request,
            "admin_jobs.html",
            {
                "active_page": "jobs",
                "jobs": rows,
                "sat_jobs": sat_rows,
                "filter_status": (status or "").strip(),
                "filter_issuer_id": issuer_id,
                "filter_q": (q or "").strip(),
                "filter_direction": (direction or "").strip(),
                "csrf_token": csrf_service.generate_csrf_token(),
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
            request,
            "admin_job_detail.html",
            {
                "active_page": "jobs",
                "job": job,
                "payload_pretty": payload_pretty,
                "result_pretty": result_pretty,
                "csrf_token": csrf_service.generate_csrf_token(),
            },
        )

    # ---------- POST: Requeue a failed job ----------
    @router.post("/jobs/{job_id:int}/requeue", response_class=RedirectResponse)
    def admin_job_requeue(
        request: Request,
        job_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        csrf_service.validate_csrf_token(request)
        conn = db()
        try:
            row = conn.execute("SELECT id, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job no encontrado")
            conn.execute(
                "UPDATE jobs SET status = 'queued', locked_by = NULL, locked_at = NULL, updated_at = datetime('now') WHERE id = ?",
                (job_id,),
            )
            conn.commit()
        finally:
            conn.close()
        user_id, _, _ = _admin
        audit.log(action="admin_job_requeue", user_id=user_id, request=request, entity="job", entity_id=str(job_id))
        log_action(request, "admin_job_requeue", job_id=job_id)
        return RedirectResponse(url=f"/admin/jobs/{job_id}", status_code=302)

    # ---------- GET: SAT Jobs (dedicated) ----------
    @router.get("/sat-jobs", response_class=HTMLResponse)
    def admin_sat_jobs(
        request: Request,
        status: str | None = Query(None),
        issuer_id: int | None = Query(None),
        direction: str | None = Query(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        where = ["1=1"]
        params: list = []
        if status and status.strip():
            where.append("sj.status = ?")
            params.append(status.strip())
        if issuer_id is not None:
            where.append("sj.issuer_id = ?")
            params.append(int(issuer_id))
        if direction and direction.strip():
            where.append("sj.direction = ?")
            params.append(direction.strip())
        rows = []
        try:
            rows = db_rows(
                f"""
                SELECT sj.id, sj.issuer_id, i.rfc AS issuer_rfc, i.razon_social AS issuer_name,
                       sj.job_type, sj.direction, sj.status,
                       sj.attempts, sj.last_error,
                       sj.started_at, sj.finished_at, sj.created_at, sj.updated_at
                FROM sat_jobs sj
                LEFT JOIN issuers i ON i.id = sj.issuer_id
                WHERE {' AND '.join(where)}
                ORDER BY sj.id DESC
                LIMIT 200
                """,
                tuple(params),
            )
        except Exception:
            pass
        return templates.TemplateResponse(
            request,
            "admin_sat_jobs.html",
            {
                "active_page": "sat-jobs",
                "sat_jobs": rows,
                "filter_status": (status or "").strip(),
                "filter_issuer_id": issuer_id,
                "filter_direction": (direction or "").strip(),
                "csrf_token": csrf_service.generate_csrf_token(),
            },
        )

    @router.get("/sat-jobs/{job_id:int}", response_class=HTMLResponse)
    def admin_sat_job_detail(
        request: Request,
        job_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        rows = db_rows(
            """
            SELECT sj.*, i.rfc AS issuer_rfc, i.razon_social AS issuer_name
            FROM sat_jobs sj
            LEFT JOIN issuers i ON i.id = sj.issuer_id
            WHERE sj.id = ?
            LIMIT 1
            """,
            (int(job_id),),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="SAT Job no encontrado")
        job = rows[0]
        # Sync state for this issuer+direction
        sync_state = None
        if job.get("direction"):
            try:
                ss = db_rows(
                    "SELECT * FROM sat_sync_state WHERE issuer_id = ? AND direction = ?",
                    (job["issuer_id"], job["direction"]),
                )
                sync_state = ss[0] if ss else None
            except Exception:
                pass
        return templates.TemplateResponse(
            request,
            "admin_sat_job_detail.html",
            {
                "active_page": "sat-jobs",
                "job": job,
                "sync_state": sync_state,
                "csrf_token": csrf_service.generate_csrf_token(),
            },
        )

    @router.post("/sat-jobs/{job_id:int}/requeue", response_class=RedirectResponse)
    def admin_sat_job_requeue(
        request: Request,
        job_id: int,
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        csrf_service.validate_csrf_token(request)
        conn = db()
        try:
            row = conn.execute("SELECT id FROM sat_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="SAT Job no encontrado")
            conn.execute(
                "UPDATE sat_jobs SET status = 'queued', locked_at = NULL, updated_at = datetime('now') WHERE id = ?",
                (job_id,),
            )
            conn.commit()
        finally:
            conn.close()
        user_id, _, _ = _admin
        audit.log(action="admin_sat_job_requeue", user_id=user_id, request=request, entity="sat_job", entity_id=str(job_id))
        log_action(request, "admin_sat_job_requeue", job_id=job_id)
        return RedirectResponse(url=f"/admin/sat-jobs/{job_id}", status_code=302)

    # ---------- POST: Requeue recent SAT errors ----------
    @router.post("/sat-jobs/requeue-recent-errors")
    def admin_requeue_sat_errors(
        request: Request,
        csrf_token: str | None = Form(None),
        _admin: tuple[int, int, int | None] = Depends(require_admin),
    ):
        token_val = (csrf_token or request.headers.get("X-CSRF-Token") or "").strip()
        if not csrf_service.verify_csrf_token(token_val):
            raise HTTPException(status_code=403, detail="Token CSRF inválido o expirado")
        user_id, issuer_id, _ = _admin
        try:
            conn = db()
            try:
                cur = conn.execute(
                    """UPDATE sat_jobs SET status = 'queued', last_error = NULL, started_at = NULL, finished_at = NULL
                       WHERE status = 'error' AND updated_at > datetime('now', '-24 hours')"""
                )
                requeued = cur.rowcount
                # Clear cooldowns for affected issuers
                conn.execute(
                    """UPDATE sat_sync_state SET cooldown_until = NULL
                       WHERE cooldown_until > datetime('now')
                       AND issuer_id IN (
                           SELECT DISTINCT issuer_id FROM sat_jobs
                           WHERE status = 'queued' AND updated_at > datetime('now', '-24 hours')
                       )"""
                )
                conn.commit()
            finally:
                conn.close()
            audit.log(
                action="admin_requeue_sat_errors",
                user_id=user_id,
                issuer_id=issuer_id,
                details=f"requeued={requeued}",
                request=request,
            )
            return RedirectResponse(
                url=f"/admin/dashboard?msg=Re-encolados {requeued} SAT job(s)",
                status_code=303,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al re-encolar: {e}")

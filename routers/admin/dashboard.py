"""Admin dashboard routes."""
import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from database import db_rows
from routers.admin._deps import require_admin_or_owner
from services import error_events as error_events_service
from services.auth import csrf as csrf_service


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


def register_dashboard_routes(router, templates):
    """Register admin dashboard routes."""

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
            LIMIT 10
            """
        )
        errors_today = 0
        try:
            error_events_service.list_error_events(limit=1)
            r = db_rows("SELECT COUNT(*) AS n FROM error_events WHERE date(created_at) = date('now')")
            errors_today = r[0]["n"] if r else 0
        except Exception:
            errors_today = 0

        # SAT jobs stats (24h)
        sat_jobs_24h = {"queued": 0, "running": 0, "error": 0, "done": 0}
        try:
            for row in db_rows(
                "SELECT status, COUNT(*) AS n FROM sat_jobs WHERE created_at > datetime('now', '-24 hours') GROUP BY status"
            ):
                st = row["status"]
                if st in sat_jobs_24h:
                    sat_jobs_24h[st] = row["n"]
                elif st in ("done", "success", "ok"):
                    sat_jobs_24h["done"] += row["n"]
        except Exception:
            pass

        # Issuers needing review
        needs_review_count = 0
        try:
            r = db_rows("SELECT COUNT(*) AS n FROM admin_issuer_meta WHERE needs_review = 1")
            needs_review_count = r[0]["n"] if r else 0
        except Exception:
            pass

        # Issuers with active cooldown or recent SAT errors
        problem_issuers = []
        try:
            problem_issuers = db_rows(
                """SELECT i.id, i.rfc, i.razon_social,
                          ss.direction, ss.cooldown_until, ss.last_error, ss.last_attempt_at,
                          (SELECT COUNT(*) FROM sat_jobs sj
                           WHERE sj.issuer_id = i.id AND sj.status = 'error'
                           AND sj.updated_at > datetime('now', '-24 hours')) AS errors_24h
                   FROM issuers i
                   JOIN sat_sync_state ss ON ss.issuer_id = i.id
                   WHERE ss.cooldown_until > datetime('now')
                      OR EXISTS (SELECT 1 FROM sat_jobs sj
                                 WHERE sj.issuer_id = i.id AND sj.status = 'error'
                                 AND sj.updated_at > datetime('now', '-24 hours'))
                   ORDER BY errors_24h DESC, ss.cooldown_until DESC"""
            )
        except Exception:
            pass

        # Recent SAT errors count (for requeue button)
        sat_errors_recent = 0
        try:
            r = db_rows(
                "SELECT COUNT(*) AS n FROM sat_jobs WHERE status = 'error' AND updated_at > datetime('now', '-24 hours')"
            )
            sat_errors_recent = r[0]["n"] if r else 0
        except Exception:
            pass

        sat_cfdi_by_direction = db_rows(
            """SELECT direction, COUNT(*) AS n FROM sat_cfdi
               WHERE fecha_emision IS NOT NULL AND substr(fecha_emision, 1, 7) = ?
               GROUP BY direction""",
            (ym,),
        )

        # CFDIs missing XML + backfill job stats
        cfdi_missing_xml = 0
        try:
            r = db_rows("SELECT COUNT(*) AS n FROM sat_cfdi WHERE xml_path IS NULL OR TRIM(COALESCE(xml_path, '')) = ''")
            cfdi_missing_xml = r[0]["n"] if r else 0
        except Exception:
            pass
        backfill_jobs_24h = {"success": 0, "failed": 0}
        try:
            for row in db_rows(
                "SELECT status, COUNT(*) AS n FROM jobs WHERE name = 'sat_xml_backfill' AND created_at > datetime('now', '-24 hours') GROUP BY status"
            ):
                st = row["status"]
                if st == "success":
                    backfill_jobs_24h["success"] = row["n"]
                elif st == "failed":
                    backfill_jobs_24h["failed"] = row["n"]
        except Exception:
            pass

        # Recent jobs (last 20) for table
        recent_jobs = db_rows(
            """SELECT j.id, j.issuer_id, i.rfc AS issuer_rfc, j.name, j.status, j.message,
                      j.created_at, j.updated_at
               FROM jobs j LEFT JOIN issuers i ON i.id = j.issuer_id
               ORDER BY j.id DESC LIMIT 20"""
        )

        # Recent errors (last 20)
        recent_errors = []
        try:
            recent_errors = db_rows(
                """SELECT id, created_at, path, status_code, request_id, issuer_id
                   FROM error_events ORDER BY id DESC LIMIT 20"""
            )
        except Exception:
            pass

        # Last backup info
        last_backup = None
        backup_dir = os.getenv("BACKUP_DIR", "")
        if not backup_dir:
            backup_dir = str(Path(__file__).resolve().parent.parent.parent / "backup")
        try:
            if os.path.isdir(backup_dir):
                db_backups = sorted(
                    [f for f in os.listdir(backup_dir) if f.startswith("invoicing") and f.endswith(".db.gz")],
                    reverse=True,
                )
                if db_backups:
                    fpath = os.path.join(backup_dir, db_backups[0])
                    stat = os.stat(fpath)
                    last_backup = {
                        "file": db_backups[0],
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "count": len(db_backups),
                    }
        except Exception:
            pass

        audit_events = db_rows(
            """SELECT id, created_at, action, user_id, issuer_id, details
               FROM audit_log ORDER BY id DESC LIMIT 10"""
        )
        return templates.TemplateResponse(
            request,
            "admin_dashboard.html",
            {
                "active_page": "dashboard",
                "count_users": count_users[0]["n"] if count_users else 0,
                "count_issuers": count_issuers[0]["n"] if count_issuers else 0,
                "count_memberships": count_memberships[0]["n"] if count_memberships else 0,
                "count_active_users": active_users[0]["n"] if active_users else 0,
                "jobs_in_queue": jobs_in_queue[0]["n"] if jobs_in_queue else 0,
                "jobs_failed_today": jobs_failed_today[0]["n"] if jobs_failed_today else 0,
                "errors_today": errors_today,
                "sat_jobs_24h": sat_jobs_24h,
                "needs_review_count": needs_review_count,
                "problem_issuers": problem_issuers,
                "sat_errors_recent": sat_errors_recent,
                "last_logins": last_logins,
                "sat_cfdi_by_direction": sat_cfdi_by_direction,
                "recent_jobs": recent_jobs,
                "recent_errors": recent_errors,
                "audit_events": audit_events,
                "last_backup": last_backup,
                "cfdi_missing_xml": cfdi_missing_xml,
                "backfill_jobs_24h": backfill_jobs_24h,
                "csrf_token": csrf_service.generate_csrf_token(),
                "msg": request.query_params.get("msg"),
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

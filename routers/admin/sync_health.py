"""Admin sync health dashboard — overview of SAT sync status across all issuers."""
import logging

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

from database import db
from routers.admin._deps import require_admin_or_owner

logger = logging.getLogger(__name__)


def _sync_health_stats() -> dict:
    """Gather aggregate sync health metrics."""
    conn = db()
    try:
        # Total issuers with validated FIEL
        fiel_count = conn.execute(
            "SELECT COUNT(DISTINCT sc.issuer_id) AS n "
            "FROM sat_credentials sc "
            "JOIN issuers i ON i.id = sc.issuer_id AND i.active = 1 "
            "WHERE sc.validation_ok = 1"
        ).fetchone()
        total_fiel = fiel_count["n"] if fiel_count else 0

        # SAT jobs by status (last 24h)
        job_stats = conn.execute(
            "SELECT status, COUNT(*) AS n FROM sat_jobs "
            "WHERE created_at > datetime('now', '-24 hours') GROUP BY status"
        ).fetchall()
        jobs_24h = {row["status"]: row["n"] for row in job_stats}

        # Total queued right now
        queued_now = conn.execute(
            "SELECT COUNT(*) AS n FROM sat_jobs WHERE status = 'queued'"
        ).fetchone()

        # Errors last 24h
        errors_24h = jobs_24h.get("error", 0)

        # Success rate last 24h
        ok_24h = jobs_24h.get("ok", 0)
        total_finished_24h = ok_24h + errors_24h
        success_rate = round(ok_24h / total_finished_24h * 100, 1) if total_finished_24h > 0 else None

        return {
            "total_fiel_issuers": total_fiel,
            "queued_now": queued_now["n"] if queued_now else 0,
            "ok_24h": ok_24h,
            "errors_24h": errors_24h,
            "success_rate": success_rate,
        }
    finally:
        conn.close()


def _per_issuer_sync_status(limit: int = 50) -> list[dict]:
    """Return per-issuer sync status with last success/error info."""
    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT sc.issuer_id, i.rfc,
                   ss_i.last_success_at AS issued_last_ok,
                   ss_i.last_error AS issued_last_error,
                   ss_i.cooldown_until AS issued_cooldown,
                   ss_r.last_success_at AS received_last_ok,
                   ss_r.last_error AS received_last_error,
                   ss_r.cooldown_until AS received_cooldown
            FROM sat_credentials sc
            JOIN issuers i ON i.id = sc.issuer_id AND i.active = 1
            LEFT JOIN sat_sync_state ss_i
              ON ss_i.issuer_id = sc.issuer_id AND ss_i.direction = 'issued'
            LEFT JOIN sat_sync_state ss_r
              ON ss_r.issuer_id = sc.issuer_id AND ss_r.direction = 'received'
            WHERE sc.validation_ok = 1
            ORDER BY COALESCE(ss_i.last_success_at, '2000-01-01') ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _stale_issuers(hours: int = 48) -> list[dict]:
    """Find issuers with FIEL but no successful sync in N hours."""
    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT sc.issuer_id, i.rfc,
                   MAX(ss.last_success_at) AS last_ok
            FROM sat_credentials sc
            JOIN issuers i ON i.id = sc.issuer_id AND i.active = 1
            LEFT JOIN sat_sync_state ss ON ss.issuer_id = sc.issuer_id
            WHERE sc.validation_ok = 1
            GROUP BY sc.issuer_id
            HAVING last_ok IS NULL OR last_ok < datetime('now', '-' || ? || ' hours')
            ORDER BY last_ok ASC
            LIMIT 20
            """,
            (hours,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def register_sync_health_routes(router, templates):
    """Register admin sync health dashboard route."""

    @router.get("/sync-health", response_class=HTMLResponse)
    def admin_sync_health(
        request: Request,
        _admin: tuple[int, int, int | None] = Depends(require_admin_or_owner),
    ):
        """Sync health dashboard showing SAT sync status across all issuers."""
        stats = _sync_health_stats()
        per_issuer = _per_issuer_sync_status()
        stale = _stale_issuers()

        return templates.TemplateResponse(
            request,
            "admin_sync_health.html",
            {
                "active_page": "sync-health",
                "stats": stats,
                "per_issuer": per_issuer,
                "stale_issuers": stale,
            },
        )

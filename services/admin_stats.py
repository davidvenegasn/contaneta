"""Admin dashboard statistics — aggregated metrics for product owner."""
import logging

from database import db_rows

logger = logging.getLogger(__name__)


def get_dashboard_stats() -> dict:
    """Aggregate key metrics for the admin stats dashboard.

    Returns dict with sections: users, issuers, cfdis, subscriptions, errors.
    """
    stats: dict = {
        "users": _user_stats(),
        "issuers": _issuer_stats(),
        "cfdis": _cfdi_stats(),
        "subscriptions": _subscription_stats(),
        "errors": _error_stats(),
        "declarations": _declaration_stats(),
    }
    return stats


def _scalar(sql: str, params: tuple = ()) -> int:
    """Return first column of first row as int, or 0."""
    rows = db_rows(sql, params)
    if rows:
        val = list(rows[0].values())[0]
        return int(val) if val else 0
    return 0


def _user_stats() -> dict:
    total = _scalar("SELECT COUNT(*) AS n FROM users")
    signups_today = _scalar(
        "SELECT COUNT(*) AS n FROM users WHERE date(created_at) = date('now')"
    )
    signups_7d = _scalar(
        "SELECT COUNT(*) AS n FROM users WHERE created_at >= datetime('now', '-7 days')"
    )
    try:
        active_7d = _scalar(
            "SELECT COUNT(DISTINCT user_id) AS n FROM audit_log "
            "WHERE action = 'login' AND created_at >= datetime('now', '-7 days')"
        )
        active_30d = _scalar(
            "SELECT COUNT(DISTINCT user_id) AS n FROM audit_log "
            "WHERE action = 'login' AND created_at >= datetime('now', '-30 days')"
        )
    except Exception:
        active_7d = active_30d = 0
    return {
        "total": total,
        "signups_today": signups_today,
        "signups_last_7d": signups_7d,
        "active_last_7d": active_7d,
        "active_last_30d": active_30d,
    }


def _issuer_stats() -> dict:
    total = _scalar("SELECT COUNT(*) AS n FROM issuers")
    try:
        with_fiel = _scalar(
            "SELECT COUNT(DISTINCT issuer_id) AS n FROM sat_credentials"
        )
    except Exception:
        with_fiel = 0
    try:
        with_sub = _scalar(
            "SELECT COUNT(DISTINCT issuer_id) AS n FROM subscriptions WHERE status = 'active'"
        )
    except Exception:
        with_sub = 0
    return {
        "total": total,
        "with_fiel_validated": with_fiel,
        "with_active_subscription": with_sub,
    }


def _cfdi_stats() -> dict:
    total = _scalar("SELECT COUNT(*) AS n FROM sat_cfdi")
    issued_30d = _scalar(
        "SELECT COUNT(*) AS n FROM sat_cfdi "
        "WHERE direction = 'issued' AND created_at >= datetime('now', '-30 days')"
    )
    received_30d = _scalar(
        "SELECT COUNT(*) AS n FROM sat_cfdi "
        "WHERE direction = 'received' AND created_at >= datetime('now', '-30 days')"
    )
    return {
        "total_in_db": total,
        "issued_last_30d": issued_30d,
        "received_last_30d": received_30d,
    }


def _subscription_stats() -> dict:
    try:
        active = _scalar(
            "SELECT COUNT(*) AS n FROM subscriptions WHERE status = 'active'"
        )
        trialing = _scalar(
            "SELECT COUNT(*) AS n FROM subscriptions WHERE status = 'trialing'"
        )
        canceled_30d = _scalar(
            "SELECT COUNT(*) AS n FROM subscriptions "
            "WHERE status = 'canceled' AND updated_at >= datetime('now', '-30 days')"
        )
        # MRR estimate: count active subs × plan price (from env or default)
        import os
        price_per_sub = float(os.getenv("STRIPE_PLAN_PRICE_MXN", "299"))
        mrr_mxn = round(active * price_per_sub, 2)
    except Exception:
        active = trialing = canceled_30d = 0
        mrr_mxn = 0
    return {
        "active": active,
        "trialing": trialing,
        "canceled_last_30d": canceled_30d,
        "mrr_mxn": mrr_mxn,
    }


def _declaration_stats() -> dict:
    """Stats on uploaded declarations."""
    try:
        total = _scalar("SELECT COUNT(*) AS n FROM declarations")
        last_30d = _scalar(
            "SELECT COUNT(*) AS n FROM declarations "
            "WHERE created_at >= datetime('now', '-30 days')"
        )
        by_status = {}
        for row in db_rows("SELECT status, COUNT(*) AS n FROM declarations GROUP BY status"):
            by_status[row["status"]] = row["n"]
        by_tipo = {}
        for row in db_rows("SELECT tipo, COUNT(*) AS n FROM declarations GROUP BY tipo ORDER BY n DESC LIMIT 10"):
            by_tipo[row["tipo"]] = row["n"]
        uploaders = _scalar("SELECT COUNT(DISTINCT uploaded_by_user_id) AS n FROM declarations")
    except Exception:
        total = last_30d = uploaders = 0
        by_status = {}
        by_tipo = {}
    return {
        "total": total,
        "last_30d": last_30d,
        "by_status": by_status,
        "by_tipo": by_tipo,
        "unique_uploaders": uploaders,
    }


def _error_stats() -> dict:
    try:
        errors_24h = _scalar(
            "SELECT COUNT(*) AS n FROM error_events WHERE created_at >= datetime('now', '-24 hours')"
        )
        errors_7d = _scalar(
            "SELECT COUNT(*) AS n FROM error_events WHERE created_at >= datetime('now', '-7 days')"
        )
    except Exception:
        errors_24h = errors_7d = 0
    return {
        "errors_last_24h": errors_24h,
        "errors_last_7d": errors_7d,
    }

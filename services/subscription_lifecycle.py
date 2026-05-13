"""Subscription lifecycle: status, usage metrics, payment history, and plan limits.

Stateless functions for the /portal/subscription page.
Reads from subscriptions, plan_usage, issuers, and storage directories.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional

from database import db, db_rows
from services.billing.plans import PLANS, get_issuer_plan, get_plan_config, get_usage

logger = logging.getLogger(__name__)


# ---------- Plan limits (spec-defined structure) ----------

PLAN_LIMITS = {
    "free": {
        "name": "Gratis",
        "invoices_per_month": 5,
        "storage_mb": 100,
    },
    "trial": {
        "name": "Prueba",
        "invoices_per_month": 50,
        "storage_mb": 500,
    },
    "basic": {
        "name": "Basico",
        "invoices_per_month": 50,
        "storage_mb": 1000,
    },
    "pro": {
        "name": "Profesional",
        "invoices_per_month": 500,
        "storage_mb": 5000,
        "price_monthly": 299,
    },
    "enterprise": {
        "name": "Empresarial",
        "invoices_per_month": -1,
        "storage_mb": 50000,
        "price_monthly": 999,
    },
}


def get_plan_limits(plan: str) -> dict[str, Any]:
    """Return limits for a given plan name.

    Args:
        plan: Plan key (free, trial, basic, pro, enterprise).

    Returns:
        Dict with name, invoices_per_month, storage_mb, and optional price_monthly.
    """
    key = (plan or "free").strip().lower()
    return dict(PLAN_LIMITS.get(key, PLAN_LIMITS["free"]))


def get_subscription_status(issuer_id: int) -> dict[str, Any]:
    """Return subscription status for an issuer.

    Args:
        issuer_id: Tenant ID.

    Returns:
        Dict with plan, plan_label, status, current_period_end,
        stripe_subscription_id, created_at, updated_at.
    """
    plan_name = get_issuer_plan(issuer_id)
    plan_config = get_plan_config(plan_name)
    plan_limits = get_plan_limits(plan_name)

    result: dict[str, Any] = {
        "plan": plan_name,
        "plan_label": plan_config.get("label", plan_limits.get("name", "Gratis")),
        "status": "free",
        "current_period_end": None,
        "stripe_subscription_id": None,
        "created_at": None,
        "updated_at": None,
    }

    # Check if there's a Stripe subscription for any user associated with this issuer
    sub = _get_subscription_for_issuer(issuer_id)
    if sub:
        result["status"] = sub.get("status", "inactive")
        result["current_period_end"] = sub.get("current_period_end")
        result["stripe_subscription_id"] = sub.get("stripe_subscription_id")
        result["created_at"] = sub.get("created_at")
        result["updated_at"] = sub.get("updated_at")
    elif plan_name == "free":
        # Check trial status
        from services.billing.subscription import is_issuer_trial_active
        if is_issuer_trial_active(issuer_id):
            result["status"] = "trialing"
        else:
            result["status"] = "free"

    return result


def get_usage_metrics(issuer_id: int) -> dict[str, Any]:
    """Return usage metrics for the current month.

    Args:
        issuer_id: Tenant ID.

    Returns:
        Dict with invoices_count, storage_used_mb, plan limits, and percentages.
    """
    plan_name = get_issuer_plan(issuer_id)
    plan_limits = get_plan_limits(plan_name)
    usage = get_usage(issuer_id)

    invoices_count = usage.get("invoices_count", 0)
    invoices_limit = plan_limits.get("invoices_per_month", 5)
    storage_mb = _calculate_storage_mb(issuer_id)
    storage_limit = plan_limits.get("storage_mb", 100)

    # Calculate percentage for progress bars
    if invoices_limit > 0:
        invoices_pct = min(100, int(invoices_count / invoices_limit * 100))
    else:
        # -1 means unlimited
        invoices_pct = 0

    if storage_limit > 0:
        storage_pct = min(100, int(storage_mb / storage_limit * 100))
    else:
        storage_pct = 0

    return {
        "invoices_count": invoices_count,
        "invoices_limit": invoices_limit,
        "invoices_pct": invoices_pct,
        "storage_used_mb": round(storage_mb, 1),
        "storage_limit_mb": storage_limit,
        "storage_pct": storage_pct,
        "sat_syncs_count": usage.get("sat_syncs_count", 0),
        "bank_imports_count": usage.get("bank_imports_count", 0),
    }


def get_payment_history(issuer_id: int, limit: int = 10) -> list[dict]:
    """Return payment history for the issuer (from subscription records).

    Args:
        issuer_id: Tenant ID.
        limit: Max number of records to return.

    Returns:
        List of dicts with date, plan, status, amount info.
    """
    # Get user IDs associated with this issuer via memberships
    user_ids = _get_user_ids_for_issuer(issuer_id)
    if not user_ids:
        return []

    placeholders = ",".join("?" for _ in user_ids)
    try:
        rows = db_rows(
            f"""SELECT id, user_id, plan, status, stripe_subscription_id,
                       current_period_end, created_at, updated_at
                FROM subscriptions
                WHERE user_id IN ({placeholders})
                ORDER BY updated_at DESC
                LIMIT ?""",
            tuple(user_ids) + (limit,),
        )
    except Exception:
        logger.debug("payment_history query failed", exc_info=True)
        return []

    result = []
    for row in rows:
        plan_key = (row.get("plan") or "free").strip().lower()
        plan_info = get_plan_limits(plan_key)
        result.append({
            "date": row.get("updated_at") or row.get("created_at") or "",
            "plan": plan_key,
            "plan_label": plan_info.get("name", plan_key),
            "status": row.get("status", ""),
            "amount": plan_info.get("price_monthly", 0),
            "stripe_subscription_id": row.get("stripe_subscription_id"),
        })

    return result


def can_create_invoice(issuer_id: int) -> bool:
    """Check if the issuer can create a new invoice under plan limits.

    Args:
        issuer_id: Tenant ID.

    Returns:
        True if the issuer has not exceeded the invoice limit.
    """
    plan_name = get_issuer_plan(issuer_id)
    plan_limits = get_plan_limits(plan_name)
    invoices_limit = plan_limits.get("invoices_per_month", 5)

    # -1 means unlimited
    if invoices_limit < 0:
        return True

    usage = get_usage(issuer_id)
    return usage.get("invoices_count", 0) < invoices_limit


# ---------- Private helpers ----------

def _get_subscription_for_issuer(issuer_id: int) -> Optional[dict]:
    """Find the most recent active subscription for any user of this issuer."""
    user_ids = _get_user_ids_for_issuer(issuer_id)
    if not user_ids:
        return None

    placeholders = ",".join("?" for _ in user_ids)
    try:
        rows = db_rows(
            f"""SELECT id, user_id, plan, status, stripe_customer_id,
                       stripe_subscription_id, current_period_end,
                       created_at, updated_at
                FROM subscriptions
                WHERE user_id IN ({placeholders})
                ORDER BY
                  CASE status WHEN 'active' THEN 0 WHEN 'trialing' THEN 1 ELSE 2 END,
                  updated_at DESC
                LIMIT 1""",
            tuple(user_ids),
        )
        return rows[0] if rows else None
    except Exception:
        logger.debug("subscription lookup failed", exc_info=True)
        return None


def _get_user_ids_for_issuer(issuer_id: int) -> list[int]:
    """Get all user IDs associated with an issuer via memberships."""
    try:
        rows = db_rows(
            "SELECT user_id FROM memberships WHERE issuer_id = ?",
            (issuer_id,),
        )
        return [int(r["user_id"]) for r in rows if r.get("user_id")]
    except Exception:
        return []


def _calculate_storage_mb(issuer_id: int) -> float:
    """Calculate storage used in MB for an issuer's storage directory.

    Scans the storage/{issuer_id}/ directory tree. Returns 0.0 if
    the directory does not exist or is inaccessible.
    """
    base_dir = os.environ.get("BASE_DIR", os.path.dirname(os.path.dirname(__file__)))
    storage_path = os.environ.get("APP_STORAGE_PATH", "").strip()
    if storage_path:
        root = storage_path if os.path.isabs(storage_path) else os.path.join(base_dir, storage_path)
    else:
        root = os.path.join(base_dir, "storage")

    issuer_dir = os.path.join(root, str(issuer_id))
    if not os.path.isdir(issuer_dir):
        return 0.0

    total_bytes = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(issuer_dir):
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                try:
                    total_bytes += os.path.getsize(fpath)
                except OSError:
                    pass
    except OSError:
        return 0.0

    return total_bytes / (1024 * 1024)

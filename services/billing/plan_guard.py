"""
Plan guard — middleware/dependency for checking plan limits before actions.

Usage in routers:
    from services.billing.plan_guard import require_plan_action

    # In a route:
    check = require_plan_action(issuer_id, "invoice")
    if not check["allowed"]:
        raise HTTPException(status_code=402, detail=check["reason"])
"""
from __future__ import annotations

from typing import Any

from services.billing.plans import check_limit, increment_usage


def require_plan_action(issuer_id: int, action: str) -> dict[str, Any]:
    """
    Check if an action is allowed under the plan.
    Returns: { allowed: bool, reason: str, ... }
    """
    return check_limit(issuer_id, action)


def record_usage(issuer_id: int, action: str) -> None:
    """Record that an action was performed (increment counter)."""
    action_to_counter = {
        "invoice": "invoices_count",
        "sat_sync": "sat_syncs_count",
        "bank_import": "bank_imports_count",
    }
    counter = action_to_counter.get(action)
    if counter:
        increment_usage(issuer_id, counter)

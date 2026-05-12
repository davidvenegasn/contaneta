"""
Plan definitions, limits, and usage tracking.

Plans: FREE, TRIAL, BASIC, PRO
Each plan has limits on invoices/month, SAT syncs, bank accounts, etc.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from database import db, db_rows, has_column, table_exists

# ---------- Plan definitions ----------

PLANS = {
    "free": {
        "label": "Gratis",
        "invoices_per_month": 5,
        "sat_syncs_per_month": 0,
        "bank_accounts": 1,
        "bank_imports_per_month": 2,
        "month_close": False,
        "matching": False,
        "price_mxn": 0,
    },
    "trial": {
        "label": "Prueba (14 días)",
        "invoices_per_month": 50,
        "sat_syncs_per_month": 10,
        "bank_accounts": 3,
        "bank_imports_per_month": 10,
        "month_close": True,
        "matching": True,
        "price_mxn": 0,
    },
    "basic": {
        "label": "Básico",
        "invoices_per_month": 50,
        "sat_syncs_per_month": 10,
        "bank_accounts": 3,
        "bank_imports_per_month": 10,
        "month_close": True,
        "matching": True,
        "price_mxn": 299,
    },
    "pro": {
        "label": "Pro",
        "invoices_per_month": 500,
        "sat_syncs_per_month": 100,
        "bank_accounts": 10,
        "bank_imports_per_month": 50,
        "month_close": True,
        "matching": True,
        "price_mxn": 599,
    },
}


def get_plan_config(plan_name: str) -> dict[str, Any]:
    """Get plan configuration by name. Defaults to 'free'."""
    return PLANS.get((plan_name or "").strip().lower(), PLANS["free"])


def get_all_plans() -> dict[str, dict[str, Any]]:
    """Get all plan definitions."""
    return dict(PLANS)


# ---------- Issuer plan ----------

def get_issuer_plan(issuer_id: int) -> str:
    """Get the current plan for an issuer."""
    conn = db()
    try:
        if not has_column(conn, "issuers", "plan"):
            return "free"
        row = conn.execute(
            "SELECT plan FROM issuers WHERE id = ? LIMIT 1",
            (issuer_id,),
        ).fetchone()
        return (row["plan"] or "free") if row else "free"
    finally:
        conn.close()


def set_issuer_plan(issuer_id: int, plan: str) -> None:
    """Set the plan for an issuer and update limits."""
    plan = (plan or "free").strip().lower()
    if plan not in PLANS:
        plan = "free"
    config = PLANS[plan]
    conn = db()
    try:
        if not has_column(conn, "issuers", "plan"):
            return
        conn.execute(
            """UPDATE issuers SET plan = ?,
               plan_invoices_limit = ?,
               plan_sat_syncs_limit = ?,
               plan_bank_accounts_limit = ?
               WHERE id = ?""",
            (
                plan,
                config["invoices_per_month"],
                config["sat_syncs_per_month"],
                config["bank_accounts"],
                issuer_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------- Usage tracking ----------

def _ensure_usage_row(conn: Any, issuer_id: int, ym: str) -> None:
    """Ensure a usage row exists for the issuer+month."""
    if not table_exists(conn, "plan_usage"):
        return
    conn.execute(
        """INSERT OR IGNORE INTO plan_usage (issuer_id, ym)
           VALUES (?, ?)""",
        (issuer_id, ym),
    )


def get_usage(issuer_id: int, ym: str | None = None) -> dict[str, int]:
    """Get current month usage for an issuer."""
    ym = ym or datetime.now().strftime("%Y-%m")
    conn = db()
    try:
        if not table_exists(conn, "plan_usage"):
            return {"invoices_count": 0, "sat_syncs_count": 0, "bank_imports_count": 0}
        _ensure_usage_row(conn, issuer_id, ym)
        conn.commit()
        row = conn.execute(
            "SELECT invoices_count, sat_syncs_count, bank_imports_count FROM plan_usage WHERE issuer_id = ? AND ym = ?",
            (issuer_id, ym),
        ).fetchone()
        if row:
            return {
                "invoices_count": int(row["invoices_count"] or 0),
                "sat_syncs_count": int(row["sat_syncs_count"] or 0),
                "bank_imports_count": int(row["bank_imports_count"] or 0),
            }
        return {"invoices_count": 0, "sat_syncs_count": 0, "bank_imports_count": 0}
    finally:
        conn.close()


def increment_usage(issuer_id: int, counter: str, amount: int = 1) -> None:
    """Increment a usage counter. counter: invoices_count | sat_syncs_count | bank_imports_count"""
    valid = ("invoices_count", "sat_syncs_count", "bank_imports_count")
    if counter not in valid:
        return
    ym = datetime.now().strftime("%Y-%m")
    conn = db()
    try:
        if not table_exists(conn, "plan_usage"):
            return
        _ensure_usage_row(conn, issuer_id, ym)
        conn.execute(
            f"UPDATE plan_usage SET {counter} = {counter} + ?, updated_at = datetime('now') WHERE issuer_id = ? AND ym = ?",
            (amount, issuer_id, ym),
        )
        conn.commit()
    finally:
        conn.close()


# ---------- Limit checking ----------

def check_limit(issuer_id: int, action: str) -> dict[str, Any]:
    """
    Check if an action is allowed under the current plan.
    action: 'invoice' | 'sat_sync' | 'bank_import' | 'bank_account' | 'month_close' | 'matching'

    Returns: { allowed: bool, reason: str, usage: int, limit: int, plan: str }
    """
    plan_name = get_issuer_plan(issuer_id)
    config = get_plan_config(plan_name)
    usage = get_usage(issuer_id)

    result = {"allowed": True, "reason": "", "plan": plan_name, "plan_label": config["label"]}

    if action == "invoice":
        limit = config["invoices_per_month"]
        used = usage["invoices_count"]
        result.update({"usage": used, "limit": limit})
        if limit > 0 and used >= limit:
            result["allowed"] = False
            result["reason"] = f"Limite de {limit} facturas/mes alcanzado (plan {config['label']})"

    elif action == "sat_sync":
        limit = config["sat_syncs_per_month"]
        used = usage["sat_syncs_count"]
        result.update({"usage": used, "limit": limit})
        if limit <= 0:
            result["allowed"] = False
            result["reason"] = f"Sync SAT no disponible en plan {config['label']}"
        elif used >= limit:
            result["allowed"] = False
            result["reason"] = f"Limite de {limit} syncs/mes alcanzado"

    elif action == "bank_import":
        limit = config["bank_imports_per_month"]
        used = usage["bank_imports_count"]
        result.update({"usage": used, "limit": limit})
        if used >= limit:
            result["allowed"] = False
            result["reason"] = f"Limite de {limit} importaciones/mes alcanzado"

    elif action == "bank_account":
        limit = config["bank_accounts"]
        # Count actual accounts
        count = 0
        try:
            rows = db_rows(
                "SELECT COUNT(*) AS c FROM issuer_bank_accounts WHERE issuer_id = ? AND is_active = 1",
                (issuer_id,),
            )
            count = int(rows[0]["c"]) if rows else 0
        except Exception:
            pass
        result.update({"usage": count, "limit": limit})
        if count >= limit:
            result["allowed"] = False
            result["reason"] = f"Limite de {limit} cuentas bancarias alcanzado"

    elif action == "month_close":
        result.update({"usage": 0, "limit": 1 if config["month_close"] else 0})
        if not config["month_close"]:
            result["allowed"] = False
            result["reason"] = "Cierre mensual no disponible en plan gratuito"

    elif action == "matching":
        result.update({"usage": 0, "limit": 1 if config["matching"] else 0})
        if not config["matching"]:
            result["allowed"] = False
            result["reason"] = "Conciliacion no disponible en plan gratuito"

    return result


def get_plan_summary(issuer_id: int) -> dict[str, Any]:
    """Get plan summary for the /portal/plan page."""
    plan_name = get_issuer_plan(issuer_id)
    config = get_plan_config(plan_name)
    usage = get_usage(issuer_id)

    # Show "Trial" instead of "Gratis" when trial is active (consistent with header badge)
    label = config["label"]
    if plan_name == "free":
        from services.billing.subscription import is_issuer_trial_active
        if is_issuer_trial_active(issuer_id):
            label = "Trial"

    return {
        "plan": plan_name,
        "plan_label": label,
        "price_mxn": config["price_mxn"],
        "limits": {
            "invoices": {"used": usage["invoices_count"], "limit": config["invoices_per_month"]},
            "sat_syncs": {"used": usage["sat_syncs_count"], "limit": config["sat_syncs_per_month"]},
            "bank_imports": {"used": usage["bank_imports_count"], "limit": config["bank_imports_per_month"]},
            "bank_accounts": {"limit": config["bank_accounts"]},
            "month_close": config["month_close"],
            "matching": config["matching"],
        },
        "all_plans": {k: {"label": v["label"], "price_mxn": v["price_mxn"], "invoices": v["invoices_per_month"], "sat_syncs": v["sat_syncs_per_month"], "bank_imports": v["bank_imports_per_month"], "bank_accounts": v["bank_accounts"], "month_close": v["month_close"], "matching": v["matching"]} for k, v in PLANS.items()},
    }

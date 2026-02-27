"""Suscripciones por usuario (Stripe) y trial por issuer (expires_at)."""
from typing import Optional

from database import db, db_rows, has_column


def get_subscription_by_user_id(user_id: int) -> Optional[dict]:
    """Devuelve la fila de subscriptions para el usuario o None."""
    if not user_id or user_id <= 0:
        return None
    rows = db_rows("SELECT id, user_id, plan, status, stripe_customer_id, stripe_subscription_id, current_period_end, created_at, updated_at FROM subscriptions WHERE user_id = ?", (user_id,))
    return rows[0] if rows else None


def is_subscription_active(user_id: int) -> bool:
    """True si el usuario tiene una suscripción activa (status = active o trialing)."""
    sub = get_subscription_by_user_id(user_id)
    if not sub:
        return False
    return (sub.get("status") or "").lower() in ("active", "trialing")


def upsert_subscription(
    user_id: int,
    *,
    plan: str = "pro",
    status: str = "active",
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    current_period_end: Optional[str] = None,
) -> None:
    """Crea o actualiza la suscripción del usuario."""
    conn = db()
    try:
        cur = conn.execute(
            "UPDATE subscriptions SET plan = ?, status = ?, stripe_customer_id = COALESCE(?, stripe_customer_id), stripe_subscription_id = COALESCE(?, stripe_subscription_id), current_period_end = COALESCE(?, current_period_end), updated_at = datetime('now') WHERE user_id = ?",
            (plan, status, stripe_customer_id, stripe_subscription_id, current_period_end, user_id),
        )
        if cur.rowcount == 0:
            conn.execute(
                """INSERT INTO subscriptions (user_id, plan, status, stripe_customer_id, stripe_subscription_id, current_period_end)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, plan, status, stripe_customer_id, stripe_subscription_id, current_period_end),
            )
        conn.commit()
    finally:
        conn.close()


def set_subscription_status(user_id: int, status: str) -> None:
    """Actualiza solo el status de la suscripción del usuario."""
    conn = db()
    try:
        conn.execute(
            "UPDATE subscriptions SET status = ?, updated_at = datetime('now') WHERE user_id = ?",
            (status, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_subscription_canceled(user_id: int) -> None:
    """Marca la suscripción como canceled."""
    set_subscription_status(user_id, "canceled")


def is_issuer_trial_active(issuer_id: int) -> bool:
    """True si el issuer tiene trial_expires_at en el futuro (sin Stripe aún). Sin columna o NULL = legacy, permitir."""
    if not issuer_id or issuer_id <= 0:
        return False
    conn = db()
    try:
        if not has_column(conn, "issuers", "trial_expires_at"):
            return True
        row = conn.execute(
            "SELECT 1 FROM issuers WHERE id = ? AND (trial_expires_at IS NULL OR trial_expires_at = '' OR trial_expires_at > datetime('now')) LIMIT 1",
            (issuer_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def can_issuer_use_sync_and_timbrado(issuer_id: int, user_id: int) -> bool:
    """
    True si el issuer puede usar sync SAT y timbrado (Facturapi).
    Permite: suscripción activa (Stripe) O trial no expirado. Demo (issuer_id <= 0) siempre True.
    """
    if issuer_id is not None and issuer_id <= 0:
        return True
    if user_id and is_subscription_active(user_id):
        return True
    if issuer_id and is_issuer_trial_active(issuer_id):
        return True
    return False

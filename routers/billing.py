"""Billing: Checkout Stripe y webhook."""
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from config import SITE_URL, STRIPE_PRICE_ID, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from services import audit
from services.action_log import log_action
from services.auth import session as session_service
from services.auth import users as users_service
from services.billing import subscription as subscription_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])


def _get_session_user_and_issuer_id(request: Request) -> tuple[int | None, int | None]:
    """Devuelve (user_id, issuer_id) de la cookie de sesión o (None, None)."""
    cookie_val = request.cookies.get(session_service.get_session_cookie_name())
    data = session_service.verify_session(cookie_val)
    if not data or data[0] <= 0:
        return None, None
    return data[0], data[1]


@router.post("/billing/checkout")
def billing_checkout(request: Request):
    """
    Crea una sesión de Stripe Checkout (subscription) y devuelve la URL.
    Requiere sesión con user_id > 0.
    """
    user_id, issuer_id = _get_session_user_and_issuer_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Inicia sesión para actualizar tu plan")

    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(status_code=503, detail="Pagos no configurados")

    user = users_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    email = (user.get("email") or "").strip()

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        base_url = (SITE_URL or str(request.base_url)).rstrip("/")
        success_url = f"{base_url}/portal/plan?success=1"
        cancel_url = f"{base_url}/portal/plan?canceled=1"

        session_params = {
            "mode": "subscription",
            "line_items": [{"price": STRIPE_PRICE_ID, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": str(user_id),
        }
        if email:
            session_params["customer_email"] = email

        checkout_session = stripe.checkout.Session.create(**session_params)
        url = checkout_session.get("url")
        if not url:
            raise HTTPException(status_code=500, detail="No se obtuvo URL de checkout")
        try:
            audit.log(action="plan_checkout_started", user_id=user_id, issuer_id=issuer_id or 0, request=request, entity="stripe", entity_id=str(checkout_session.get("id") or ""))
        except Exception:
            pass
        log_action(request, "plan_checkout_started", user_id=user_id, issuer_id=issuer_id or 0)
        return {"url": url}
    except Exception as e:
        logger.exception("Stripe checkout: %s", e)
        raise HTTPException(status_code=500, detail="Error al crear sesión de pago")


@router.post("/webhooks/stripe")
async def webhook_stripe(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """
    Webhook Stripe: activa o cancela suscripción según eventos.
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook no configurado")

    body = await request.body()

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(body, stripe_signature or "", STRIPE_WEBHOOK_SECRET)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Payload inválido")
    except Exception as e:
        logger.warning("Webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Firma inválida")

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        user_id_str = session_data.get("client_reference_id")
        if user_id_str and user_id_str.isdigit():
            user_id = int(user_id_str)
            customer_id = session_data.get("customer")
            subscription_id = session_data.get("subscription")
            subscription_service.upsert_subscription(
                user_id,
                plan="pro",
                status="active",
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
            )
            logger.info("Subscription activated for user_id=%s", user_id)
            log_action(request, "plan_changed", user_id=user_id, status="active", plan="pro", stripe_subscription_id=subscription_id)

    elif event["type"] == "customer.subscription.updated":
        sub = event["data"]["object"]
        status = (sub.get("status") or "").lower()
        subscription_id = sub.get("id")
        if status in ("canceled", "unpaid", "past_due"):
            _mark_subscription_by_stripe_id(subscription_id, "canceled" if status == "canceled" else status)
            log_action(request, "plan_changed", status=status, stripe_subscription_id=subscription_id)
        elif status == "active":
            period_end = sub.get("current_period_end")
            from datetime import datetime
            period_end_str = datetime.utcfromtimestamp(period_end).isoformat() + "Z" if period_end else None
            _update_subscription_period_by_stripe_id(subscription_id, period_end_str)
            log_action(request, "plan_period_updated", stripe_subscription_id=subscription_id, current_period_end=period_end_str)

    elif event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        _mark_subscription_by_stripe_id(sub.get("id"), "canceled")
        log_action(request, "plan_changed", status="canceled", stripe_subscription_id=sub.get("id"))

    elif event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        stripe_sub_id = invoice.get("subscription")
        if stripe_sub_id:
            _notify_payment_failed(stripe_sub_id)
            log_action(request, "payment_failed", stripe_subscription_id=stripe_sub_id)

    elif event["type"] == "customer.subscription.trial_will_end":
        sub = event["data"]["object"]
        stripe_sub_id = sub.get("id")
        if stripe_sub_id:
            _notify_trial_ending(stripe_sub_id)
            log_action(request, "trial_will_end", stripe_subscription_id=stripe_sub_id)

    return JSONResponse(content={"received": True})


def _mark_subscription_by_stripe_id(stripe_subscription_id: str, status: str) -> None:
    from database import db
    conn = db()
    try:
        cur = conn.execute(
            "UPDATE subscriptions SET status = ?, updated_at = datetime('now') WHERE stripe_subscription_id = ?",
            (status, stripe_subscription_id),
        )
        conn.commit()
        if cur.rowcount:
            logger.info("Subscription %s set to %s", stripe_subscription_id, status)
    finally:
        conn.close()


def _update_subscription_period_by_stripe_id(stripe_subscription_id: str, current_period_end: Optional[str]) -> None:
    from database import db
    conn = db()
    try:
        conn.execute(
            "UPDATE subscriptions SET current_period_end = ?, updated_at = datetime('now') WHERE stripe_subscription_id = ?",
            (current_period_end, stripe_subscription_id),
        )
        conn.commit()
    finally:
        conn.close()


def _get_user_for_stripe_sub(stripe_subscription_id: str) -> Optional[dict]:
    """Find the user associated with a Stripe subscription."""
    from database import db_rows
    rows = db_rows(
        """SELECT u.email, u.id AS user_id, s.id AS sub_id,
                  m.issuer_id
           FROM subscriptions s
           JOIN users u ON u.id = s.user_id
           LEFT JOIN memberships m ON m.user_id = u.id
           WHERE s.stripe_subscription_id = ?
           LIMIT 1""",
        (stripe_subscription_id,),
    )
    return rows[0] if rows else None


def _notify_payment_failed(stripe_subscription_id: str) -> None:
    """Enqueue a payment_failed email to the subscription owner."""
    user = _get_user_for_stripe_sub(stripe_subscription_id)
    if not user:
        return
    try:
        from services.email.queue import enqueue_send_email
        enqueue_send_email(
            to_email=user["email"],
            template="payment_failed",
            context={
                "brand_name": "ContaNeta",
                "billing_url": "/portal/plan",
            },
            email_type="payment_failed",
            issuer_id=user.get("issuer_id"),
            user_id=user["user_id"],
        )
    except Exception as exc:
        logger.warning("Failed to enqueue payment_failed email: %s", exc)


def _notify_trial_ending(stripe_subscription_id: str) -> None:
    """Enqueue a trial_expiring email when Stripe notifies trial will end."""
    user = _get_user_for_stripe_sub(stripe_subscription_id)
    if not user:
        return
    try:
        from services.email.queue import enqueue_send_email
        enqueue_send_email(
            to_email=user["email"],
            template="trial_expiring",
            context={
                "days_left": 3,
                "brand_name": "ContaNeta",
                "billing_url": "/portal/plan",
            },
            email_type="trial_expiring",
            issuer_id=user.get("issuer_id"),
            user_id=user["user_id"],
        )
    except Exception as exc:
        logger.warning("Failed to enqueue trial_expiring email: %s", exc)

"""Stripe integration (real Checkout / portal / webhooks). Only used when
ZZPAY_STRIPE_SECRET_KEY and ZZPAY_STRIPE_PRICE_ID are set; otherwise billing runs in clearly
labelled demo mode (see routers/billing.py).

The server is the only source of truth for a user's plan. The plan changes ONLY from a Stripe
webhook whose signature was verified with ZZPAY_STRIPE_WEBHOOK_SECRET. Users are matched by ids
we stored ourselves (customer / subscription id) or by the ``user_id`` metadata we attached when
creating the Checkout Session - never by anything the browser sends.

The Stripe Price referenced by ZZPAY_STRIPE_PRICE_ID must be a recurring monthly price in CAD.
"""

import json
import logging
from datetime import datetime, timezone

import stripe
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app import email as mailer
from app.config import settings
from app.models import Plan, User

logger = logging.getLogger("tradetrack.stripe")

ACTIVE_STATUSES = {"active", "trialing", "past_due"}  # past_due keeps access while Stripe retries payment
ENDED_STATUSES = {"canceled", "unpaid", "incomplete_expired"}


class BillingError(Exception):
    pass


class WebhookError(Exception):
    pass


def _client() -> stripe.StripeClient:
    return stripe.StripeClient(settings.stripe_secret_key, max_network_retries=1)


def _dt(ts) -> datetime | None:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None


async def create_checkout_url(user: User) -> str:
    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_price_id, "quantity": 1}],
        "client_reference_id": str(user.id),
        "metadata": {"user_id": str(user.id)},
        "subscription_data": {"metadata": {"user_id": str(user.id)}},
        "success_url": f"{settings.frontend_origin}/dashboard?billing=success",
        "cancel_url": f"{settings.frontend_origin}/dashboard?billing=cancel",
    }
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email
    try:
        session = await _client().v1.checkout.sessions.create_async(params=params)
    except stripe.StripeError as exc:
        logger.error("Stripe checkout failed (%s)", type(exc).__name__)
        raise BillingError() from exc
    return session.url


async def create_portal_url(user: User) -> str:
    try:
        session = await _client().v1.billing_portal.sessions.create_async(
            params={
                "customer": user.stripe_customer_id,
                "return_url": f"{settings.frontend_origin}/dashboard",
            }
        )
    except stripe.StripeError as exc:
        logger.error("Stripe portal failed (%s)", type(exc).__name__)
        raise BillingError() from exc
    return session.url


async def cancel_for_account_deletion(user: User) -> None:
    """Cancel the user's live subscription (if any) before the account is deleted."""
    if not (settings.stripe_configured and user.stripe_subscription_id):
        return
    if user.subscription_status in ENDED_STATUSES:
        return
    try:
        await _client().v1.subscriptions.cancel_async(user.stripe_subscription_id)
    except stripe.InvalidRequestError as exc:
        if getattr(exc, "code", None) == "resource_missing":
            return  # already gone at Stripe
        raise BillingError() from exc
    except stripe.StripeError as exc:
        raise BillingError() from exc


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
def verify_event(payload: bytes, signature: str | None) -> dict:
    """Verify the Stripe signature and return the event as a plain dict. Raises WebhookError."""
    if not settings.stripe_webhook_secret.strip():
        raise WebhookError("webhook secret not configured")
    try:
        stripe.Webhook.construct_event(payload, signature or "", settings.stripe_webhook_secret)
        return json.loads(payload)
    except (stripe.SignatureVerificationError, ValueError) as exc:
        raise WebhookError("bad signature") from exc


async def _find_user(session: AsyncSession, *, customer: str | None, subscription: str | None, user_id: str | None) -> User | None:
    from uuid import UUID

    if subscription:
        u = (await session.execute(select(User).where(User.stripe_subscription_id == subscription))).scalar_one_or_none()
        if u:
            return u
    if customer:
        u = (await session.execute(select(User).where(User.stripe_customer_id == customer))).scalar_one_or_none()
        if u:
            return u
    if user_id:
        try:
            return await session.get(User, UUID(user_id))
        except ValueError:
            return None
    return None


def _apply_subscription(user: User, sub: dict) -> None:
    status = sub.get("status")
    user.stripe_subscription_id = sub.get("id") or user.stripe_subscription_id
    user.subscription_status = status
    user.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    end = sub.get("current_period_end")
    if not end:
        items = (sub.get("items") or {}).get("data") or []
        end = items[0].get("current_period_end") if items else None
    user.current_period_end = _dt(end)
    if status in ACTIVE_STATUSES:
        user.plan = Plan.PREMIUM.value
    elif status in ENDED_STATUSES:
        user.plan = Plan.FREE.value


async def handle_event(session: AsyncSession, event: dict) -> str:
    """Apply a verified Stripe event. Idempotent. Returns a short note for logging."""
    etype = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        if obj.get("mode") != "subscription":
            return "ignored (not a subscription checkout)"
        user = await _find_user(
            session, customer=obj.get("customer"), subscription=obj.get("subscription"),
            user_id=obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id"),
        )
        if user is None:
            return "ignored (no matching user)"
        was_premium = user.plan == Plan.PREMIUM.value
        user.stripe_customer_id = obj.get("customer") or user.stripe_customer_id
        user.stripe_subscription_id = obj.get("subscription") or user.stripe_subscription_id
        if obj.get("payment_status") in ("paid", "no_payment_required"):
            user.plan = Plan.PREMIUM.value
            user.subscription_status = "active"
        session.add(user)
        if not was_premium and user.plan == Plan.PREMIUM.value:
            await mailer.send_upgrade_confirmation(user, "stripe")  # once: later events see Premium already
        return "checkout completed"

    if etype in ("customer.subscription.updated", "customer.subscription.created", "customer.subscription.deleted"):
        user = await _find_user(
            session, customer=obj.get("customer"), subscription=obj.get("id"),
            user_id=(obj.get("metadata") or {}).get("user_id"),
        )
        if user is None:
            return "ignored (no matching user)"
        # Ignore the end of an OLD subscription when the user already has a different, current one.
        ends = etype == "customer.subscription.deleted" or obj.get("status") in ENDED_STATUSES
        if ends and user.stripe_subscription_id and obj.get("id") and obj["id"] != user.stripe_subscription_id:
            return "ignored (not the current subscription)"
        if obj.get("customer"):
            user.stripe_customer_id = obj["customer"]
        if etype == "customer.subscription.deleted":
            obj = {**obj, "status": "canceled"}
        was_premium = user.plan == Plan.PREMIUM.value
        _apply_subscription(user, obj)
        session.add(user)
        if not was_premium and user.plan == Plan.PREMIUM.value:
            await mailer.send_upgrade_confirmation(user, "stripe")
        return f"subscription {obj.get('status')}"

    if etype == "invoice.payment_failed":
        user = await _find_user(session, customer=obj.get("customer"), subscription=obj.get("subscription"), user_id=None)
        if user is None:
            return "ignored (no matching user)"
        user.subscription_status = "past_due"  # access continues while Stripe retries; subscription events decide the rest
        session.add(user)
        return "payment failed"

    return "ignored"

"""Billing. Real Stripe Checkout when configured, otherwise a clearly labelled DEMO mode.

* ``mode = "stripe"``: Checkout subscription (CAD price from ZZPAY_STRIPE_PRICE_ID), customer portal,
  and a signature-verified webhook that is the only thing that changes a paid plan.
* ``mode = "demo"``: ``/demo/upgrade`` and ``/demo/downgrade`` flip the plan on the server so the
  free/premium behaviour can be shown. NO payment is taken.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import email as mailer
from app import stripe_service
from app.auth import CurrentUser
from app.config import settings
from app.database import get_session
from app.models import Plan, as_utc

logger = logging.getLogger("tradetrack.billing")
router = APIRouter(prefix="/api/billing", tags=["billing"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _status_payload(user) -> dict:
    return {
        "plan": user.plan,
        "subscription_status": user.subscription_status,
        "mode": settings.billing_mode,
        "can_manage": settings.stripe_configured and bool(user.stripe_customer_id),
        "current_period_end": as_utc(user.current_period_end).isoformat() if user.current_period_end else None,
        "cancel_at_period_end": bool(user.cancel_at_period_end),
    }


@router.get("/status")
async def billing_status(user: CurrentUser) -> dict:
    return _status_payload(user)


@router.post("/checkout")
async def checkout(user: CurrentUser) -> dict:
    if not settings.stripe_configured:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "billing_demo_mode",
             "message": "Payments are not set up on this server. Use the demo upgrade instead (no payment is taken)."},
        )
    if user.plan == Plan.PREMIUM.value and user.subscription_status in ("active", "trialing", "past_due"):
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "already_premium", "message": "You are already on Premium."})
    try:
        return {"url": await stripe_service.create_checkout_url(user)}
    except stripe_service.BillingError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": "billing_unavailable", "message": "The payment provider is unavailable right now. Please try again."},
        ) from None


@router.post("/portal")
async def portal(user: CurrentUser) -> dict:
    if not settings.stripe_configured:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "billing_demo_mode", "message": "Payments are not set up on this server (demo mode)."},
        )
    if not user.stripe_customer_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "no_billing_account", "message": "There is no billing account to manage yet."},
        )
    try:
        return {"url": await stripe_service.create_portal_url(user)}
    except stripe_service.BillingError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": "billing_unavailable", "message": "The payment provider is unavailable right now. Please try again."},
        ) from None


def _require_demo() -> None:
    if settings.billing_mode != "demo":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.post("/demo/upgrade")
async def demo_upgrade(user: CurrentUser, session: SessionDep) -> dict:
    _require_demo()
    was_premium = user.plan == Plan.PREMIUM.value
    user.plan = Plan.PREMIUM.value
    user.subscription_status = "demo"
    user.cancel_at_period_end = False
    session.add(user)
    await session.flush()
    out = _status_payload(user)
    # "sent" | "failed" | "not_configured" | null (already Premium, nothing to confirm)
    out["confirmation_email"] = None if was_premium else await mailer.send_upgrade_confirmation(user, "demo")
    return out


@router.post("/demo/downgrade")
async def demo_downgrade(user: CurrentUser, session: SessionDep) -> dict:
    _require_demo()
    user.plan = Plan.FREE.value
    user.subscription_status = None
    user.cancel_at_period_end = False
    session.add(user)
    await session.flush()
    return _status_payload(user)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, session: SessionDep) -> dict:
    """Stripe -> server only. Rejects anything without a valid signature."""
    if not settings.stripe_configured:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    payload = await request.body()
    try:
        event = stripe_service.verify_event(payload, request.headers.get("stripe-signature"))
    except stripe_service.WebhookError as exc:
        # Missing secret is a server problem; a bad signature is the caller's.
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "not configured" in str(exc) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, {"code": "invalid_webhook", "message": "Webhook could not be verified"}) from None
    note = await stripe_service.handle_event(session, event)
    logger.info("stripe webhook %s: %s", event.get("type"), note)
    return {"received": True}

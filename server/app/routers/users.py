"""Accounts: register / login / logout / profile, forwarding alias, inbound log, data export, delete."""

import json
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app import stripe_service, storage
from app.auth import (
    CurrentUser,
    clear_auth_cookie,
    create_token,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from app.config import settings
from app.database import get_session
from app.models import (
    DeleteAccount,
    InboundEvent,
    Receipt,
    UsageEvent,
    User,
    UserCreate,
    UserOut,
    UserUpdate,
    as_utc,
    receipt_to_out,
    user_to_out,
)
from app.ratelimit import limiter
from app.usage import usage_summary

logger = logging.getLogger("tradetrack.users")
router = APIRouter(prefix="/api", tags=["users"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Verified against when the email is unknown, so response time does not reveal which emails exist.
_DUMMY_HASH = hash_password("not-a-real-password")


def new_alias() -> str:
    """Secret local-part of the forwarding address (80 random bits, lowercase hex)."""
    return "r" + secrets.token_hex(10)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many() -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        {"code": "rate_limited", "message": "Too many attempts. Please wait a few minutes and try again."},
    )


async def _get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.strip().lower()))
    return result.scalar_one_or_none()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, response: Response, session: SessionDep) -> UserOut:
    email = str(body.email).strip().lower()
    if await _get_by_email(session, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    user = User(
        email=email,
        first_name=body.first_name,
        last_name=body.last_name,
        password_hash=hash_password(body.password),
        business_name=body.business_name,
        province=body.province.value,
        accountant_email=str(body.accountant_email).lower() if body.accountant_email else None,
        forwarding_alias=new_alias(),
        # plan is ALWAYS FREE at signup; nothing in the request can change that
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists") from None
    set_auth_cookie(response, create_token(user))
    return user_to_out(user)


@router.post("/login")
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    session: SessionDep,
) -> dict:
    """Email goes in the ``username`` field (OAuth2 form, so Swagger's Authorize works)."""
    email = form.username.strip().lower()
    window = settings.login_window_seconds
    email_key, ip_key = f"login:{email}", f"login-ip:{_client_ip(request)}"
    if limiter.is_limited(email_key, settings.login_max_attempts, window) or \
            limiter.is_limited(ip_key, settings.login_max_attempts * 5, window):
        raise _too_many()

    user = await _get_by_email(session, email)
    ok = verify_password(form.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok:
        limiter.hit(email_key, window)
        limiter.hit(ip_key, window)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    limiter.reset(email_key)
    token = create_token(user)
    set_auth_cookie(response, token)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response) -> dict:
    clear_auth_cookie(response)
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return user_to_out(user)


@router.put("/me", response_model=UserOut)
async def update_me(body: UserUpdate, user: CurrentUser, session: SessionDep) -> UserOut:
    """Update the caller's own profile. Plan, billing and alias fields cannot be set here."""
    sent = body.model_fields_set
    for field in ("first_name", "last_name"):
        if field in sent and getattr(body, field) is not None:
            setattr(user, field, getattr(body, field).strip())
    if "business_name" in sent:
        user.business_name = body.business_name
    if "province" in sent and body.province is not None:
        user.province = body.province.value
    if "accountant_email" in sent:
        user.accountant_email = str(body.accountant_email).lower() if body.accountant_email else None
    if "gst_hst_registered" in sent:
        user.gst_hst_registered = body.gst_hst_registered
    if "gst_hst_number" in sent:
        user.gst_hst_number = body.gst_hst_number
    session.add(user)
    await session.flush()
    return user_to_out(user)


@router.post("/me/forwarding-alias/rotate", response_model=UserOut)
async def rotate_alias(user: CurrentUser, session: SessionDep) -> UserOut:
    user.forwarding_alias = new_alias()  # the old address stops working immediately
    session.add(user)
    await session.flush()
    return user_to_out(user)


@router.get("/me/inbound-log")
async def inbound_log(user: CurrentUser, session: SessionDep) -> list[dict]:
    rows = (
        await session.execute(
            select(InboundEvent)
            .where(InboundEvent.user_id == user.id)
            .order_by(InboundEvent.received_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [
        {
            "id": str(e.id),
            "received_at": as_utc(e.received_at).isoformat(),
            "status": e.status,
            "reason": e.reason,
            "attachments": e.attachments,
            "receipt_ids": e.receipt_ids or [],
        }
        for e in rows
    ]


@router.get("/me/export")
async def export_account(user: CurrentUser, session: SessionDep) -> Response:
    """Everything TradeTrack holds about the account, as JSON (privacy / portability).
    Original files are not embedded; fetch them from each receipt's /file route."""
    receipts = (
        await session.execute(select(Receipt).where(Receipt.user_id == user.id).order_by(Receipt.created_at))
    ).scalars().all()
    events = (
        await session.execute(select(InboundEvent).where(InboundEvent.user_id == user.id).order_by(InboundEvent.received_at))
    ).scalars().all()
    payload = {
        "account": user_to_out(user).model_dump(mode="json"),
        "usage": await usage_summary(session, user),
        "receipts": [receipt_to_out(r).model_dump(mode="json") for r in receipts],
        "inbound_log": [
            {"received_at": as_utc(e.received_at).isoformat(), "status": e.status, "reason": e.reason,
             "attachments": e.attachments, "receipt_ids": e.receipt_ids or []}
            for e in events
        ],
        "note": "Original receipt files are not included in this export; download them from each receipt.",
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="tradetrack-account-export.json"', "Cache-Control": "private, no-store"},
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(body: DeleteAccount, user: CurrentUser, session: SessionDep) -> Response:
    """Permanently delete the account, its receipts and files. Requires the password."""
    key = f"delete:{user.id}"
    if limiter.is_limited(key, 5, settings.login_window_seconds):
        raise _too_many()
    if not verify_password(body.password, user.password_hash):
        limiter.hit(key, settings.login_window_seconds)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Incorrect password")

    # Do not leave a live paid subscription behind.
    try:
        await stripe_service.cancel_for_account_deletion(user)
    except stripe_service.BillingError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": "subscription_cancel_failed",
             "message": "We could not cancel your subscription with our payment provider, so the account was not deleted. Please try again or cancel it from the billing portal first."},
        ) from None

    receipts = list((await session.execute(select(Receipt).where(Receipt.user_id == user.id))).scalars().all())
    await storage.delete_user_files(session, user.id, receipts)
    await session.execute(delete(Receipt).where(Receipt.user_id == user.id))
    await session.execute(delete(UsageEvent).where(UsageEvent.user_id == user.id))
    await session.execute(delete(InboundEvent).where(InboundEvent.user_id == user.id))
    await session.delete(user)
    await session.flush()
    done = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookie(done)
    return done

"""Authentication helpers: password hashing, JWT tokens, and the
``get_current_user`` dependency used to protect endpoints.

The token is delivered to the browser as an httponly cookie (``tradetrack_token``)
so JavaScript can't read it; an ``Authorization: Bearer`` header is also accepted
for API clients / Swagger.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import User

COOKIE_NAME = "tradetrack_token"

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")


# --- passwords -------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd.verify(password, password_hash)


# --- tokens ----------------------------------------------------------------- #
def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + timedelta(hours=settings.token_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


# --- current user dependency ------------------------------------------------ #
def _extract_token(request: Request) -> str | None:
    """Prefer the cookie; fall back to a Bearer header."""
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:]
    return None


async def _user_from_request(request: Request, session: AsyncSession) -> User | None:
    """Resolve the user from the cookie/header token, or None if not (validly) authed."""
    token = _extract_token(request)
    if not token:
        return None
    payload = _decode_token(token)
    if payload is None or "sub" not in payload:
        return None
    try:
        return await session.get(User, UUID(str(payload["sub"])))
    except ValueError:
        return None


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Strict dependency: 401 when there is no valid, current account."""
    user = await _user_from_request(request, session)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


# Cookie attributes are shared by login/register (set) and logout (clear).
def cookie_kwargs() -> dict:
    samesite = settings.cookie_samesite.lower()
    if samesite not in ("lax", "strict", "none"):
        samesite = "lax"
    return {
        "httponly": True,
        "samesite": samesite,
        # HTTPS-only outside development (SameSite=None also requires Secure).
        "secure": (not settings.is_development) or samesite == "none",
        "path": "/",
    }


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=settings.token_ttl_hours * 3600, **cookie_kwargs())


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, **cookie_kwargs())


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_premium_user(user: CurrentUser) -> User:
    """Strict dependency for Premium-only routes: 402 on the Free plan."""
    if user.plan != "PREMIUM":
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {"code": "premium_required", "message": "This feature is included in the Premium plan."},
        )
    return user


PremiumUser = Annotated[User, Depends(get_premium_user)]

"""Forgot / reset password: emailed single-use link, no account enumeration."""

import re

from app.auth import create_reset_token, create_token
from app.config import settings

from .conftest import register


def _token(brevo) -> str:
    text = brevo[-1]["payload"]["textContent"]
    return re.search(r"token=([\w\-.]+)", text).group(1)


async def _forgot(client, email):
    return await client.post("/api/password/forgot", json={"email": email})


async def test_forgot_without_email_provider_is_503(client):
    await register(client, "a@example.com")
    r = await _forgot(client, "a@example.com")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "email_not_configured"


async def test_forgot_sends_link_to_owner_only(client, brevo):
    await register(client, "a@example.com")
    brevo.clear()  # drop the welcome email
    r = await _forgot(client, "A@Example.com")
    assert r.status_code == 200
    assert len(brevo) == 1
    p = brevo[0]["payload"]
    assert p["to"] == [{"email": "a@example.com"}]
    assert "/reset-password?token=" in p["textContent"]
    assert "password123" not in p["textContent"]


async def test_forgot_unknown_email_looks_identical_and_sends_nothing(client, brevo):
    await register(client, "a@example.com")
    brevo.clear()
    known = await _forgot(client, "a@example.com")
    unknown = await _forgot(client, "nobody@example.com")
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert len(brevo) == 1  # only the real account got mail


async def test_forgot_is_rate_limited(client, brevo):
    await register(client, "a@example.com")
    codes = [(await _forgot(client, "a@example.com")).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


async def test_reset_changes_password_and_link_is_single_use(client, brevo):
    await register(client, "a@example.com")
    await _forgot(client, "a@example.com")
    token = _token(brevo)
    brevo.clear()

    r = await client.post("/api/password/reset", json={"token": token, "password": "brand-new-pass"})
    assert r.status_code == 200
    assert "was just changed" in brevo[0]["payload"]["textContent"]
    assert "brand-new-pass" not in brevo[0]["payload"]["textContent"]

    await client.post("/api/logout")
    old = await client.post("/api/login", data={"username": "a@example.com", "password": "password123"})
    new = await client.post("/api/login", data={"username": "a@example.com", "password": "brand-new-pass"})
    assert old.status_code == 401 and new.status_code == 200

    again = await client.post("/api/password/reset", json={"token": token, "password": "another-pass-1"})
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "invalid_reset_link"


async def test_reset_rejects_bad_expired_and_session_tokens(client, brevo, monkeypatch):
    me = await register(client, "a@example.com")
    from sqlalchemy import select
    from app.models import User
    from app.database import get_session
    from app.main import app

    async for s in app.dependency_overrides[get_session]():
        user = (await s.execute(select(User).where(User.email == "a@example.com"))).scalar_one()
        session_jwt, reset_jwt = create_token(user), create_reset_token(user)

    for bad in ("garbage-token-value", session_jwt):
        r = await client.post("/api/password/reset", json={"token": bad, "password": "brand-new-pass"})
        assert r.status_code == 400

    import app.auth as auth
    monkeypatch.setattr(auth, "RESET_TTL_MINUTES", -5)
    expired = auth.create_reset_token(user)
    r = await client.post("/api/password/reset", json={"token": expired, "password": "brand-new-pass"})
    assert r.status_code == 400

    ok = await client.post("/api/password/reset", json={"token": reset_jwt, "password": "brand-new-pass"})
    assert ok.status_code == 200


async def test_reset_enforces_password_length(client, brevo):
    await register(client, "a@example.com")
    await _forgot(client, "a@example.com")
    r = await client.post("/api/password/reset", json={"token": _token(brevo), "password": "short"})
    assert r.status_code == 422


async def test_reset_token_does_not_authenticate(client, brevo):
    await register(client, "a@example.com")
    await _forgot(client, "a@example.com")
    await client.post("/api/logout")
    r = await client.get("/api/me", headers={"Authorization": f"Bearer {_token(brevo)}"})
    assert r.status_code == 401

"""Welcome email, Premium order confirmation and the Brevo (HTTPS) delivery path."""

import json

import pytest

from app import email as mailer
from app.config import settings

from .billing_helpers import stripe_header
from .conftest import register


@pytest.fixture
def brevo(monkeypatch):
    """Configure Brevo and capture what would be POSTed. Returns the list of captured calls."""
    class Calls(list):
        state = {"status": 201}

    calls = Calls()
    state = calls.state

    async def fake_post(url, headers, payload, timeout):
        calls.append({"url": url, "headers": headers, "payload": payload})
        return state["status"]

    monkeypatch.setattr(settings, "brevo_api_key", "xkeysib-test-key")
    monkeypatch.setattr(settings, "smtp_from", "TradeTrack <sender@example.com>")
    monkeypatch.setattr(mailer, "_post_json", fake_post)
    return calls


async def test_register_without_email_provider_says_not_configured(client):
    me = await register(client, "new@example.com")
    assert me["welcome_email"] == "not_configured"
    assert (await client.get("/api/me")).status_code == 200  # signed up and signed in regardless


async def test_welcome_email_sent_through_brevo(client, brevo):
    me = await register(client, "new@example.com")
    assert me["welcome_email"] == "sent"
    assert len(brevo) == 1
    call = brevo[0]
    assert call["url"] == "https://api.brevo.com/v3/smtp/email"
    assert call["headers"]["api-key"] == "xkeysib-test-key"
    p = call["payload"]
    assert p["sender"] == {"name": "TradeTrack", "email": "sender@example.com"}
    assert p["to"] == [{"email": "new@example.com"}]
    assert p["subject"] == "Welcome to TradeTrack"
    assert "password123" not in json.dumps(p)  # the password never goes into an email
    assert "xkeysib" not in json.dumps(p["textContent"])
    assert "not tax advice" in p["textContent"]


async def test_welcome_email_failure_never_blocks_signup(client, brevo, monkeypatch):
    brevo.state["status"] = 401  # e.g. wrong API key
    me = await register(client, "new@example.com")
    assert me["welcome_email"] == "failed"
    assert (await client.get("/api/me")).json()["email"] == "new@example.com"


async def test_welcome_email_network_error_never_blocks_signup(client, brevo, monkeypatch):
    async def boom(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(mailer, "_post_json", boom)
    me = await register(client, "new@example.com")
    assert me["welcome_email"] == "failed"
    assert (await client.get("/api/me")).status_code == 200


async def test_demo_upgrade_sends_confirmation_once(client, brevo):
    await register(client, "buyer@example.com")
    brevo.clear()
    first = (await client.post("/api/billing/demo/upgrade")).json()
    assert first["confirmation_email"] == "sent" and first["plan"] == "PREMIUM"
    text = brevo[0]["payload"]["textContent"]
    assert brevo[0]["payload"]["subject"] == "Your TradeTrack Premium confirmation"
    assert "CAD 5.99 per month" in text and "demo upgrade" in text and "not charged" in text
    again = (await client.post("/api/billing/demo/upgrade")).json()
    assert again["confirmation_email"] is None and len(brevo) == 1  # already Premium: no second email


async def test_demo_upgrade_without_email_provider(client):
    await register(client, "buyer@example.com")
    r = (await client.post("/api/billing/demo/upgrade")).json()
    assert r["plan"] == "PREMIUM" and r["confirmation_email"] == "not_configured"


async def test_stripe_checkout_sends_one_confirmation_labelled_test_mode(client, brevo, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    me = await register(client, "buyer@example.com")
    brevo.clear()
    done = {"type": "checkout.session.completed", "data": {"object": {
        "mode": "subscription", "customer": "cus_1", "subscription": "sub_1", "payment_status": "paid",
        "client_reference_id": me["id"]}}}
    payload = json.dumps(done).encode()
    for _ in range(2):  # Stripe may deliver the same event twice
        r = await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": stripe_header(payload, "whsec_test")})
        assert r.status_code == 200
    created = {"type": "customer.subscription.created", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "active", "current_period_end": 1893456000}}}
    p2 = json.dumps(created).encode()
    await client.post("/api/billing/webhook", content=p2, headers={"stripe-signature": stripe_header(p2, "whsec_test")})
    assert len(brevo) == 1  # one order confirmation, however many events arrive
    text = brevo[0]["payload"]["textContent"]
    assert "TEST MODE" in text and "no real money was charged" in text and "CAD 5.99 per month" in text


async def test_webhook_still_succeeds_when_email_fails(client, brevo, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    me = await register(client, "buyer@example.com")
    brevo.state["status"] = 500
    done = {"type": "checkout.session.completed", "data": {"object": {
        "mode": "subscription", "customer": "cus_1", "subscription": "sub_1", "payment_status": "paid",
        "client_reference_id": me["id"]}}}
    payload = json.dumps(done).encode()
    r = await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": stripe_header(payload, "whsec_test")})
    assert r.status_code == 200 and (await client.get("/api/me")).json()["plan"] == "PREMIUM"


async def test_config_reports_email_configured_for_brevo(client, brevo):
    assert (await client.get("/api/config")).json()["services"]["smtp_configured"] is True


async def test_accountant_email_goes_through_brevo_with_attachments(client, brevo):
    from .conftest import upgrade

    await register(client, "owner@example.com")
    await upgrade(client)
    await client.put("/api/me", json={"accountant_email": "acct@example.com"})
    brevo.clear()
    r = await client.post("/api/receipts/export/email", json={"month": "2026-10"})
    assert r.status_code == 200
    p = brevo[0]["payload"]
    assert p["to"] == [{"email": "acct@example.com"}]
    assert {a["name"] for a in p["attachment"]} == {"tradetrack-receipts-2026-10.csv", "tradetrack-summary-2026-10.pdf"}
    assert p["replyTo"]["email"] == "owner@example.com"
    brevo.state["status"] = 400
    bad = await client.post("/api/receipts/export/email", json={"month": "2026-10"})
    assert bad.status_code == 502 and bad.json()["detail"]["code"] == "email_send_failed"

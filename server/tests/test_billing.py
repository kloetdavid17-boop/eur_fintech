import hashlib
import hmac
import json
import time

from app.config import settings

from .conftest import png_bytes, register, upload


async def test_demo_upgrade_downgrade_changes_limits(client, ai):
    await register(client)
    st = (await client.get("/api/billing/status")).json()
    assert st == {"plan": "FREE", "subscription_status": None, "mode": "demo", "can_manage": False,
                  "current_period_end": None, "cancel_at_period_end": False}
    ids = [(await upload(client, png_bytes(i)))["id"] for i in range(7)]
    for rid in ids[:5]:
        await client.post(f"/api/receipts/{rid}/save")
    assert (await client.post(f"/api/receipts/{ids[5]}/save")).status_code == 402
    assert (await client.post("/api/billing/demo/upgrade")).json()["plan"] == "PREMIUM"
    assert (await client.get("/api/me")).json()["plan"] == "PREMIUM"
    u = (await client.get("/api/receipts/usage")).json()
    assert u["plan"] == "PREMIUM" and u["limit"] is None and u["remaining"] is None
    assert (await client.post(f"/api/receipts/{ids[5]}/save")).status_code == 200
    assert (await client.post(f"/api/receipts/{ids[6]}/save")).status_code == 200
    assert (await client.get("/api/receipts/summary")).status_code == 200
    assert (await client.post("/api/billing/demo/downgrade")).json()["plan"] == "FREE"
    assert (await client.get("/api/receipts/summary")).status_code == 402
    # 7 saved this month already: a new save is blocked after downgrade
    extra = (await upload(client, png_bytes(99)))["id"]
    assert (await client.post(f"/api/receipts/{extra}/save")).status_code == 402
    r = await client.post("/api/billing/checkout")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "billing_demo_mode"


def _stripe_header(payload: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


async def test_stripe_mode_and_webhook(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_price_id", "price_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    cfg = (await client.get("/api/config")).json()
    assert cfg["services"]["billing_mode"] == "stripe"

    me = await register(client)
    assert (await client.post("/api/billing/demo/upgrade")).status_code == 404
    assert (await client.post("/api/billing/demo/downgrade")).status_code == 404
    assert (await client.post("/api/billing/portal")).json()["detail"]["code"] == "no_billing_account"

    event = {"type": "checkout.session.completed", "data": {"object": {
        "mode": "subscription", "customer": "cus_1", "subscription": "sub_1", "payment_status": "paid",
        "client_reference_id": me["id"]}}}
    payload = json.dumps(event).encode()

    bad = await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": "t=1,v1=deadbeef"})
    assert bad.status_code == 400
    assert (await client.post("/api/billing/webhook", content=payload)).status_code == 400
    wrong = await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": _stripe_header(payload, "other")})
    assert wrong.status_code == 400
    stale = await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": _stripe_header(payload, "whsec_test", 1000)})
    assert stale.status_code == 400
    assert (await client.get("/api/me")).json()["plan"] == "FREE"  # nothing changed by rejected calls

    ok = await client.post("/api/billing/webhook", content=payload, headers={"stripe-signature": _stripe_header(payload, "whsec_test")})
    assert ok.status_code == 200
    assert (await client.get("/api/me")).json()["plan"] == "PREMIUM"
    st = (await client.get("/api/billing/status")).json()
    assert st["mode"] == "stripe" and st["can_manage"] is True and st["subscription_status"] == "active"

    upd = {"type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "active", "cancel_at_period_end": True, "current_period_end": 1893456000}}}
    p2 = json.dumps(upd).encode()
    await client.post("/api/billing/webhook", content=p2, headers={"stripe-signature": _stripe_header(p2, "whsec_test")})
    st = (await client.get("/api/billing/status")).json()
    assert st["cancel_at_period_end"] is True and st["current_period_end"].startswith("2030-01-01")

    failed = {"type": "invoice.payment_failed", "data": {"object": {"customer": "cus_1", "subscription": "sub_1"}}}
    p3 = json.dumps(failed).encode()
    await client.post("/api/billing/webhook", content=p3, headers={"stripe-signature": _stripe_header(p3, "whsec_test")})
    st = (await client.get("/api/billing/status")).json()
    assert st["subscription_status"] == "past_due" and st["plan"] == "PREMIUM"

    old = {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_OLD", "customer": "cus_1"}}}
    p4 = json.dumps(old).encode()
    await client.post("/api/billing/webhook", content=p4, headers={"stripe-signature": _stripe_header(p4, "whsec_test")})
    assert (await client.get("/api/me")).json()["plan"] == "PREMIUM"  # an old subscription ending changes nothing

    gone = {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_1", "customer": "cus_1"}}}
    p5 = json.dumps(gone).encode()
    await client.post("/api/billing/webhook", content=p5, headers={"stripe-signature": _stripe_header(p5, "whsec_test")})
    assert (await client.get("/api/me")).json()["plan"] == "FREE"


async def test_webhook_hidden_in_demo_mode(client):
    assert (await client.post("/api/billing/webhook", content=b"{}")).status_code == 404

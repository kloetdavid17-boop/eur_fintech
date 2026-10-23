from app.config import settings

from .conftest import register


async def test_health_and_config(client):
    r = await client.get("/api/health")
    assert r.json() == {"status": "ok", "app": "TradeTrack"}
    cfg = (await client.get("/api/config")).json()
    assert cfg["currency"] == "CAD"
    assert [p["id"] for p in cfg["plans"]] == ["FREE", "PREMIUM"]
    assert cfg["plans"][0]["monthly_receipt_limit"] == 5 and cfg["plans"][1]["monthly_receipt_limit"] is None
    assert cfg["plans"][1]["price_cad"] == "5.99"
    s = cfg["services"]
    assert s["billing_mode"] == "demo" and s["inbound_email_configured"] is False
    assert s["inbound_domain"] is None and s["smtp_configured"] is False and s["file_storage"] == "database"
    assert any(p["code"] == "ON" and p["tax_hint"] == "HST 13%" for p in cfg["provinces"])


async def test_register_sets_cookie_and_hides_secrets(client):
    r = await client.post("/api/register", json={"email": "A@Example.com", "first_name": "A", "last_name": "B",
                                                  "password": "password123", "plan": "PREMIUM"})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "a@example.com" and body["plan"] == "FREE"  # client cannot choose a plan
    assert "password_hash" not in body and "password" not in body
    assert body["forwarding_address"] is None and len(body["forwarding_alias"]) >= 16
    cookie = r.headers["set-cookie"].lower()
    assert "tradetrack_token=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    me = await client.get("/api/me")
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"


async def test_cookie_secure_outside_development(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    r = await client.post("/api/register", json={"email": "p@example.com", "first_name": "A", "last_name": "B", "password": "password123"})
    assert "secure" in r.headers["set-cookie"].lower()


async def test_register_validation_and_duplicate(client):
    await register(client)
    dup = await client.post("/api/register", json={"email": "owner@example.com", "first_name": "A", "last_name": "B", "password": "password123"})
    assert dup.status_code == 409
    short = await client.post("/api/register", json={"email": "x@example.com", "first_name": "A", "last_name": "B", "password": "short"})
    assert short.status_code == 422


async def test_login_logout_me(client, client2):
    await register(client)
    bad = await client2.post("/api/login", data={"username": "owner@example.com", "password": "nope-nope"})
    assert bad.status_code == 401
    ok = await client2.post("/api/login", data={"username": "OWNER@example.com", "password": "password123"})
    assert ok.status_code == 200 and ok.json()["token_type"] == "bearer"
    assert (await client2.get("/api/me")).status_code == 200
    assert (await client2.post("/api/logout")).status_code == 200
    client2.cookies.clear()
    assert (await client2.get("/api/me")).status_code == 401
    # Bearer header also works
    h = {"Authorization": "Bearer " + ok.json()["access_token"]}
    assert (await client2.get("/api/me", headers=h)).status_code == 200


async def test_login_rate_limited(client):
    await register(client)
    for _ in range(settings.login_max_attempts):
        r = await client.post("/api/login", data={"username": "owner@example.com", "password": "wrong-password"})
        assert r.status_code == 401
    r = await client.post("/api/login", data={"username": "owner@example.com", "password": "password123"})
    assert r.status_code == 429


async def test_update_profile_cannot_change_plan(client):
    await register(client)
    r = await client.put("/api/me", json={"business_name": "Pat Plumbing", "province": "QC", "gst_hst_registered": True,
                                           "gst_hst_number": "123456789RT0001", "accountant_email": "acct@example.com", "plan": "PREMIUM"})
    assert r.status_code == 200
    b = r.json()
    assert b["business_name"] == "Pat Plumbing" and b["province"] == "QC" and b["gst_hst_registered"] is True
    assert b["accountant_email"] == "acct@example.com" and b["plan"] == "FREE"
    bad = await client.put("/api/me", json={"province": "ZZ"})
    assert bad.status_code == 422


async def test_unauthenticated_routes_401(client):
    for method, url in [("get", "/api/me"), ("get", "/api/receipts"), ("get", "/api/receipts/usage"),
                        ("get", "/api/receipts/TT-2026-AAAAAA"), ("get", "/api/billing/status"),
                        ("get", "/api/me/inbound-log"), ("get", "/api/me/export")]:
        assert (await getattr(client, method)(url)).status_code == 401, url


async def test_rotate_alias(client):
    u = await register(client)
    r = await client.post("/api/me/forwarding-alias/rotate")
    assert r.status_code == 200 and r.json()["forwarding_alias"] != u["forwarding_alias"]


async def test_account_export_and_delete(client, client2):
    from .conftest import upload

    await register(client)
    await upload(client)
    exp = await client.get("/api/me/export")
    assert exp.status_code == 200
    data = exp.json()
    assert data["account"]["email"] == "owner@example.com" and len(data["receipts"]) == 1
    assert "password_hash" not in exp.text

    assert (await client.request("DELETE", "/api/me", json={"password": "wrong-password"})).status_code == 403
    assert (await client.request("DELETE", "/api/me", json={"password": "password123"})).status_code == 204
    r = await client2.post("/api/login", data={"username": "owner@example.com", "password": "password123"})
    assert r.status_code == 401
    client.cookies.clear()
    assert (await client.get("/api/receipts")).status_code == 401

import hashlib
import hmac
import time

import pytest

from app import extraction
from app.config import settings

from .conftest import GOOD_RECEIPT, png_bytes, register, upgrade

KEY = "mailgun-test-key"
DOMAIN = "receipts.tradetrack.test"


@pytest.fixture(autouse=True)
def _inbound(monkeypatch):
    monkeypatch.setattr(settings, "mailgun_signing_key", KEY)
    monkeypatch.setattr(settings, "inbound_domain", DOMAIN)


def sign(ts=None, token=None, key=KEY):
    ts = str(ts if ts is not None else int(time.time()))
    token = token or hashlib.sha256(str(time.time_ns()).encode()).hexdigest()
    return {"timestamp": ts, "token": token, "signature": hmac.new(key.encode(), (ts + token).encode(), hashlib.sha256).hexdigest()}


async def send(c, alias, files=None, extra=None, sig=None, recipient=None, message_id=None):
    data = {**(sig or sign()), "recipient": recipient or f"{alias}@{DOMAIN}", "sender": "Mallory <a@evil.example>",
            "subject": "Your receipt", "Message-Id": message_id or f"<{time.time_ns()}@mail.example>", **(extra or {})}
    return await c.post("/api/inbound/mailgun", data=data, files=files)


@pytest.fixture
async def premium(client):
    u = await register(client, "p@example.com")
    await upgrade(client)
    return u


async def test_not_configured_503(client, monkeypatch):
    monkeypatch.setattr(settings, "mailgun_signing_key", "")
    r = await client.post("/api/inbound/mailgun", data=sign())
    assert r.status_code == 503
    assert (await client.get("/api/config")).json()["services"]["inbound_email_configured"] is False


async def test_config_and_forwarding_address(client, premium):
    s = (await client.get("/api/config")).json()["services"]
    assert s["inbound_email_configured"] is True and s["inbound_domain"] == DOMAIN
    me = (await client.get("/api/me")).json()
    assert me["forwarding_address"] == f"{me['forwarding_alias']}@{DOMAIN}"


async def test_bad_signature_stale_and_replay(client, premium):
    alias = premium["forwarding_alias"]
    bad = sign(key="wrong-key")
    assert (await send(client, alias, sig=bad)).status_code == 403
    assert (await send(client, alias, sig={**sign(), "signature": ""})).status_code == 403
    stale = sign(ts=int(time.time()) - 3600)
    r = await send(client, alias, sig=stale)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "stale_timestamp"
    good = sign()
    files = {"attachment-1": ("r.png", png_bytes(1), "image/png")}
    assert (await send(client, alias, files=files, sig=good)).status_code == 200
    again = await send(client, alias, files={"attachment-1": ("r.png", png_bytes(2), "image/png")}, sig=good)
    assert again.status_code == 403 and again.json()["detail"]["code"] == "replayed_token"
    # nothing was created by the rejected calls
    assert (await client.get("/api/receipts")).json()["total"] == 1


async def test_unknown_alias_and_wrong_domain(client, premium):
    assert (await send(client, "rdeadbeefdeadbeefdead")).status_code == 406
    assert (await send(client, premium["forwarding_alias"], recipient=f"{premium['forwarding_alias']}@other.example")).status_code == 406
    # sender is irrelevant: the sender address of a real account does not select it
    r = await send(client, "nobody", extra={"sender": "p@example.com", "from": "p@example.com"})
    assert r.status_code == 406
    assert (await client.get("/api/receipts")).json()["total"] == 0


async def test_free_plan_account_rejected(client):
    u = await register(client, "free@example.com")
    r = await send(client, u["forwarding_alias"], files={"attachment-1": ("r.png", png_bytes(3), "image/png")})
    assert r.status_code == 406 and r.json()["detail"]["code"] == "premium_required"
    assert (await client.get("/api/receipts")).json()["total"] == 0
    log = (await client.get("/api/me/inbound-log")).json()
    assert log[0]["status"] == "REJECTED" and log[0]["reason"] == "premium_required"


async def test_good_path_creates_email_receipt_and_log(client, premium, ai):
    files = [("attachment-1", ("receipt.png", png_bytes(5), "image/png"))]
    r = await send(client, premium["forwarding_alias"], files=files)
    assert r.status_code == 200 and r.json()["status"] == "processed"
    items = (await client.get("/api/receipts")).json()["items"]
    assert len(items) == 1
    rec = items[0]
    assert rec["source"] == "EMAIL" and rec["processing_status"] == "NEEDS_REVIEW" and rec["merchant"] == "Canadian Tire"
    assert rec["has_original_file"] is True
    log = (await client.get("/api/me/inbound-log")).json()
    assert len(log) == 1 and log[0]["status"] == "PROCESSED" and log[0]["attachments"] == 1 and log[0]["receipt_ids"] == [rec["id"]]
    assert set(log[0]) == {"id", "received_at", "status", "reason", "attachments", "receipt_ids"}
    assert "evil" not in str(log) and "Your receipt" not in str(log)  # no sender/subject kept


async def test_duplicate_message_and_duplicate_file(client, premium, ai):
    alias = premium["forwarding_alias"]
    f = lambda n: {"attachment-1": ("r.png", png_bytes(n), "image/png")}  # noqa: E731
    assert (await send(client, alias, files=f(7), message_id="<same@x>")).json()["status"] == "processed"
    second = await send(client, alias, files=f(8), message_id="<same@x>")
    assert second.json()["status"] == "duplicate"
    third = await send(client, alias, files=f(7), message_id="<other@x>")  # same file, new message
    assert third.json()["status"] == "duplicate"
    assert (await client.get("/api/receipts")).json()["total"] == 1
    assert ai.calls == 1
    statuses = [e["status"] for e in (await client.get("/api/me/inbound-log")).json()]
    assert statuses.count("DUPLICATE") == 2 and statuses.count("PROCESSED") == 1


async def test_bad_attachments_rejected(client, premium, ai):
    alias = premium["forwarding_alias"]
    r = await send(client, alias, files={"attachment-1": ("evil.exe", b"MZ\x90\x00 not a receipt", "application/pdf"),
                                         "attachment-2": ("x.png", png_bytes(9)[:30], "image/png")})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert (await client.get("/api/receipts")).json()["total"] == 0
    assert ai.calls == 0
    log = (await client.get("/api/me/inbound-log")).json()
    assert log[0]["status"] == "REJECTED" and "unsupported_attachment" in log[0]["reason"]


async def test_oversize_attachment_rejected(client, premium, ai, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    r = await send(client, premium["forwarding_alias"], files={"attachment-1": ("r.png", png_bytes(12), "image/png")})
    assert r.json()["status"] == "rejected"
    assert (await client.get("/api/me/inbound-log")).json()[0]["reason"] == "attachment_too_large"


async def test_body_only_email_uses_text_and_stores_no_body(client, premium, monkeypatch):
    seen = []

    async def spy(doc):
        seen.append(doc)
        import json
        return json.dumps(GOOD_RECEIPT)

    monkeypatch.setattr(extraction, "call_provider", spy)
    body = "<html><body><p>Thanks for your order from Canadian Tire</p><p>Total $113.00 incl HST</p></body></html>"
    r = await send(client, premium["forwarding_alias"], extra={"body-html": body})
    assert r.json()["status"] == "processed"
    assert seen[0].kind == "text" and "Canadian Tire" in seen[0].text and "<p>" not in seen[0].text
    rec = (await client.get("/api/receipts")).json()["items"][0]
    assert rec["source"] == "EMAIL" and rec["has_original_file"] is False
    assert "Thanks for your order" not in str(rec)
    empty = await send(client, premium["forwarding_alias"], extra={"body-plain": "hi"})
    assert empty.json()["status"] == "rejected"


async def test_ai_failure_logged_as_failed(client, premium, ai):
    ai.response = extraction.ExtractionFailed("down")
    r = await send(client, premium["forwarding_alias"], files={"attachment-1": ("r.png", png_bytes(15), "image/png")})
    assert r.status_code == 200 and r.json()["status"] == "failed"
    rec = (await client.get("/api/receipts")).json()["items"][0]
    assert rec["processing_status"] == "FAILED" and rec["source"] == "EMAIL"


async def test_rotated_alias_old_address_stops(client, premium):
    old = premium["forwarding_alias"]
    await client.post("/api/me/forwarding-alias/rotate")
    assert (await send(client, old, files={"attachment-1": ("r.png", png_bytes(20), "image/png")})).status_code == 406

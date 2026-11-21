"""Forwarded receipts through a polled Gmail inbox (no domain). The IMAP server is faked."""

import imaplib
from email.message import EmailMessage

import pytest

from app import inbox
from app.config import settings

from .conftest import png_bytes, register, upgrade

GMAIL = "tradetrack.receipts@gmail.com"


@pytest.fixture(autouse=True)
def _gmail(monkeypatch):
    monkeypatch.setattr(settings, "inbound_gmail_address", GMAIL)
    monkeypatch.setattr(settings, "inbound_gmail_app_password", "abcd efgh ijkl mnop")
    inbox._attempts.clear()
    inbox.state.ok = inbox.state.error = None


def mail(to, *, attachments=(), body="Thanks for your purchase.", sender="Mallory <a@evil.example>",
         subject="Your receipt", message_id="<m1@example.com>", extra_headers=None) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = sender, to, subject, message_id
    for k, v in (extra_headers or {}).items():
        msg[k] = v
    msg.set_content(body)
    for name, data, mime in attachments:
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


@pytest.fixture
async def premium(client):
    u = await register(client, "p@example.com")
    await upgrade(client)
    return u


async def run(db_maker, raw):
    async with db_maker() as s:
        out = await inbox.handle_message(s, raw)
        await s.commit()
    return out


async def test_address_and_config_in_gmail_mode(client, premium):
    me = (await client.get("/api/me")).json()
    assert me["forwarding_address"] == f"tradetrack.receipts+{me['forwarding_alias']}@gmail.com"
    s = (await client.get("/api/config")).json()["services"]
    assert s["inbound_email_configured"] is True and s["inbound_mode"] == "gmail" and s["inbound_ok"] is None


async def test_gmail_alone_does_not_open_the_mailgun_webhook(client):
    r = await client.post("/api/inbound/mailgun", data={"timestamp": "1", "token": "t", "signature": "s"})
    assert r.status_code == 503


async def test_not_configured_means_no_address(client, monkeypatch):
    await register(client, "p@example.com")
    monkeypatch.setattr(settings, "inbound_gmail_app_password", "")
    me = (await client.get("/api/me")).json()
    assert me["forwarding_address"] is None
    assert (await client.get("/api/config")).json()["services"]["inbound_mode"] is None


async def test_attachment_becomes_email_receipt(client, premium, db_maker, ai):
    to = f"tradetrack.receipts+{premium['forwarding_alias']}@gmail.com"
    out = await run(db_maker, mail(to, attachments=[("receipt.png", png_bytes(5), "image/png")]))
    assert out == "processed"
    items = (await client.get("/api/receipts")).json()["items"]
    assert len(items) == 1 and items[0]["source"] == "EMAIL" and items[0]["processing_status"] == "NEEDS_REVIEW"
    log = (await client.get("/api/me/inbound-log")).json()
    assert log[0]["status"] == "PROCESSED" and "evil" not in str(log) and "Your receipt" not in str(log)


async def test_alias_found_in_delivered_to_when_to_is_someone_else(client, premium, db_maker):
    alias = premium["forwarding_alias"]
    raw = mail("Boss <boss@work.example>", attachments=[("r.png", png_bytes(6), "image/png")],
               extra_headers={"Delivered-To": f"tradetrack.receipts+{alias}@gmail.com"})
    assert await run(db_maker, raw) == "processed"


async def test_dots_and_case_in_the_gmail_address_still_match(client, premium, db_maker):
    to = f"Tradetrack.Receipts+{premium['forwarding_alias']}@GMAIL.com"
    assert await run(db_maker, mail(to, attachments=[("r.png", png_bytes(7), "image/png")])) == "processed"


async def test_unknown_or_missing_alias_is_ignored_without_ai(client, premium, db_maker, ai):
    for to in ("tradetrack.receipts+rdeadbeefdeadbeef@gmail.com", GMAIL, "other@gmail.com",
               "evil+" + premium["forwarding_alias"] + "@gmail.com"):
        out = await run(db_maker, mail(to, attachments=[("r.png", png_bytes(8), "image/png")]))
        assert out.startswith("ignored")
    assert ai.calls == 0 and (await client.get("/api/receipts")).json()["total"] == 0


async def test_sender_never_selects_the_account(client, premium, db_maker, ai):
    raw = mail(GMAIL, sender="p@example.com", attachments=[("r.png", png_bytes(9), "image/png")])
    assert (await run(db_maker, raw)).startswith("ignored")
    assert ai.calls == 0


async def test_free_plan_is_rejected_and_logged(client, db_maker):
    u = await register(client, "free@example.com")
    to = f"tradetrack.receipts+{u['forwarding_alias']}@gmail.com"
    assert await run(db_maker, mail(to, attachments=[("r.png", png_bytes(3), "image/png")])) == "rejected_premium_required"
    assert (await client.get("/api/receipts")).json()["total"] == 0
    assert (await client.get("/api/me/inbound-log")).json()[0]["reason"] == "premium_required"


async def test_same_message_twice_is_one_receipt(client, premium, db_maker, ai):
    to = f"tradetrack.receipts+{premium['forwarding_alias']}@gmail.com"
    raw = mail(to, attachments=[("r.png", png_bytes(11), "image/png")], message_id="<same@x>")
    assert await run(db_maker, raw) == "processed"
    assert await run(db_maker, raw) == "duplicate"
    assert (await client.get("/api/receipts")).json()["total"] == 1 and ai.calls == 1


async def test_inline_logo_is_not_a_receipt_but_real_attachment_is(client, premium, db_maker, ai):
    to = f"tradetrack.receipts+{premium['forwarding_alias']}@gmail.com"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Message-ID"] = "shop@example.com", to, "<logo@x>"
    msg.set_content("plain fallback")
    msg.add_alternative('<p>Thanks! <img src="cid:logo"></p>', subtype="html")
    msg.get_payload()[1].add_related(png_bytes(1), "image", "png", cid="<logo>")  # small inline image
    msg.add_attachment(png_bytes(12), maintype="image", subtype="png", filename="receipt.png")
    assert await run(db_maker, msg.as_bytes()) == "processed"
    assert ai.calls == 1 and (await client.get("/api/receipts")).json()["total"] == 1


async def test_body_only_email_is_read_as_text(client, premium, db_maker, ai):
    to = f"tradetrack.receipts+{premium['forwarding_alias']}@gmail.com"
    body = "Order confirmation from Home Hardware. Hammer $100.00, HST 13% $13.00, total $113.00 paid by Visa."
    assert await run(db_maker, mail(to, body=body, message_id="<body@x>")) == "processed"
    assert (await client.get("/api/receipts")).json()["total"] == 1


async def test_gmail_forwarding_confirmation_is_not_a_receipt(client, premium, db_maker, ai):
    to = f"tradetrack.receipts+{premium['forwarding_alias']}@gmail.com"
    raw = mail(to, sender="Gmail Team <forwarding-noreply@google.com>",
               subject="Gmail Forwarding Confirmation - Receive Mail from p@example.com",
               body="p@example.com has requested to automatically forward mail to your email address. Confirmation code: 123456")
    assert await run(db_maker, raw) == "ignored_forwarding_confirmation"
    assert ai.calls == 0


# ---- the IMAP wrapper, against a fake server ----------------------------- #
class FakeIMAP:
    inbox: dict[bytes, bytes] = {}
    log: list = []
    fail_login = False

    def __init__(self, host, port, timeout=None):
        FakeIMAP.log.append(("connect", host, port))

    def login(self, user, password):
        if FakeIMAP.fail_login:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        FakeIMAP.log.append(("login", user))

    def select(self, box):
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        FakeIMAP.log.append((cmd, *args))
        if cmd == "SEARCH":
            return "OK", [b" ".join(FakeIMAP.inbox)]
        if cmd == "FETCH":
            uid, what = args
            raw = FakeIMAP.inbox[uid]
            if "SIZE" in what:
                return "OK", [b"%s (RFC822.SIZE %d)" % (uid, len(raw))]
            return "OK", [(b"%s (BODY[] {%d}" % (uid, len(raw)), raw), b")"]
        return "OK", [None]

    def expunge(self):
        FakeIMAP.log.append(("expunge",))
        return "OK", [None]

    def logout(self):
        return "BYE", [b""]


@pytest.fixture
def imap(monkeypatch):
    FakeIMAP.inbox, FakeIMAP.log, FakeIMAP.fail_login = {}, [], False
    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", FakeIMAP)
    return FakeIMAP


async def test_poll_creates_receipts_and_closes_out_messages(client, premium, db_maker, imap):
    to = f"tradetrack.receipts+{premium['forwarding_alias']}@gmail.com"
    imap.inbox = {
        b"1": mail(to, attachments=[("a.png", png_bytes(20), "image/png")], message_id="<1@x>"),
        b"2": mail("tradetrack.receipts@gmail.com", message_id="<2@x>"),  # no alias: ignored
    }
    await inbox.check_once(db_maker)
    assert inbox.state.ok is True
    assert (await client.get("/api/receipts")).json()["total"] == 1
    cmds = [e for e in imap.log if e[0] in ("STORE", "COPY", "expunge")]
    assert ("COPY", b"1", '"[Gmail]/Trash"') in cmds and ("COPY", b"2", '"[Gmail]/Trash"') in cmds and ("expunge",) in cmds
    assert (await client.get("/api/config")).json()["services"]["inbound_ok"] is True


async def test_login_failure_is_reported_not_raised(client, db_maker, imap):
    imap.fail_login = True
    await inbox.check_once(db_maker)
    assert inbox.state.ok is False and inbox.state.error == "error"
    assert (await client.get("/api/config")).json()["services"]["inbound_ok"] is False


async def test_a_message_that_keeps_failing_is_dropped_after_three_tries(client, premium, db_maker, imap, monkeypatch):
    to = f"tradetrack.receipts+{premium['forwarding_alias']}@gmail.com"
    imap.inbox = {b"1": mail(to, attachments=[("a.png", png_bytes(21), "image/png")])}

    async def boom(session, raw):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(inbox, "handle_message", boom)
    for _ in range(2):
        await inbox.check_once(db_maker)
    assert not [e for e in imap.log if e[0] == "COPY"]  # still unread: will be retried
    await inbox.check_once(db_maker)
    assert [e for e in imap.log if e[0] == "COPY"]  # third failure: closed out

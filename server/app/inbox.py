"""Receive forwarded receipts WITHOUT a domain: poll a dedicated Gmail inbox over IMAP.

How it works
------------
Every account has a secret alias. In Gmail mode the account's forwarding address is
``<inbox>+<alias>@gmail.com``; Gmail delivers every "+tag" address to the same inbox. A background task
checks that inbox about once a minute, finds the alias in the recipient headers, and hands the message to
``inbound.process_message``: the same code the Mailgun route uses (Premium check, duplicate detection,
attachment validation, AI extraction, the owner's log).

Trust model: the alias is a secret that selects the account. The sender is never used to identify anyone.
Mail to an address without a known alias is ignored without any AI call.

Privacy: forwarded emails pass through this one mailbox. After a message is handled it is moved to the
mailbox's Trash (or at least marked read if that fails); no sender, subject or body is stored by
TradeTrack (only a minimal log row, as with Mailgun).

Honesty: ``state.ok`` records whether the last check worked and is reported by ``/api/config`` so the
dashboard can say so when the mailbox cannot be reached. Nothing here runs unless
ZZPAY_INBOUND_GMAIL_ADDRESS and ZZPAY_INBOUND_GMAIL_APP_PASSWORD are both set. The server must be awake to
poll (see docs/email-forwarding.md).
"""

import asyncio
import imaplib
import logging
import re
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr

from sqlmodel import select

from app import database
from app.config import settings
from app.models import User
from app.routers import inbound

logger = logging.getLogger("tradetrack.inbox")

MAX_MESSAGES_PER_POLL = 20
MAX_MESSAGE_BYTES = 25 * 1024 * 1024  # Gmail's own limit for incoming mail
MAX_ATTEMPTS = 3
SMALL_INLINE_BYTES = 30 * 1024  # logos and tracking pixels in HTML mail are not receipts
RECIPIENT_HEADERS = ("Delivered-To", "X-Original-To", "Envelope-To", "To", "Cc")
IMAGE_OR_PDF = ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic")


@dataclass
class InboxState:
    ok: bool | None = None  # None until the first check
    error: str | None = None


state = InboxState()
_attempts: dict[bytes, int] = {}


# --------------------------------------------------------------------------- #
# Reading one message
# --------------------------------------------------------------------------- #
def _base(local: str) -> str:
    """Gmail ignores dots and anything after "+" in the local part."""
    return local.split("+")[0].replace(".", "").lower()


def recipient_alias(msg: EmailMessage) -> str | None:
    """The alias from ``inbox+alias@gmail.com`` in any recipient header, or None."""
    want_local, want_domain = settings.inbound_gmail_address.strip().lower().rsplit("@", 1)
    for header in RECIPIENT_HEADERS:
        for _, addr in getaddresses([str(v) for v in msg.get_all(header, [])]):
            local, _, domain = addr.lower().rpartition("@")
            if domain in (want_domain, "googlemail.com") and "+" in local and _base(local) == _base(want_local):
                alias = local.split("+", 1)[1]
                if re.fullmatch(r"[a-z0-9]{6,64}", alias):
                    return alias
    return None


def is_gmail_forwarding_confirmation(msg: EmailMessage) -> bool:
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    return sender.endswith("@google.com") and "forwarding confirmation" in str(msg.get("Subject", "")).lower()


def extract_content(msg: EmailMessage) -> tuple[list[tuple[str | None, bytes]], str]:
    """(attachments worth reading, plain-text body). Inline logos and non-receipt file types are skipped."""
    attachments: list[tuple[str | None, bytes]] = []
    body_plain = body_html = ""
    for part in msg.walk():
        if part.is_multipart() or part.get_content_maintype() == "message":
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        disposition = (part.get_content_disposition() or "").lower()
        if ctype in ("text/plain", "text/html") and disposition != "attachment" and not filename:
            text = part.get_content()
            if ctype == "text/plain":
                body_plain += text + "\n"
            else:
                body_html += text + "\n"
            continue
        if ctype not in IMAGE_OR_PDF and not (filename or "").lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic")):
            continue
        data = part.get_payload(decode=True) or b""
        if ctype.startswith("image/") and part.get("Content-ID") and disposition != "attachment" and len(data) < SMALL_INLINE_BYTES:
            continue  # an inline logo, not a receipt
        if data:
            attachments.append((filename, data))
    body = body_plain.strip() or inbound.html_to_text(body_html).strip()
    return attachments, body


async def handle_message(session, raw: bytes) -> str:
    """Process one raw message. Returns a short outcome word for the logs: never raises Rejected."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    alias = recipient_alias(msg)
    if alias is None:
        return "ignored_no_alias"
    user = (await session.execute(select(User).where(User.forwarding_alias == alias))).scalar_one_or_none()
    if user is None:
        return "ignored_unknown_alias"
    if is_gmail_forwarding_confirmation(msg):
        return "ignored_forwarding_confirmation"  # Gmail's "confirm forwarding" mail is not a receipt
    from app.ratelimit import limiter

    if limiter.check_and_hit(f"inbound:{user.id}", 60, 60):
        return "rate_limited"
    attachments, body = extract_content(msg)

    def reader(data: bytes):
        async def read() -> bytes:
            return data

        return read

    try:
        result = await inbound.process_message(
            session,
            user,
            message_id=str(msg.get("Message-ID", "")).strip(),
            attachments=[(name, reader(data)) for name, data in attachments],
            body=body,
        )
    except inbound.Rejected as exc:
        return f"rejected_{exc.reason}"
    return str(result.get("status", "done"))


# --------------------------------------------------------------------------- #
# IMAP (blocking, run in a thread)
# --------------------------------------------------------------------------- #
def _connect() -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(settings.inbound_imap_host, 993, timeout=30)
    conn.login(settings.inbound_gmail_address.strip(), settings.inbound_gmail_app_password.strip())
    conn.select("INBOX")
    return conn


def _fetch_batch() -> list[tuple[bytes, bytes]]:
    """Unread messages as (uid, raw bytes). Leaves them unread: they are only closed out after handling."""
    conn = _connect()
    try:
        typ, data = conn.uid("SEARCH", None, "UNSEEN")
        uids = (data[0] or b"").split()[:MAX_MESSAGES_PER_POLL] if typ == "OK" else []
        out: list[tuple[bytes, bytes]] = []
        for uid in uids:
            typ, parts = conn.uid("FETCH", uid, "(RFC822.SIZE)")
            size = re.search(rb"RFC822\.SIZE (\d+)", b" ".join(p if isinstance(p, bytes) else p[0] for p in parts or []))
            if size and int(size.group(1)) > MAX_MESSAGE_BYTES:
                out.append((uid, b""))  # too big: closed out below without reading it
                continue
            typ, parts = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ == "OK" and parts and isinstance(parts[0], tuple):
                out.append((uid, parts[0][1]))
        return out
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _finish(uids: list[bytes]) -> None:
    """Mark handled messages read and move them to Trash so receipts do not pile up in the mailbox."""
    if not uids:
        return
    conn = _connect()
    try:
        for uid in uids:
            conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
            try:
                typ, _ = conn.uid("COPY", uid, '"[Gmail]/Trash"')
                if typ == "OK":
                    conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            except imaplib.IMAP4.error:
                pass  # Trash folder has another name: leave it read
        conn.expunge()
    finally:
        try:
            conn.logout()
        except Exception:
            pass


async def poll_once(session_factory=None) -> int:
    """One check of the mailbox. Returns how many messages were closed out."""
    factory = session_factory or database.async_session
    batch = await asyncio.to_thread(_fetch_batch)
    done: list[bytes] = []
    for uid, raw in batch:
        if not raw:
            done.append(uid)
            continue
        try:
            async with factory() as session:
                outcome = await handle_message(session, raw)
                await session.commit()
            logger.info("inbound mail handled: %s", outcome)
            _attempts.pop(uid, None)
            done.append(uid)
        except Exception as exc:
            _attempts[uid] = _attempts.get(uid, 0) + 1
            logger.error("inbound mail failed (%s), attempt %s", type(exc).__name__, _attempts[uid])
            if _attempts[uid] >= MAX_ATTEMPTS:
                _attempts.pop(uid, None)
                done.append(uid)  # give up on a message that keeps failing
    await asyncio.to_thread(_finish, done)
    return len(done)


async def check_once(session_factory=None) -> None:
    """``poll_once`` plus bookkeeping: never raises, records whether the check worked."""
    try:
        await poll_once(session_factory)
        state.ok, state.error = True, None
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # login refused, network down, ...
        state.ok, state.error = False, type(exc).__name__
        logger.error("inbox check failed (%s)", type(exc).__name__)  # never log the password or server text


async def run_forever() -> None:
    while True:
        await check_once()
        await asyncio.sleep(max(15, settings.inbound_poll_seconds))

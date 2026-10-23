"""Inbound email (Mailgun "forward to URL" route). Provider -> server only; no login.

Trust model - the request is accepted only if ALL hold:
1. ZZPAY_MAILGUN_SIGNING_KEY and ZZPAY_INBOUND_DOMAIN are configured (else 503);
2. the HMAC-SHA256 signature over ``timestamp + token`` is valid (constant-time compare) - else 403;
3. the timestamp is fresh (default +-5 minutes) - else 403;
4. the token was not used before (replay) - else 403;
5. the RECIPIENT (an unguessable alias at our inbound domain) belongs to an account - else 406.
   The sender address / display name is never used to identify or authorise anyone;
6. the account is on the Premium plan - else the delivery is rejected (and logged for the owner).

What is stored: the receipts created and a minimal ``tt_inbound_events`` row (time, status, short
reason, attachment count, receipt ids). No sender, subject or body is stored; when a receipt is built
from the email body, that text is sent to the extractor and then discarded.

406 tells Mailgun not to retry (permanent rejection); a 200 means we dealt with it.
"""

import hashlib
import hmac
import logging
import re
import time
from datetime import timedelta
from html.parser import HTMLParser
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from starlette.datastructures import UploadFile

from app import pipeline
from app.config import settings
from app.database import get_session
from app.extraction import InvalidFile
from app.models import InboundEvent, InboundStatus, InboundToken, ReceiptSource, User, utcnow
from app.ratelimit import limiter

logger = logging.getLogger("tradetrack.inbound")
router = APIRouter(prefix="/api/inbound", tags=["inbound"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]

MAX_ATTACHMENTS = 5
MAX_BODY_BYTES = 40 * 1024 * 1024
MIN_BODY_TEXT_CHARS = 30
TOKEN_TTL = timedelta(hours=1)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:  # malformed HTML: fall back to a crude strip
        return re.sub(r"<[^>]+>", " ", html)
    return "".join(p.parts)


def signature_ok(timestamp: str, token: str, signature: str) -> bool:
    expected = hmac.new(settings.mailgun_signing_key.encode(), (timestamp + token).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _reject(code: int, error: str) -> HTTPException:
    return HTTPException(code, {"code": error, "message": error.replace("_", " ")})


async def _reject_keep(session: AsyncSession, code: int, error: str) -> HTTPException:
    """Persist what we recorded (used token, log row) before answering with an error status."""
    await session.commit()
    return _reject(code, error)


def _recipient_alias(recipient: str) -> str | None:
    """Local part of the recipient if it is at our inbound domain, else None."""
    match = re.search(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+)", recipient or "")
    if not match:
        return None
    local, domain = match.group(1).lower(), match.group(2).lower().rstrip(".")
    return local if domain == settings.inbound_domain.strip().lower() else None


@router.post("/mailgun")
async def mailgun_inbound(request: Request, session: SessionDep) -> dict:
    if not settings.inbound_email_configured:
        raise _reject(503, "inbound_email_not_configured")
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise _reject(413, "message_too_large")
    try:
        form = await request.form(max_files=20, max_fields=200, max_part_size=2 * 1024 * 1024)
    except Exception:
        raise _reject(400, "unreadable_request") from None

    # --- authenticate the provider -------------------------------------- #
    timestamp, token, signature = (str(form.get(k) or "") for k in ("timestamp", "token", "signature"))
    if not (timestamp and token and signature and signature_ok(timestamp, token, signature)):
        raise _reject(403, "invalid_signature")
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        raise _reject(403, "invalid_signature") from None
    if age > settings.inbound_max_age_seconds:
        raise _reject(403, "stale_timestamp")

    now = utcnow()
    await session.execute(delete(InboundToken).where(InboundToken.seen_at < now - TOKEN_TTL))
    try:
        async with session.begin_nested():
            session.add(InboundToken(token_hash=_sha(token), seen_at=now))
            await session.flush()
    except IntegrityError:
        raise _reject(403, "replayed_token") from None

    # --- who is it for? (recipient alias only) ---------------------------- #
    alias = _recipient_alias(str(form.get("recipient") or ""))
    user = None
    if alias:
        user = (await session.execute(select(User).where(User.forwarding_alias == alias))).scalar_one_or_none()
    if user is None:
        raise await _reject_keep(session, 406, "unknown_recipient")
    if limiter.check_and_hit(f"inbound:{user.id}", 60, 60):
        raise await _reject_keep(session, 429, "rate_limited")

    uploads = [v for _, v in form.multi_items() if isinstance(v, UploadFile)]
    message_id = str(form.get("Message-Id") or form.get("message-id") or "").strip()
    message_hash = _sha(message_id.lower()) if message_id else None

    def log(status: InboundStatus, reason: str | None, attachments: int, ids: list[str]) -> InboundEvent:
        ev = InboundEvent(user_id=user.id, status=status.value, reason=reason, attachments=attachments,
                          receipt_ids=ids, message_hash=message_hash)
        session.add(ev)
        return ev

    if user.plan != "PREMIUM":
        log(InboundStatus.REJECTED, "premium_required", len(uploads), [])
        raise await _reject_keep(session, 406, "premium_required")

    if message_hash:
        seen = (await session.execute(
            select(InboundEvent).where(
                InboundEvent.user_id == user.id, InboundEvent.message_hash == message_hash,
                InboundEvent.status.in_([InboundStatus.PROCESSED.value, InboundStatus.FAILED.value]),
            )
        )).first()
        if seen:
            log(InboundStatus.DUPLICATE, "message_already_processed", len(uploads), [])
            return {"status": "duplicate"}

    # --- run the same pipeline as uploads ----------------------------------- #
    ids: list[str] = []
    counts = {"ok": 0, "duplicate": 0, "failed": 0, "not_configured": 0, "invalid": 0}
    reasons: list[str] = []

    if uploads:
        for up in uploads[:MAX_ATTACHMENTS]:
            data = await up.read(settings.max_upload_bytes + 1)
            try:
                res = await pipeline.ingest_file(session, user, data, up.filename, ReceiptSource.EMAIL)
            except InvalidFile as exc:
                counts["invalid"] += 1
                reasons.append("attachment_too_large" if exc.status_code == 413 else "unsupported_attachment")
                continue
            counts[res.outcome] += 1
            ids.append(res.receipt.id)
        if len(uploads) > MAX_ATTACHMENTS:
            reasons.append("too_many_attachments")
    else:
        body = str(form.get("body-plain") or "").strip()
        if not body and form.get("body-html"):
            body = html_to_text(str(form.get("body-html"))).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        if len(body) < MIN_BODY_TEXT_CHARS:
            log(InboundStatus.REJECTED, "no_receipt_content", 0, [])
            return {"status": "rejected", "reason": "no_receipt_content"}
        res = await pipeline.ingest_text(session, user, body, ReceiptSource.EMAIL)
        counts[res.outcome] += 1
        ids.append(res.receipt.id)

    if counts["failed"] or counts["not_configured"]:
        reasons.append("ai_not_configured" if counts["not_configured"] else "extraction_failed")
    if counts["ok"]:
        status_ = InboundStatus.PROCESSED
    elif counts["failed"] or counts["not_configured"]:
        status_ = InboundStatus.FAILED
    elif counts["duplicate"]:
        status_ = InboundStatus.DUPLICATE
        reasons.append("file_already_received")
    else:
        status_ = InboundStatus.REJECTED
    log(status_, ", ".join(dict.fromkeys(reasons)) or None, len(uploads), ids)
    return {"status": status_.value.lower(), "receipts": len(ids)}

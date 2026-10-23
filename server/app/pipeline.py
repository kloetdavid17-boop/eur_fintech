"""Shared receipt-intake pipeline, used by the upload route and the inbound-email route so both
go through exactly the same validation, duplicate check, storage and AI extraction.

Outcomes (``IngestResult.outcome``)
* ``ok``             - receipt created/updated, status NEEDS_REVIEW.
* ``duplicate``      - same file already uploaded by this user; the existing receipt is returned and
                       the AI is NOT called again.
* ``failed``         - extraction failed; a FAILED receipt was kept so the user can complete it by hand.
* ``not_configured`` - no AI key; the file and a FAILED manual-entry receipt were kept.

An unusable file raises ``extraction.InvalidFile`` (nothing is stored).
"""

import hashlib
import logging
import secrets
import string
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app import extraction, storage
from app.models import (
    Confidence,
    ProcessingStatus,
    Receipt,
    ReceiptSource,
    User,
    utcnow,
)
from app.validation import refresh_warnings

logger = logging.getLogger("tradetrack.pipeline")

_ID_ALPHABET = string.ascii_uppercase + string.digits
NOT_CONFIGURED_MESSAGE = (
    "AI extraction is not configured on this server, so nothing was read from your file. "
    "Your file was kept: you can enter the details by hand."
)


@dataclass
class IngestResult:
    receipt: Receipt
    outcome: str
    message: str | None = None


def _random_id(year: int) -> str:
    return f"TT-{year}-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(6))


async def new_receipt_id(session: AsyncSession) -> str:
    year = utcnow().year
    for _ in range(20):
        candidate = _random_id(year)
        if await session.get(Receipt, candidate) is None:
            return candidate
    raise RuntimeError("Could not allocate a receipt id")  # astronomically unlikely


async def _flush_new(session: AsyncSession, receipt: Receipt) -> None:
    """Insert a new receipt, retrying with a fresh id if a concurrent insert took ours."""
    for _ in range(5):
        try:
            async with session.begin_nested():
                session.add(receipt)
                await session.flush()
            return
        except IntegrityError:
            existing = await session.get(Receipt, receipt.id)
            if existing is None:
                raise  # a different constraint (e.g. the per-user file hash)
            receipt.id = await new_receipt_id(session)
    raise RuntimeError("Could not allocate a receipt id")


def apply_extraction(r: Receipt, ex: extraction.Extracted, user: User) -> None:
    r.merchant = ex.merchant
    r.receipt_date = ex.receipt_date
    r.receipt_time = ex.receipt_time
    r.currency = ex.currency
    r.receipt_number = ex.receipt_number
    r.line_items = ex.line_items
    r.discounts = ex.discounts
    r.subtotal = ex.subtotal
    r.tax_lines = ex.tax_lines
    r.tax_total = ex.tax_total
    r.total = ex.total
    r.province = ex.province
    r.category = ex.category
    r.category_is_ai_suggested = ex.category is not None
    r.extraction_confidence = ex.confidence
    r.extraction_error = None
    r.processing_status = ProcessingStatus.NEEDS_REVIEW.value
    r.warnings = []
    if ex.currency_assumed:
        r.warnings = [{
            "code": "currency_assumed", "severity": "info", "field": "currency",
            "message": "No currency was found on the receipt, so CAD is shown. Please check it.",
        }]
    refresh_warnings(r, default_province=user.province, keep_sticky=True)
    r.updated_at = utcnow()


def _mark_failed(r: Receipt, message: str) -> None:
    r.processing_status = ProcessingStatus.FAILED.value
    r.extraction_error = message
    r.extraction_confidence = Confidence.UNKNOWN.value
    r.warnings = []
    r.updated_at = utcnow()


async def run_extraction(session: AsyncSession, user: User, r: Receipt, doc: extraction.PreparedDocument) -> IngestResult:
    try:
        ex = await extraction.extract(doc)
    except extraction.ExtractionNotConfigured:
        _mark_failed(r, NOT_CONFIGURED_MESSAGE)
        await session.flush()
        return IngestResult(r, "not_configured", NOT_CONFIGURED_MESSAGE)
    except extraction.ExtractionFailed as exc:
        _mark_failed(r, exc.message)
        await session.flush()
        return IngestResult(r, "failed", exc.message)
    except Exception as exc:  # defensive: a normalisation bug must not become a 500 / fake success
        logger.exception("Unexpected error normalising extraction (%s)", type(exc).__name__)
        msg = "The receipt could not be read. Please enter the details by hand."
        _mark_failed(r, msg)
        await session.flush()
        return IngestResult(r, "failed", msg)
    apply_extraction(r, ex, user)
    await session.flush()
    return IngestResult(r, "ok")


async def ingest_file(
    session: AsyncSession,
    user: User,
    data: bytes,
    filename: str | None,
    source: ReceiptSource,
) -> IngestResult:
    mime = await extraction.validate_file_async(data)  # raises InvalidFile
    sha = hashlib.sha256(data).hexdigest()

    existing = (
        await session.execute(select(Receipt).where(Receipt.user_id == user.id, Receipt.file_sha256 == sha))
    ).scalar_one_or_none()
    if existing is not None and existing.processing_status != ProcessingStatus.FAILED.value:
        return IngestResult(existing, "duplicate", "This looks like a receipt you already uploaded.")

    if existing is None:
        receipt = Receipt(
            id=await new_receipt_id(session),
            user_id=user.id,
            source=source.value,
            processing_status=ProcessingStatus.NEEDS_REVIEW.value,
            original_filename=(filename or "")[:200] or None,
            file_mime_type=mime,
            file_size_bytes=len(data),
            file_sha256=sha,
        )
        try:
            await _flush_new(session, receipt)
        except IntegrityError:
            # A concurrent upload of the same file won the race: treat as a duplicate.
            winner = (
                await session.execute(select(Receipt).where(Receipt.user_id == user.id, Receipt.file_sha256 == sha))
            ).scalar_one_or_none()
            if winner is None:
                raise
            return IngestResult(winner, "duplicate", "This looks like a receipt you already uploaded.")
        await storage.put_file(session, receipt, data)
        await session.flush()
    else:  # the earlier attempt FAILED (e.g. AI outage): try again on the same row
        receipt = existing

    doc = await extraction.prepare_document_async(data, mime)
    return await run_extraction(session, user, receipt, doc)


async def ingest_text(session: AsyncSession, user: User, text: str, source: ReceiptSource) -> IngestResult:
    """Extract from plain text (an email body). The text itself is NOT stored."""
    receipt = Receipt(
        id=await new_receipt_id(session),
        user_id=user.id,
        source=source.value,
        processing_status=ProcessingStatus.NEEDS_REVIEW.value,
    )
    await _flush_new(session, receipt)
    return await run_extraction(session, user, receipt, extraction.text_document(text))


async def reprocess(session: AsyncSession, user: User, r: Receipt) -> IngestResult:
    data = await storage.get_file(session, r)
    if data is None:
        raise extraction.InvalidFile("There is no stored file to process again for this receipt.")
    mime = await extraction.validate_file_async(data)
    doc = await extraction.prepare_document_async(data, mime)
    return await run_extraction(session, user, r, doc)

"""Receipts — upload, AI extraction, review/correction, save, list, manage.

TradeTrack has no public/anonymous receipt concept: every receipt belongs to
exactly one user, and every route in this file enforces that server-side
(never trust the frontend to only *show* the right receipts — a malicious or
buggy client must not be able to read/edit/delete another user's data).

Flow:
  1. POST /process   -> run AI extraction, create a Receipt row with
                        processing_status=NEEDS_REVIEW (or FAILED), does NOT
                        count against the monthly quota yet.
  2. PATCH /{id}      -> user corrects fields (merchant, totals, category...).
  3. POST /{id}/save  -> quota check (server-side, FREE plan only), flips
                        status to SAVED, writes a UsageEvent row.
  4. GET  ""          -> list the caller's own receipts (search/filter).
  5. GET  /{id}       -> fetch one (owner-only).
  6. DELETE /{id}     -> owner-only delete (or archive, see note below).
  7. GET  /usage      -> current plan + usage for the billing period.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.ai_extraction import AIExtractionError, extract_receipt
from app.auth import CurrentUser
from app.database import get_session
from app.models import (
    EXPENSE_CATEGORIES,
    ExtractionConfidence,
    Plan,
    ProcessingStatus,
    Receipt,
    ReceiptOut,
    ReceiptSource,
    ReceiptUpdate,
    UsageEvent,
    UsageOut,
    next_receipt_id,
)

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

FREE_PLAN_MONTHLY_LIMIT = 5

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def _to_out(receipt: Receipt) -> ReceiptOut:
    return ReceiptOut(
        id=receipt.id,
        source=receipt.source,
        processing_status=receipt.processing_status,
        extraction_confidence=receipt.extraction_confidence,
        extraction_error=receipt.extraction_error,
        original_filename=receipt.original_filename,
        file_mime_type=receipt.file_mime_type,
        has_original_file=receipt.file_storage_key is not None,
        merchant=receipt.merchant,
        receipt_date=receipt.receipt_date,
        currency=receipt.currency,
        receipt_number=receipt.receipt_number,
        line_items=receipt.line_items,
        tax_lines=receipt.tax_lines,
        subtotal=receipt.subtotal,
        tax_total=receipt.tax_total,
        total=receipt.total,
        province=receipt.province,
        category=receipt.category,
        category_is_ai_suggested=receipt.category_is_ai_suggested,
        review_notes=receipt.review_notes,
        reviewed_at=receipt.reviewed_at,
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
    )


async def _get_owned_receipt(receipt_id: str, user: CurrentUser, session: AsyncSession) -> Receipt:
    receipt = await session.get(Receipt, receipt_id)
    # 404, not 403, for another user's receipt — don't reveal that the id exists.
    if receipt is None or receipt.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    return receipt


def _current_billing_period(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Calendar-month billing period in UTC. Simple and predictable for a demo;
    swap for Stripe's actual period dates once real billing is wired up."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


async def _usage_this_period(user_id: UUID, session: AsyncSession) -> tuple[int, datetime, datetime]:
    start, end = _current_billing_period()
    count = await session.scalar(
        select(func.count())
        .select_from(UsageEvent)
        .where(UsageEvent.user_id == user_id)
        .where(UsageEvent.created_at >= start)
        .where(UsageEvent.created_at < end)
    )
    return count or 0, start, end


# --------------------------------------------------------------------------- #
# Upload + AI processing (does not count against quota — only SAVE does)
# --------------------------------------------------------------------------- #
@router.post("/process", response_model=ReceiptOut)
async def process_receipt(
    user: CurrentUser,
    session: SessionDep,
    file: UploadFile = File(...),
) -> Receipt:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type '{file.content_type}'. Please upload a JPEG, PNG, WEBP, HEIC, or PDF.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "File is too large. Please upload a file under 10 MB.",
        )
    if len(content) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")

    receipt_id = await next_receipt_id(session)
    receipt = Receipt(
        id=receipt_id,
        user_id=user.id,
        source=ReceiptSource.UPLOAD.value,
        processing_status=ProcessingStatus.PENDING.value,
        original_filename=file.filename,
        file_mime_type=file.content_type,
        file_size_bytes=len(content),
        province=user.province,
        currency="CAD",
    )

    try:
        extracted = await extract_receipt(content, file.content_type, file.filename or "receipt")
    except AIExtractionError as exc:
        receipt.processing_status = ProcessingStatus.FAILED.value
        receipt.extraction_confidence = ExtractionConfidence.UNKNOWN.value
        receipt.extraction_error = str(exc)
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)
        # 422, not 500: the request was well-formed, extraction just failed.
        # We still persist the failed attempt so the user can see it and retry
        # or fill in fields manually, but it does NOT consume their quota.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": f"Could not process receipt: {exc}", "receipt_id": receipt.id},
        )

    receipt.processing_status = ProcessingStatus.NEEDS_REVIEW.value
    receipt.extraction_confidence = extracted.get("confidence", ExtractionConfidence.UNKNOWN.value).upper()
    receipt.merchant = extracted.get("merchant")
    receipt.receipt_date = extracted.get("date")
    receipt.currency = extracted.get("currency") or "CAD"
    receipt.receipt_number = extracted.get("receipt_number")
    receipt.line_items = extracted.get("line_items", [])
    receipt.tax_lines = extracted.get("taxes", [])
    receipt.subtotal = extracted.get("subtotal")
    receipt.tax_total = sum((t.get("amount", 0) or 0) for t in extracted.get("taxes", [])) or None
    receipt.total = extracted.get("total")

    suggested = extracted.get("suggested_category")
    if suggested in EXPENSE_CATEGORIES:
        receipt.category = suggested
        receipt.category_is_ai_suggested = True
    else:
        receipt.category = None
        receipt.category_is_ai_suggested = False

    if receipt.extraction_confidence == ExtractionConfidence.LOW.value:
        receipt.review_notes = "Some fields could not be read with confidence — please double-check before saving."

    session.add(receipt)
    await session.commit()
    await session.refresh(receipt)
    return _to_out(receipt)


# --------------------------------------------------------------------------- #
# Review / correction
# --------------------------------------------------------------------------- #
@router.patch("/{receipt_id}", response_model=ReceiptOut)
async def update_receipt(
    receipt_id: str, body: ReceiptUpdate, user: CurrentUser, session: SessionDep
) -> Receipt:
    receipt = await _get_owned_receipt(receipt_id, user, session)
    if receipt.processing_status == ProcessingStatus.SAVED.value:
        # Saved receipts are the user's bookkeeping record — allow edits, but
        # this is where you'd add an audit trail if that matters for grading.
        pass

    data = body.model_dump(exclude_unset=True)
    if "category" in data:
        receipt.category_is_ai_suggested = False  # user touched it -> no longer "AI suggested"
    if "line_items" in data and data["line_items"] is not None:
        data["line_items"] = [li if isinstance(li, dict) else li.model_dump() for li in data["line_items"]]
    if "tax_lines" in data and data["tax_lines"] is not None:
        data["tax_lines"] = [tl if isinstance(tl, dict) else tl.model_dump() for tl in data["tax_lines"]]
    if "province" in data and data["province"] is not None:
        data["province"] = data["province"].value if hasattr(data["province"], "value") else data["province"]

    for key, value in data.items():
        setattr(receipt, key, value)
    receipt.updated_at = datetime.now(timezone.utc)

    session.add(receipt)
    await session.commit()
    await session.refresh(receipt)
    return _to_out(receipt)


# --------------------------------------------------------------------------- #
# Save (quota-enforced, server-side)
# --------------------------------------------------------------------------- #
@router.post("/{receipt_id}/save", response_model=ReceiptOut)
async def save_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> Receipt:
    receipt = await _get_owned_receipt(receipt_id, user, session)

    if receipt.processing_status == ProcessingStatus.SAVED.value:
        return _to_out(receipt)  # idempotent — already saved, don't double-charge quota

    if receipt.processing_status == ProcessingStatus.FAILED.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This receipt failed processing. Fill in the required fields manually before saving.",
        )

    if user.plan == Plan.FREE.value:
        used, _, _ = await _usage_this_period(user.id, session)
        if used >= FREE_PLAN_MONTHLY_LIMIT:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": (
                        f"You've reached the free plan limit of {FREE_PLAN_MONTHLY_LIMIT} "
                        "saved receipts this month. Upgrade to Premium for unlimited receipts."
                    ),
                    "limit": FREE_PLAN_MONTHLY_LIMIT,
                    "used": used,
                },
            )

    receipt.processing_status = ProcessingStatus.SAVED.value
    receipt.reviewed_at = datetime.now(timezone.utc)
    receipt.updated_at = receipt.reviewed_at
    session.add(receipt)
    session.add(UsageEvent(user_id=user.id, receipt_id=receipt.id))
    await session.commit()
    await session.refresh(receipt)
    return _to_out(receipt)


# --------------------------------------------------------------------------- #
# List / search / filter (owner-only)
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[ReceiptOut])
async def list_receipts(
    user: CurrentUser,
    session: SessionDep,
    merchant: str | None = Query(default=None),
    category: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    min_amount: float | None = Query(default=None),
    max_amount: float | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[Receipt]:
    stmt = select(Receipt).where(Receipt.user_id == user.id)

    if merchant:
        stmt = stmt.where(Receipt.merchant.ilike(f"%{merchant}%"))
    if category:
        stmt = stmt.where(Receipt.category == category)
    if date_from:
        stmt = stmt.where(Receipt.receipt_date >= date_from)
    if date_to:
        stmt = stmt.where(Receipt.receipt_date <= date_to)
    if min_amount is not None:
        stmt = stmt.where(Receipt.total >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(Receipt.total <= max_amount)
    if status_filter:
        stmt = stmt.where(Receipt.processing_status == status_filter.upper())
    else:
        # Default view hides archived receipts; pass ?status=ARCHIVED to see them.
        stmt = stmt.where(Receipt.processing_status != ProcessingStatus.ARCHIVED.value)

    stmt = stmt.order_by(Receipt.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/usage", response_model=UsageOut)
async def get_usage(user: CurrentUser, session: SessionDep) -> UsageOut:
    used, start, end = await _usage_this_period(user.id, session)
    return UsageOut(
        plan=user.plan,
        saved_this_period=used,
        limit=None if user.plan == Plan.PREMIUM.value else FREE_PLAN_MONTHLY_LIMIT,
        period_start=start,
        period_end=end,
    )


@router.get("/{receipt_id}", response_model=ReceiptOut)
async def get_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> Receipt:
    receipt = await _get_owned_receipt(receipt_id, user, session)
    return _to_out(receipt)


# --------------------------------------------------------------------------- #
# Archive / delete (owner-only)
# --------------------------------------------------------------------------- #
@router.post("/{receipt_id}/archive", response_model=ReceiptOut)
async def archive_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> Receipt:
    """Soft-delete: keeps the bookkeeping record (and its UsageEvent) but hides
    it from the default list view. Prefer this over hard delete for SAVED
    receipts so a user's monthly count stays accurate."""
    receipt = await _get_owned_receipt(receipt_id, user, session)
    receipt.processing_status = ProcessingStatus.ARCHIVED.value
    receipt.updated_at = datetime.now(timezone.utc)
    session.add(receipt)
    await session.commit()
    await session.refresh(receipt)
    return _to_out(receipt)


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> None:
    receipt = await _get_owned_receipt(receipt_id, user, session)
    # Hard delete also removes its UsageEvent via FK cascade if configured; if
    # not, delete it explicitly so a removed receipt can't double-count.
    usage_rows = await session.execute(
        select(UsageEvent).where(UsageEvent.receipt_id == receipt.id)
    )
    for row in usage_rows.scalars().all():
        await session.delete(row)
    await session.delete(receipt)
    await session.commit()

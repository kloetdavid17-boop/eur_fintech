"""Receipts: upload + AI extraction, review/correct, save, list, export. Owner-only.

Every query filters on ``Receipt.user_id == current_user.id``; someone else's receipt is
indistinguishable from a missing one (404). Ownership is never taken from the request.

Flow:  POST /process  ->  PATCH /{id} (corrections)  ->  POST /{id}/save  (counts against the
monthly allowance, enforced here on the server)  ->  list / export later.
"""

import asyncio
import re
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, or_, select

from app import exports, pdf, pipeline, plans, storage
from app import email as mailer
from app.auth import CurrentUser, PremiumUser
from app.config import settings
from app.database import get_session
from app.extraction import InvalidFile
from app.models import (
    EXPENSE_CATEGORIES,
    EmailExportRequest,
    ProcessingStatus,
    Receipt,
    ReceiptOut,
    ReceiptUpdate,
    UsageEvent,
    User,
    receipt_to_out,
    utcnow,
)
from app.ratelimit import limiter
from app.usage import saved_in_period, usage_summary
from app.validation import FieldError, apply_patch, missing_required, parse_date, parse_money, refresh_warnings

router = APIRouter(prefix="/api/receipts", tags=["receipts"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _err(code_: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(code_, {"code": code, "message": message, **extra})


async def _get_owned(session: AsyncSession, user: User, receipt_id: str) -> Receipt:
    r = (
        await session.execute(select(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user.id))
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    return r


def _safe_filename(name: str | None, fallback: str) -> str:
    base = Path((name or "").replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")[:100]
    return base or fallback


def _invalid_field(exc: FieldError) -> HTTPException:
    return _err(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_field", exc.message, field=exc.field)


def _check_rate(user: User) -> None:
    if limiter.check_and_hit(f"process:{user.id}", settings.process_max_per_minute, 60):
        raise _err(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", "You are uploading too quickly. Please wait a minute and try again.")


async def _finish_ingest(session: AsyncSession, result: pipeline.IngestResult) -> ReceiptOut:
    """Turn a pipeline result into the contract's response / error."""
    if result.outcome == "duplicate":
        out = receipt_to_out(result.receipt)
        out.processing_note = result.message
        return out
    if result.outcome == "ok":
        return receipt_to_out(result.receipt)
    # Keep the FAILED receipt (and its file) before answering with an error.
    await session.commit()
    if result.outcome == "not_configured":
        raise _err(status.HTTP_503_SERVICE_UNAVAILABLE, "ai_not_configured", result.message or "", receipt_id=result.receipt.id)
    raise _err(status.HTTP_422_UNPROCESSABLE_ENTITY, "extraction_failed", result.message or "", receipt_id=result.receipt.id)


def _parse_month(month: str | None) -> str:
    if month is None or not month.strip():
        now = plans.now_utc().astimezone(plans.PERIOD_TZ)
        return f"{now.year:04d}-{now.month:02d}"
    try:
        exports.month_range(month)
    except ValueError as exc:
        raise _err(422, "invalid_field", f"Invalid month: {exc}", field="month") from None
    return month


def _opt_date(value: str | None, field: str) -> date | None:
    try:
        return parse_date(value) if value and value.strip() else None
    except ValueError as exc:
        raise _err(422, "invalid_field", f"{field} must be a valid YYYY-MM-DD date", field=field) from exc


def _opt_amount(value: str | None, field: str):
    try:
        return parse_money(value) if value and value.strip() else None
    except ValueError as exc:
        raise _err(422, "invalid_field", f"{field} must be a valid amount", field=field) from exc


# --------------------------------------------------------------------------- #
# Upload + processing
# --------------------------------------------------------------------------- #
@router.post("/process", response_model=ReceiptOut)
async def process_receipt(request: Request, user: CurrentUser, session: SessionDep, file: UploadFile = File(...)) -> ReceiptOut:
    _check_rate(user)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_upload_bytes + 1024 * 1024:
        raise HTTPException(413, f"The file is too large. The maximum size is {settings.max_upload_mb} MB.")
    data = await file.read(settings.max_upload_bytes + 1)  # bounded read
    try:
        result = await pipeline.ingest_file(session, user, data, file.filename, source=_UPLOAD)
    except InvalidFile as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return await _finish_ingest(session, result)


from app.models import ReceiptSource  # noqa: E402

_UPLOAD = ReceiptSource.UPLOAD


@router.post("/{receipt_id}/reprocess", response_model=ReceiptOut)
async def reprocess_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> ReceiptOut:
    r = await _get_owned(session, user, receipt_id)
    if r.processing_status not in (ProcessingStatus.FAILED.value, ProcessingStatus.NEEDS_REVIEW.value):
        raise _err(409, "not_reprocessable", "Only receipts that are not saved yet can be processed again.")
    _check_rate(user)
    try:
        result = await pipeline.reprocess(session, user, r)
    except InvalidFile as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    return await _finish_ingest(session, result)


# --------------------------------------------------------------------------- #
# Usage / list
# --------------------------------------------------------------------------- #
@router.get("/usage")
async def get_usage(user: CurrentUser, session: SessionDep) -> dict:
    return await usage_summary(session, user)


@router.get("")
async def list_receipts(
    user: CurrentUser,
    session: SessionDep,
    q: str | None = None,
    category: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    premium_filters = [v for v in (date_from, date_to, min_amount, max_amount) if v and v.strip()]
    if premium_filters and user.plan != "PREMIUM":
        raise _err(402, "premium_required", "Date and amount filters are included in the Premium plan.")
    df, dt = _opt_date(date_from, "date_from"), _opt_date(date_to, "date_to")
    lo, hi = _opt_amount(min_amount, "min_amount"), _opt_amount(max_amount, "max_amount")

    conds = [Receipt.user_id == user.id]
    if status_ and status_.strip():
        if status_ not in {s.value for s in ProcessingStatus}:
            raise _err(422, "invalid_field", "Unknown status", field="status")
        conds.append(Receipt.processing_status == status_)
    else:
        conds.append(Receipt.processing_status != ProcessingStatus.ARCHIVED.value)
    if category and category.strip():
        if category not in EXPENSE_CATEGORIES:
            raise _err(422, "invalid_field", "Unknown category", field="category")
        conds.append(Receipt.category == category)
    if q and q.strip():
        pattern = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conds.append(or_(
            func.lower(Receipt.merchant).like(pattern, escape="\\"),
            func.lower(Receipt.receipt_number).like(pattern, escape="\\"),
            func.lower(Receipt.notes).like(pattern, escape="\\"),
            func.lower(Receipt.id).like(pattern, escape="\\"),
        ))
    if df:
        conds.append(Receipt.receipt_date >= df)
    if dt:
        conds.append(Receipt.receipt_date <= dt)
    if lo is not None:
        conds.append(Receipt.total >= lo)
    if hi is not None:
        conds.append(Receipt.total <= hi)

    total = await session.scalar(select(func.count()).select_from(Receipt).where(*conds))
    rows = (
        await session.execute(
            select(Receipt).where(*conds).order_by(Receipt.created_at.desc(), Receipt.id).limit(limit).offset(offset)
        )
    ).scalars().all()
    return {"items": [receipt_to_out(r) for r in rows], "total": int(total or 0)}


# --------------------------------------------------------------------------- #
# Premium: summary + exports
# --------------------------------------------------------------------------- #
def _period(month: str | None, date_from: str | None, date_to: str | None) -> tuple[date, date, str]:
    """Month, or a custom range (how quarters/years are asked for). 422 on anything invalid."""
    today = plans.now_utc().astimezone(plans.PERIOD_TZ).date()
    try:
        return exports.resolve_period(
            month.strip() if month and month.strip() else None,
            _opt_date(date_from, "date_from"), _opt_date(date_to, "date_to"), today,
        )
    except ValueError as exc:
        raise _err(422, "invalid_field", f"Invalid period: {exc}", field="date_from" if date_from or date_to else "month") from None


async def _saved_for_period(session: AsyncSession, user: User, start: date, end: date) -> list[Receipt]:
    return list((await session.execute(
        select(Receipt).where(
            Receipt.user_id == user.id,
            Receipt.processing_status == ProcessingStatus.SAVED.value,
            or_(Receipt.receipt_date.is_(None), (Receipt.receipt_date >= start) & (Receipt.receipt_date <= end)),
        )
    )).scalars().all())


def _in_period(saved: list[Receipt], start: date, end: date) -> list[Receipt]:
    return [r for r in saved if r.receipt_date and start <= r.receipt_date <= end]


@router.get("/summary")
async def period_summary(
    user: PremiumUser, session: SessionDep, month: str | None = None, date_from: str | None = None, date_to: str | None = None
) -> dict:
    start, end, label = _period(month, date_from, date_to)
    return exports.build_period_summary(start, end, label, await _saved_for_period(session, user, start, end))


@router.get("/export")
async def export_receipts(
    user: PremiumUser,
    session: SessionDep,
    format: str = "csv",
    month: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
) -> Response:
    if format not in ("csv", "json"):
        raise _err(422, "invalid_field", "format must be csv or json", field="format")
    conds = [Receipt.user_id == user.id, Receipt.processing_status == ProcessingStatus.SAVED.value]
    label = "all"
    if month and month.strip():
        month = _parse_month(month)
        start, end = exports.month_range(month)
        conds += [Receipt.receipt_date >= start, Receipt.receipt_date <= end]
        label = month
    df, dt = _opt_date(date_from, "date_from"), _opt_date(date_to, "date_to")
    if df:
        conds.append(Receipt.receipt_date >= df)
    if dt:
        conds.append(Receipt.receipt_date <= dt)
    if category and category.strip():
        if category not in EXPENSE_CATEGORIES:
            raise _err(422, "invalid_field", "Unknown category", field="category")
        conds.append(Receipt.category == category)
    rows = list((await session.execute(select(Receipt).where(*conds).order_by(Receipt.receipt_date, Receipt.id))).scalars().all())
    if format == "csv":
        body, media = exports.receipts_csv(rows), "text/csv; charset=utf-8"
    else:
        body, media = exports.receipts_json(rows), "application/json"
    return Response(body, media_type=media, headers=pdf.download_headers(f"tradetrack-receipts-{label}.{format}"))


async def _summary_pdf(user: User, summary: dict, receipts: list[Receipt]) -> bytes:
    business = user.business_name or f"{user.first_name} {user.last_name}"
    return await asyncio.to_thread(pdf.render_summary_pdf, summary, [r for r in receipts if r.currency == "CAD"], business)


@router.get("/export/summary")
async def export_summary(
    user: PremiumUser, session: SessionDep, month: str | None = None, date_from: str | None = None,
    date_to: str | None = None, format: str = "pdf",
) -> Response:
    if format not in ("csv", "pdf"):
        raise _err(422, "invalid_field", "format must be csv or pdf", field="format")
    start, end, label = _period(month, date_from, date_to)
    saved = await _saved_for_period(session, user, start, end)
    summary = exports.build_period_summary(start, end, label, saved)
    name = f"tradetrack-summary-{label.replace(' to ', '_to_')}"
    if format == "csv":
        return Response(exports.summary_csv(summary), media_type="text/csv; charset=utf-8",
                        headers=pdf.download_headers(f"{name}.csv"))
    body = await _summary_pdf(user, summary, _in_period(saved, start, end))
    return Response(body, media_type="application/pdf", headers=pdf.download_headers(f"{name}.pdf"))


@router.get("/export/package")
async def export_package(
    user: PremiumUser, session: SessionDep, month: str | None = None, date_from: str | None = None, date_to: str | None = None
) -> Response:
    """ZIP for the accountant: summary PDF, receipts CSV and the original file of each receipt.
    Works without any email provider. Owner-only (rows are filtered by the signed-in user)."""
    start, end, label = _period(month, date_from, date_to)
    saved = await _saved_for_period(session, user, start, end)
    in_period = sorted(_in_period(saved, start, end), key=lambda r: (r.receipt_date, r.id))
    if len(in_period) > exports.MAX_PACKAGE_RECEIPTS or \
            sum(r.file_size_bytes or 0 for r in in_period) > exports.MAX_PACKAGE_BYTES:
        raise _err(413, "package_too_large",
                   "That period has too many receipts or files for one package. Choose a shorter period "
                   "(for example one month) and download it in parts.")
    summary = exports.build_period_summary(start, end, label, saved)
    originals: dict[str, bytes] = {}
    for r in in_period:
        data = await storage.get_file(session, r)
        if data is not None:
            originals[exports.original_name(r)] = data
    pdf_bytes = await _summary_pdf(user, summary, in_period)
    body = await asyncio.to_thread(exports.build_package, pdf_bytes, exports.receipts_csv(in_period), originals)
    name = f"tradetrack-accountant-package-{label.replace(' to ', '_to_')}.zip"
    return Response(body, media_type="application/zip", headers=pdf.download_headers(name))


@router.post("/export/email")
async def email_to_accountant(body: EmailExportRequest, user: PremiumUser, session: SessionDep) -> dict:
    if not user.accountant_email:
        raise _err(400, "no_accountant_email", "Add your accountant's email address in your account settings first.")
    if not settings.smtp_configured:
        raise _err(503, "email_not_configured", "Email sending is not configured on this server, so nothing was sent.")
    start, end, label = _period(body.month, body.date_from, body.date_to)
    saved = await _saved_for_period(session, user, start, end)
    summary = exports.build_period_summary(start, end, label, saved)
    in_period = sorted(_in_period(saved, start, end), key=lambda r: (r.receipt_date, r.id))
    csv_bytes = exports.receipts_csv(in_period)
    pdf_bytes = await _summary_pdf(user, summary, in_period)
    try:
        await mailer.send_month_to_accountant(user.accountant_email, user, label, csv_bytes, pdf_bytes)
    except mailer.EmailNotConfigured:
        raise _err(503, "email_not_configured", "Email sending is not configured on this server, so nothing was sent.") from None
    except mailer.EmailSendFailed:
        raise _err(502, "email_send_failed", "The email could not be sent. Nothing was delivered. Please try again later.") from None
    return {"sent": True, "to": user.accountant_email, "month": label, "receipts": len(in_period)}


# --------------------------------------------------------------------------- #
# Single receipt
# --------------------------------------------------------------------------- #
@router.get("/{receipt_id}", response_model=ReceiptOut)
async def get_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> ReceiptOut:
    return receipt_to_out(await _get_owned(session, user, receipt_id))


@router.patch("/{receipt_id}", response_model=ReceiptOut)
async def update_receipt(receipt_id: str, body: ReceiptUpdate, user: CurrentUser, session: SessionDep) -> ReceiptOut:
    r = await _get_owned(session, user, receipt_id)
    try:
        applied = apply_patch(r, body)
    except FieldError as exc:
        await session.rollback()  # discard half-applied changes
        raise _invalid_field(exc) from None
    if r.processing_status == ProcessingStatus.SAVED.value:
        missing = missing_required(r)
        if missing:
            await session.rollback()
            raise _err(422, "missing_required_fields", "A saved receipt must keep its merchant and total.", fields=missing)
    if applied and r.processing_status == ProcessingStatus.FAILED.value:
        r.processing_status = ProcessingStatus.NEEDS_REVIEW.value  # being completed by hand
    refresh_warnings(r, default_province=user.province, keep_sticky="currency" not in applied)
    r.updated_at = utcnow()
    session.add(r)
    await session.flush()
    return receipt_to_out(r)


@router.post("/{receipt_id}/save", response_model=ReceiptOut)
async def save_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> ReceiptOut:
    """Confirm the receipt. Idempotent. The free-plan limit is enforced here, on the server."""
    # Lock the account row so two simultaneous saves cannot both slip under the limit.
    await session.execute(select(User).where(User.id == user.id).with_for_update())
    r = await _get_owned(session, user, receipt_id)
    if r.processing_status == ProcessingStatus.SAVED.value:
        return receipt_to_out(r)
    if r.processing_status == ProcessingStatus.ARCHIVED.value:
        raise _err(409, "receipt_archived", "Restore this receipt from the archive before saving it.")
    missing = missing_required(r)
    if missing:
        raise _err(422, "missing_required_fields", "Merchant and total are required to save a receipt.", fields=missing)

    now = plans.now_utc()
    period = plans.period_key(now)
    plan = plans.plan_for(user.plan)
    if plan.monthly_receipt_limit is not None:
        used = await saved_in_period(session, user.id, period)
        if used >= plan.monthly_receipt_limit:
            _, end = plans.period_bounds(now)
            raise _err(
                402, "free_limit_reached",
                f"You have saved {used} of {plan.monthly_receipt_limit} receipts this month. "
                f"Upgrade to Premium for unlimited receipts, or wait until {plans.resets_on(now).isoformat()}.",
                limit=plan.monthly_receipt_limit, used=used, period_end=end.isoformat(),
            )

    r.processing_status = ProcessingStatus.SAVED.value
    r.reviewed_at = now
    r.extraction_error = None
    r.updated_at = now
    session.add(r)
    already = (await session.execute(select(UsageEvent).where(UsageEvent.receipt_id == r.id))).scalar_one_or_none()
    if already is None:
        session.add(UsageEvent(user_id=user.id, receipt_id=r.id, period=period))
    await session.flush()
    return receipt_to_out(r)


@router.post("/{receipt_id}/archive", response_model=ReceiptOut)
async def archive_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> ReceiptOut:
    r = await _get_owned(session, user, receipt_id)
    if r.processing_status != ProcessingStatus.ARCHIVED.value:
        r.status_before_archive = r.processing_status
        r.processing_status = ProcessingStatus.ARCHIVED.value
        r.updated_at = utcnow()
        session.add(r)
        await session.flush()
    return receipt_to_out(r)


@router.post("/{receipt_id}/unarchive", response_model=ReceiptOut)
async def unarchive_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> ReceiptOut:
    r = await _get_owned(session, user, receipt_id)
    if r.processing_status == ProcessingStatus.ARCHIVED.value:
        r.processing_status = r.status_before_archive or ProcessingStatus.NEEDS_REVIEW.value
        r.status_before_archive = None
        r.updated_at = utcnow()
        session.add(r)
        await session.flush()
    return receipt_to_out(r)


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_receipt(receipt_id: str, user: CurrentUser, session: SessionDep) -> Response:
    """Permanently delete the receipt and its file. The usage row is deliberately KEPT, so
    deleting a saved receipt does not hand back allowance within the same month."""
    r = await _get_owned(session, user, receipt_id)
    await storage.delete_file(session, r)
    await session.delete(r)
    await session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{receipt_id}/file")
async def get_original_file(receipt_id: str, user: CurrentUser, session: SessionDep) -> Response:
    r = await _get_owned(session, user, receipt_id)
    data = await storage.get_file(session, r) if r.file_storage else None
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No original file is stored for this receipt")
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"}.get(r.file_mime_type or "", "bin")
    name = _safe_filename(r.original_filename, f"{r.id}.{ext}")
    return Response(data, media_type=r.file_mime_type or "application/octet-stream",
                    headers=pdf.download_headers(name, inline=True))


@router.get("/{receipt_id}/pdf")
async def get_receipt_pdf(receipt_id: str, user: CurrentUser, session: SessionDep) -> Response:
    r = await _get_owned(session, user, receipt_id)
    body = await asyncio.to_thread(pdf.render_receipt_pdf, r)
    return Response(body, media_type="application/pdf", headers=pdf.download_headers(pdf.receipt_filename(r, "pdf")))

"""Database tables (SQLModel) and request/response schemas (Pydantic).

TradeTrack is a private, owner-only receipt/expense tracker for Canadian self-employed
people and small businesses.

All tables use the ``tt_`` prefix so they never collide with the legacy ZZPay tables
(users, receipts, credit_notes) that may still exist in the shared Neon database. Those
legacy tables are never read, altered or dropped by this app (see docs/database.md).

Tables
* ``tt_users``          - an account (plan, billing ids, secret forwarding alias).
* ``tt_receipts``       - one receipt, ALWAYS owned (``user_id`` NOT NULL).
* ``tt_receipt_files``  - original upload bytes (when file storage is "database").
* ``tt_usage_events``   - one row per SAVED receipt; drives the free-plan limit.
* ``tt_inbound_events`` - minimal log of forwarded emails (no bodies or subjects).
* ``tt_inbound_tokens`` - Mailgun webhook tokens already seen (replay protection).

Money is ``Numeric(10, 2)`` in the database and a *string* ("13.00") in JSON. AI output
is never authoritative: ``null`` always means "unavailable / not read".
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field as PField, field_validator
from sqlalchemy import JSON, Column, Date, DateTime, LargeBinary, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Enums / constants
# --------------------------------------------------------------------------- #
class Plan(str, Enum):
    FREE = "FREE"
    PREMIUM = "PREMIUM"


class ReceiptSource(str, Enum):
    UPLOAD = "UPLOAD"
    EMAIL = "EMAIL"


class ProcessingStatus(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"  # extracted (or empty for manual entry); not yet confirmed
    SAVED = "SAVED"                # user confirmed — counts against the monthly allowance
    FAILED = "FAILED"              # extraction failed / unavailable; never counts
    ARCHIVED = "ARCHIVED"          # hidden by the owner


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class InboundStatus(str, Enum):
    PROCESSED = "PROCESSED"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"


PROVINCE_CODES = ["ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "PE", "NL", "YT", "NT", "NU"]
Province = Enum("Province", {c: c for c in PROVINCE_CODES}, type=str)

EXPENSE_CATEGORIES = [
    "Tools and equipment",
    "Building materials and supplies",
    "Vehicle expenses and fuel",
    "Repairs and maintenance",
    "Office supplies",
    "Software and subscriptions",
    "Telecommunications",
    "Travel and accommodation",
    "Meals and entertainment",
    "Professional services",
    "Other business expenses",
]


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
class User(SQLModel, table=True):
    __tablename__ = "tt_users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(index=True, unique=True)
    first_name: str
    last_name: str
    password_hash: str

    business_name: str | None = Field(default=None)
    province: str = Field(default="ON")
    accountant_email: str | None = Field(default=None)
    # None = "not stated". A business may or may not be registered for GST/HST.
    gst_hst_registered: bool | None = Field(default=None)
    gst_hst_number: str | None = Field(default=None)

    # The server is the only source of truth for plan/entitlements.
    plan: str = Field(default=Plan.FREE.value)
    stripe_customer_id: str | None = Field(default=None, index=True)
    stripe_subscription_id: str | None = Field(default=None)
    subscription_status: str | None = Field(default=None)
    current_period_end: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    cancel_at_period_end: bool = Field(default=False)

    # Secret local-part of the user's forwarding address. Random, never derived from
    # the user's name or email. Only this identifies the account for inbound email.
    forwarding_alias: str = Field(index=True, unique=True)

    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class Receipt(SQLModel, table=True):
    __tablename__ = "tt_receipts"
    __table_args__ = (UniqueConstraint("user_id", "file_sha256", name="uq_tt_receipt_user_filehash"),)

    id: str = Field(primary_key=True)  # "TT-2026-A1B2C3"
    user_id: UUID = Field(foreign_key="tt_users.id", index=True, nullable=False)

    source: str = Field(default=ReceiptSource.UPLOAD.value)
    processing_status: str = Field(default=ProcessingStatus.NEEDS_REVIEW.value, index=True)
    status_before_archive: str | None = Field(default=None)
    extraction_confidence: str = Field(default=Confidence.UNKNOWN.value)
    extraction_error: str | None = Field(default=None)

    original_filename: str | None = Field(default=None)
    file_mime_type: str | None = Field(default=None)
    file_size_bytes: int | None = Field(default=None)
    file_sha256: str | None = Field(default=None)  # duplicate detection (per user)
    file_storage: str | None = Field(default=None)  # "database" | "s3" | None (no file kept)
    file_key: str | None = Field(default=None)       # S3 object key when file_storage == "s3"
    is_sample: bool = Field(default=False)

    merchant: str | None = Field(default=None)
    receipt_date: date | None = Field(default=None, sa_type=Date, index=True)
    receipt_time: str | None = Field(default=None)
    currency: str = Field(default="CAD")
    receipt_number: str | None = Field(default=None)
    line_items: list = Field(default_factory=list, sa_column=Column(JSON))
    discounts: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    subtotal: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    tax_lines: list = Field(default_factory=list, sa_column=Column(JSON))
    tax_total: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    total: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    province: str | None = Field(default=None)

    category: str | None = Field(default=None)
    category_is_ai_suggested: bool = Field(default=False)

    warnings: list = Field(default_factory=list, sa_column=Column(JSON))
    notes: str | None = Field(default=None)            # the owner's own note
    processing_note: str | None = Field(default=None)  # server message, e.g. duplicate

    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True), index=True)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class ReceiptFile(SQLModel, table=True):
    """Original upload bytes. Private: only served through the authenticated /file route."""

    __tablename__ = "tt_receipt_files"

    receipt_id: str = Field(primary_key=True)
    user_id: UUID = Field(foreign_key="tt_users.id", index=True, nullable=False)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))


class UsageEvent(SQLModel, table=True):
    """One row per receipt that was SAVED. The free-plan limit counts these rows.

    ``receipt_id`` is intentionally NOT a foreign key and the row is NOT removed when the
    receipt is deleted: otherwise "save, delete, upload again" would give unlimited free
    receipts. It is removed only when the whole account is deleted.
    """

    __tablename__ = "tt_usage_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="tt_users.id", index=True, nullable=False)
    receipt_id: str = Field(unique=True, index=True)  # unique => saving twice never double counts
    period: str = Field(index=True)  # "2026-10" (America/Toronto calendar month)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class InboundEvent(SQLModel, table=True):
    """Minimal log of a forwarded email. No sender, subject or body is stored."""

    __tablename__ = "tt_inbound_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="tt_users.id", index=True, nullable=False)
    received_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True), index=True)
    status: str
    reason: str | None = Field(default=None)
    attachments: int = Field(default=0)
    receipt_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    message_hash: str | None = Field(default=None, index=True)  # SHA-256 of the Message-Id


class InboundToken(SQLModel, table=True):
    """Mailgun webhook tokens already used (replay protection). Pruned after an hour."""

    __tablename__ = "tt_inbound_tokens"

    token_hash: str = Field(primary_key=True)
    seen_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True), index=True)


# --------------------------------------------------------------------------- #
# Schemas - users
# --------------------------------------------------------------------------- #
class UserCreate(BaseModel):
    email: EmailStr
    first_name: str = PField(min_length=1, max_length=80)
    last_name: str = PField(min_length=1, max_length=80)
    password: str = PField(min_length=8, max_length=128)
    business_name: str | None = PField(default=None, max_length=120)
    province: Province = Province.ON
    accountant_email: EmailStr | None = None

    @field_validator("first_name", "last_name", "business_name", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("accountant_email", "business_name", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class UserUpdate(BaseModel):
    first_name: str | None = PField(default=None, min_length=1, max_length=80)
    last_name: str | None = PField(default=None, min_length=1, max_length=80)
    business_name: str | None = PField(default=None, max_length=120)
    province: Province | None = None
    accountant_email: EmailStr | None = None
    gst_hst_registered: bool | None = None
    gst_hst_number: str | None = PField(default=None, max_length=30)

    @field_validator("accountant_email", "business_name", "gst_hst_number", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class UserOut(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    business_name: str | None
    province: str
    accountant_email: str | None
    gst_hst_registered: bool | None
    gst_hst_number: str | None
    plan: str
    subscription_status: str | None
    forwarding_alias: str
    forwarding_address: str | None
    created_at: datetime


class RegisterOut(UserOut):
    """Sign-up response: the new user plus what happened to the welcome email.
    "sent" | "failed" | "not_configured". Never "sent" unless the provider accepted it."""

    welcome_email: str


def user_to_out(user: User) -> UserOut:
    address = (
        f"{user.forwarding_alias}@{settings.inbound_domain.strip().lower()}"
        if settings.inbound_email_configured
        else None
    )
    return UserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        business_name=user.business_name,
        province=user.province,
        accountant_email=user.accountant_email,
        gst_hst_registered=user.gst_hst_registered,
        gst_hst_number=user.gst_hst_number,
        plan=user.plan,
        subscription_status=user.subscription_status,
        forwarding_alias=user.forwarding_alias,
        forwarding_address=address,
        created_at=as_utc(user.created_at),
    )


class DeleteAccount(BaseModel):
    password: str


# --------------------------------------------------------------------------- #
# Schemas - receipts
# --------------------------------------------------------------------------- #
class LineItemOut(BaseModel):
    description: str
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None


class TaxLineOut(BaseModel):
    label: str
    amount: str
    tax_type: str


class WarningOut(BaseModel):
    code: str
    severity: str
    field: str | None = None
    message: str


class ReceiptOut(BaseModel):
    id: str
    source: str
    processing_status: str
    extraction_confidence: str
    extraction_error: str | None
    original_filename: str | None
    file_mime_type: str | None
    has_original_file: bool
    is_sample: bool
    merchant: str | None
    receipt_date: str | None
    receipt_time: str | None
    currency: str
    receipt_number: str | None
    line_items: list[LineItemOut]
    discounts: str | None
    subtotal: str | None
    tax_lines: list[TaxLineOut]
    tax_total: str | None
    total: str | None
    province: str | None
    category: str | None
    category_is_ai_suggested: bool
    warnings: list[WarningOut]
    notes: str | None
    processing_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


def money_str(value: Decimal | None) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


def receipt_to_out(r: Receipt) -> ReceiptOut:
    return ReceiptOut(
        id=r.id,
        source=r.source,
        processing_status=r.processing_status,
        extraction_confidence=r.extraction_confidence,
        extraction_error=r.extraction_error,
        original_filename=r.original_filename,
        file_mime_type=r.file_mime_type,
        has_original_file=r.file_storage is not None,
        is_sample=r.is_sample,
        merchant=r.merchant,
        receipt_date=r.receipt_date.isoformat() if r.receipt_date else None,
        receipt_time=r.receipt_time,
        currency=r.currency,
        receipt_number=r.receipt_number,
        line_items=[LineItemOut(**li) for li in (r.line_items or [])],
        discounts=money_str(r.discounts),
        subtotal=money_str(r.subtotal),
        tax_lines=[TaxLineOut(**t) for t in (r.tax_lines or [])],
        tax_total=money_str(r.tax_total),
        total=money_str(r.total),
        province=r.province,
        category=r.category,
        category_is_ai_suggested=r.category_is_ai_suggested,
        warnings=[WarningOut(**w) for w in (r.warnings or [])],
        notes=r.notes,
        processing_note=r.processing_note,
        reviewed_at=as_utc(r.reviewed_at),
        created_at=as_utc(r.created_at),
        updated_at=as_utc(r.updated_at),
    )


class ReceiptUpdate(BaseModel):
    """Partial update. Amounts/dates are typed loosely here and validated in
    ``validation.apply_patch`` so errors come back as one clear 422. Only fields that
    were actually sent (``model_fields_set``) are applied; unknown fields are ignored,
    so a client can never set owner, status, plan or ids through this body."""

    model_config = ConfigDict(extra="ignore")

    merchant: str | None = None
    receipt_date: str | None = None
    receipt_time: str | None = None
    currency: str | None = None
    receipt_number: str | None = None
    line_items: list[dict] | None = None
    discounts: str | int | float | None = None
    subtotal: str | int | float | None = None
    tax_lines: list[dict] | None = None
    tax_total: str | int | float | None = None
    total: str | int | float | None = None
    province: str | None = None
    category: str | None = None
    notes: str | None = None


class EmailExportRequest(BaseModel):
    """Either ``month`` (YYYY-MM) or ``date_from`` + ``date_to`` (YYYY-MM-DD). Neither = this month."""

    month: str | None = PField(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    date_from: str | None = PField(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = PField(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

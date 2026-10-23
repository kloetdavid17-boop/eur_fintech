"""Database tables (SQLModel) and the request/response schemas (Pydantic).

TradeTrack is a private, owner-only receipt/expense tracker for Canadian
self-employed people and small businesses. Three entities:

* ``User``    — an account (required for anything persistent). Holds plan/
                billing status, province (for tax defaults), and the unique
                email-forwarding alias.
* ``Receipt`` — an uploaded or emailed receipt, run through AI extraction,
                reviewed/corrected by the owner, then saved. ALWAYS owned
                (``user_id`` is NOT nullable) — there is no public, anonymous
                receipt concept in TradeTrack.
* ``UsageEvent`` — one row per successfully *saved* receipt, used to enforce
                the free-plan monthly limit server-side. (A receipt that fails
                processing or is never saved must not count against the quota.)

Money uses ``Decimal``/``Numeric(10, 2)``; in JSON we serialise decimals as
strings to avoid binary-float drift. Timestamps are timezone-aware UTC.

IMPORTANT — AI output is never authoritative. ``extraction_confidence`` and
``processing_status`` exist so the UI can visibly flag anything the user
should double-check. Nothing here should be presented as verified fact until
the user has reviewed it (``reviewed_at`` is set when they confirm/save).
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr
from sqlalchemy import JSON, Column, DateTime, Numeric
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel, func, select


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Plan(str, Enum):
    FREE = "FREE"
    PREMIUM = "PREMIUM"


class ReceiptSource(str, Enum):
    UPLOAD = "UPLOAD"   # user selected a file / took a photo
    EMAIL = "EMAIL"      # arrived via the forwarding alias


class ProcessingStatus(str, Enum):
    PENDING = "PENDING"           # queued / in flight
    NEEDS_REVIEW = "NEEDS_REVIEW"  # AI returned a result; user hasn't confirmed yet
    SAVED = "SAVED"                # user reviewed and saved — counts against quota
    FAILED = "FAILED"              # AI/service error; does not count against quota
    ARCHIVED = "ARCHIVED"          # soft-deleted/archived by the user


class ExtractionConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"  # e.g. AI service unavailable, manual entry only


# Canadian provinces/territories — used for tax defaults, not enforced strictly
# (a business may have receipts from multiple provinces).
class Province(str, Enum):
    ON = "ON"
    QC = "QC"
    BC = "BC"
    AB = "AB"
    MB = "MB"
    SK = "SK"
    NS = "NS"
    NB = "NB"
    PE = "PE"
    NL = "NL"
    YT = "YT"
    NT = "NT"
    NU = "NU"


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
    """An account. Required for any persisted receipt — TradeTrack has no
    anonymous/public receipt concept."""

    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(index=True, unique=True)
    first_name: str
    last_name: str
    password_hash: str

    # Business profile
    business_name: str | None = Field(default=None)
    province: str = Field(default=Province.ON.value)  # drives default tax labels
    accountant_email: str | None = Field(default=None)

    # Billing / plan. Server is the single source of truth for what a user can
    # do — the frontend must never infer entitlement from local state alone.
    plan: str = Field(default=Plan.FREE.value)
    stripe_customer_id: str | None = Field(default=None)
    stripe_subscription_id: str | None = Field(default=None)
    subscription_status: str | None = Field(default=None)  # mirrors Stripe status

    # Unique, unguessable alias for inbound email forwarding, e.g.
    # "a1b2c3d4@receipts.tradetrack.app". Generated at signup. Never derived
    # from the user's real email or name (that would make it guessable).
    forwarding_alias: str = Field(index=True, unique=True)

    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=DateTime(timezone=True)
    )


class Receipt(SQLModel, table=True):
    """An uploaded or emailed receipt: raw file reference + AI-extracted fields
    + user corrections. Always owned — enforce ``user_id == current_user.id``
    on every read/write in the router, not just in the UI.
    """

    __tablename__ = "receipts"

    id: str = Field(primary_key=True)  # "TT-2026-0001"
    user_id: UUID = Field(foreign_key="users.id", index=True, nullable=False)

    source: str = Field(default=ReceiptSource.UPLOAD.value)
    processing_status: str = Field(default=ProcessingStatus.PENDING.value, index=True)
    extraction_confidence: str = Field(default=ExtractionConfidence.UNKNOWN.value)
    extraction_error: str | None = Field(default=None)  # user-facing failure reason

    # Original file reference. If no object storage is configured, these may be
    # null and only the extracted structured data is kept (document this to
    # the user — do not claim a re-downloadable original exists if it doesn't).
    original_filename: str | None = Field(default=None)
    file_mime_type: str | None = Field(default=None)
    file_storage_key: str | None = Field(default=None)  # key/URL in object storage
    file_size_bytes: int | None = Field(default=None)

    # --- Extracted / user-corrected fields --------------------------------
    # Every one of these may be null if unreadable — never fabricate a value.
    merchant: str | None = Field(default=None)
    receipt_date: str | None = Field(default=None)   # ISO date "2026-06-04"
    currency: str = Field(default="CAD")
    receipt_number: str | None = Field(default=None)

    # [{description, quantity, unit_price, amount}, ...] — decimals as strings
    line_items: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    # [{"label": "HST", "amount": "13.00"}, ...] — labels come from the receipt
    # itself (or the user), never invented from a province's "typical" rate.
    tax_lines: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    subtotal: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    tax_total: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))
    total: Decimal | None = Field(default=None, sa_column=Column(Numeric(10, 2)))

    province: str | None = Field(default=None)  # jurisdiction for this specific receipt

    category: str | None = Field(default=None)       # from EXPENSE_CATEGORIES
    category_is_ai_suggested: bool = Field(default=False)  # False once user confirms/edits

    # Non-binding notes — e.g. "tax amount unclear, please verify" — shown as a
    # warning banner, never silently dropped.
    review_notes: str | None = Field(default=None)

    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))

    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=DateTime(timezone=True), index=True
    )
    updated_at: datetime = Field(
        default_factory=_utcnow, sa_type=DateTime(timezone=True)
    )


class UsageEvent(SQLModel, table=True):
    """One row per successfully SAVED receipt. The free-plan monthly limit is
    enforced by counting these rows in the current billing period — never by
    trusting a client-side counter. Failed/unsaved processing attempts must
    NOT create a row here.
    """

    __tablename__ = "usage_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True, nullable=False)
    receipt_id: str = Field(foreign_key="receipts.id", index=True)
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=DateTime(timezone=True), index=True
    )


# --------------------------------------------------------------------------- #
# Sequential, human-readable receipt IDs (TT-2026-0001)
# --------------------------------------------------------------------------- #
async def next_receipt_id(session: AsyncSession, year: int | None = None) -> str:
    year = year or _utcnow().year
    count = await session.scalar(select(func.count()).select_from(Receipt))
    return f"TT-{year}-{(count or 0) + 1:04d}"


# --------------------------------------------------------------------------- #
# Schemas — Users / account
# --------------------------------------------------------------------------- #
class UserCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    password: str = Field(min_length=8)
    business_name: str | None = None
    province: Province = Province.ON
    accountant_email: EmailStr | None = None


class UserUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    business_name: str | None = None
    province: Province | None = None
    accountant_email: EmailStr | None = None


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    business_name: str | None
    province: str
    accountant_email: str | None
    plan: Plan
    subscription_status: str | None
    forwarding_alias: str
    created_at: datetime


# --------------------------------------------------------------------------- #
# Schemas — Receipts
# --------------------------------------------------------------------------- #
class LineItemOut(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


class TaxLineOut(BaseModel):
    label: str
    amount: Decimal


class ReceiptOut(BaseModel):
    id: str
    source: ReceiptSource
    processing_status: ProcessingStatus
    extraction_confidence: ExtractionConfidence
    extraction_error: str | None

    original_filename: str | None
    file_mime_type: str | None
    has_original_file: bool  # computed: file_storage_key is not None

    merchant: str | None
    receipt_date: str | None
    currency: str
    receipt_number: str | None
    line_items: list[LineItemOut]
    tax_lines: list[TaxLineOut]
    subtotal: Decimal | None
    tax_total: Decimal | None
    total: Decimal | None
    province: str | None

    category: str | None
    category_is_ai_suggested: bool
    review_notes: str | None

    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReceiptUpdate(BaseModel):
    """User corrections applied before/at save time. All fields optional —
    send only what changed."""

    merchant: str | None = None
    receipt_date: str | None = None
    currency: str | None = None
    receipt_number: str | None = None
    line_items: list[LineItemOut] | None = None
    tax_lines: list[TaxLineOut] | None = None
    subtotal: Decimal | None = None
    tax_total: Decimal | None = None
    total: Decimal | None = None
    province: Province | None = None
    category: str | None = None


class UsageOut(BaseModel):
    plan: Plan
    saved_this_period: int
    limit: int | None  # None == unlimited (premium)
    period_start: datetime
    period_end: datetime

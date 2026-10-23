"""Central plan configuration — change prices, limits and features HERE.

Defaults are the assignment's demo values (Free: CAD 0 / 5 saved receipts per month,
Premium: CAD 5.99 / unlimited). The limit and price can also be overridden with
ZZPAY_FREE_MONTHLY_LIMIT and ZZPAY_PREMIUM_PRICE_CAD.

The usage period is the calendar month in ``America/Toronto``.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.config import settings

PERIOD_TZ = ZoneInfo("America/Toronto")


@dataclass(frozen=True)
class PlanDef:
    id: str
    name: str
    price_cad: str
    monthly_receipt_limit: int | None  # None == unlimited
    features: list[str]


def get_plans() -> dict[str, PlanDef]:
    price = str(Decimal(settings.premium_price_cad).quantize(Decimal("0.01")))
    return {
        "FREE": PlanDef(
            id="FREE",
            name="Free",
            price_cad="0.00",
            monthly_receipt_limit=settings.free_monthly_limit,
            features=[
                f"Up to {settings.free_monthly_limit} saved receipts per month",
                "Upload receipts (image or PDF)",
                "AI extraction + category suggestion",
                "Review and correct every field",
                "Search receipts by text, category and status",
                "Download the original file or a TradeTrack PDF",
            ],
        ),
        "PREMIUM": PlanDef(
            id="PREMIUM",
            name="Premium",
            price_cad=price,
            monthly_receipt_limit=None,
            features=[
                "Unlimited saved receipts",
                "Email-forwarding receipt capture",
                "Date and amount filters",
                "Monthly expense summary (PDF and CSV)",
                "CSV / JSON export",
                "Email the month's records to your accountant",
            ],
        ),
    }


# (feature label, free, premium) — shown as the comparison table in the UI.
FEATURE_MATRIX: list[tuple[str, bool, bool]] = [
    ("Upload receipts (image or PDF)", True, True),
    ("AI extraction + category suggestion", True, True),
    ("Review, correct and save receipts", True, True),
    ("Original file download and TradeTrack PDF", True, True),
    ("Search by text, category and status", True, True),
    ("Unlimited saved receipts", False, True),
    ("Email-forwarding receipt capture", False, True),
    ("Date and amount filters", False, True),
    ("Monthly expense summary", False, True),
    ("CSV & JSON export", False, True),
    ("Email records to your accountant", False, True),
]

PREMIUM_FEATURES = {"inbound_email", "filters", "summary", "export", "email_accountant"}


def plan_for(plan_id: str) -> PlanDef:
    return get_plans().get(plan_id, get_plans()["FREE"])


# --------------------------------------------------------------------------- #
# Usage period (calendar month, America/Toronto)
# --------------------------------------------------------------------------- #
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def period_key(moment: datetime | None = None) -> str:
    """'2026-10' for the Toronto calendar month containing ``moment``."""
    local = (moment or now_utc()).astimezone(PERIOD_TZ)
    return f"{local.year:04d}-{local.month:02d}"


def period_bounds(moment: datetime | None = None) -> tuple[datetime, datetime]:
    """(start, end) of the Toronto calendar month as UTC datetimes; end is exclusive."""
    local = (moment or now_utc()).astimezone(PERIOD_TZ)
    start = datetime(local.year, local.month, 1, tzinfo=PERIOD_TZ)
    ny, nm = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    end = datetime(ny, nm, 1, tzinfo=PERIOD_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def period_label(moment: datetime | None = None) -> str:
    local = (moment or now_utc()).astimezone(PERIOD_TZ)
    return local.strftime("%B %Y")


def resets_on(moment: datetime | None = None) -> date:
    """First day of the next period, as a Toronto-local date."""
    _, end = period_bounds(moment)
    return end.astimezone(PERIOD_TZ).date()

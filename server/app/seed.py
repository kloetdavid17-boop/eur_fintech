"""Optional demo data. Runs only in development or when ZZPAY_SEED_DEMO=true; otherwise does nothing.

Creates ``demo@tradetrack.ca`` (password: ZZPAY_DEMO_PASSWORD, default ``demo1234``) as a Premium
account with three clearly labelled SAMPLE Ontario receipts (``is_sample = true``). Idempotent: it
never modifies an existing demo account's receipts and never touches any other user's data.
These receipts are illustrative - they are not read from real documents and have no original file.
"""

import logging
from datetime import date
from decimal import Decimal

from sqlmodel import select

from app import pipeline
from app.auth import hash_password
from app.config import settings
from app.database import async_session
from app.models import Plan, Receipt, User, utcnow
from app.routers.users import new_alias
from app.validation import refresh_warnings

logger = logging.getLogger("tradetrack.seed")

DEMO_EMAIL = "demo@tradetrack.ca"
SAMPLE_NOTE = "SAMPLE DATA: illustrative receipt for the demo account, not a real purchase."

# (merchant, date, category, [(description, qty, unit, amount)], subtotal, HST, total)
SAMPLES = [
    ("Canadian Tire", date(2026, 10, 6), "Tools and equipment",
     [("Cordless drill 20V", "1", "119.99", "119.99"), ("Drill bit set", "1", "24.99", "24.99")],
     "144.98", "18.85", "163.83"),
    ("Home Depot", date(2026, 10, 12), "Building materials and supplies",
     [("2x4x8 SPF stud", "20", "4.18", "83.60"), ("Wood screws 3in (box)", "2", "11.49", "22.98")],
     "106.58", "13.86", "120.44"),
    ("Petro-Canada", date(2026, 10, 15), "Vehicle expenses and fuel",
     [("Regular unleaded 52.3 L", None, None, "89.41")],
     "89.41", "11.62", "101.03"),
]


def _enabled() -> bool:
    return settings.is_development or settings.seed_demo


async def run() -> None:
    if not _enabled():
        return
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.email == DEMO_EMAIL))).scalar_one_or_none()
        if user is not None:
            return  # already seeded; never touch an existing account's data
        user = User(
            email=DEMO_EMAIL, first_name="Demo", last_name="Contractor",
            business_name="Demo Renovations (sample account)",
            password_hash=hash_password(settings.demo_password),
            province="ON", plan=Plan.PREMIUM.value, subscription_status="demo",
            accountant_email="accountant@example.com", forwarding_alias=new_alias(),
        )
        session.add(user)
        await session.flush()
        for merchant, d, category, items, subtotal, hst, total in SAMPLES:
            r = Receipt(
                id=await pipeline.new_receipt_id(session), user_id=user.id, source="UPLOAD",
                processing_status="SAVED", extraction_confidence="UNKNOWN", is_sample=True,
                merchant=merchant, receipt_date=d, currency="CAD", province="ON",
                line_items=[{"description": desc, "quantity": q, "unit_price": u, "amount": a} for desc, q, u, a in items],
                subtotal=Decimal(subtotal), tax_lines=[{"label": "HST 13%", "amount": hst, "tax_type": "HST"}],
                tax_total=Decimal(hst), total=Decimal(total),
                category=category, category_is_ai_suggested=False,
                notes=SAMPLE_NOTE, reviewed_at=utcnow(),
            )
            refresh_warnings(r, default_province="ON")
            session.add(r)
        await session.commit()
        logger.info("Seeded demo account %s (password from ZZPAY_DEMO_PASSWORD, default demo1234)", DEMO_EMAIL)

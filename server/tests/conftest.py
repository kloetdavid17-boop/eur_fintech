"""Test fixtures: the app runs against an in-memory SQLite DB, with a FAKE extraction provider
(no network, no OpenAI), so the suite needs neither Postgres nor any credentials."""

import io
import json
import os

os.environ["ZZPAY_JWT_SECRET"] = "test-secret-not-for-production-0123456789abcdef"
os.environ["ZZPAY_OPENAI_API_KEY"] = "sk-test-fake"
os.environ["ZZPAY_ENVIRONMENT"] = "development"
for _k in list(os.environ):
    if _k.startswith("ZZPAY_") and _k.split("ZZPAY_")[1] in {
        "STRIPE_SECRET_KEY", "STRIPE_PRICE_ID", "STRIPE_WEBHOOK_SECRET", "MAILGUN_SIGNING_KEY",
        "INBOUND_DOMAIN", "SMTP_HOST", "S3_ENDPOINT", "POSTGRES_URL",
    }:
        del os.environ[_k]

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import extraction
from app.config import settings
from app.database import ensure_schema, get_session
from app.main import app
from app.ratelimit import limiter

REAL_CALL_PROVIDER = extraction.call_provider  # the real OpenAI-backed function

GOOD_RECEIPT = {
    "is_receipt": True,
    "merchant": "Canadian Tire",
    "receipt_date": "2026-10-06",
    "receipt_time": "14:32",
    "currency": "CAD",
    "receipt_number": "CT-12345",
    "line_items": [{"description": "Hammer", "quantity": 1, "unit_price": "100.00", "amount": "100.00"}],
    "discounts": None,
    "subtotal": "100.00",
    "tax_lines": [{"label": "HST 13%", "amount": "13.00", "tax_type": "HST"}],
    "tax_total": "13.00",
    "total": "113.00",
    "province": "ON",
    "category": "Tools and equipment",
    "confidence": "HIGH",
}


class FakeAI:
    """Replaces extraction.call_provider. Set .response to a dict, a str, or an Exception."""

    def __init__(self):
        self.response = dict(GOOD_RECEIPT)
        self.calls = 0

    async def __call__(self, doc):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        if isinstance(self.response, str):
            return self.response
        return json.dumps(self.response)


@pytest.fixture(autouse=True)
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(extraction, "call_provider", fake)
    return fake


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-fake")
    monkeypatch.setattr(settings, "environment", "development")
    yield
    limiter.reset()


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    await ensure_schema(eng)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    async def _get_session():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _get_session
    app.state.test_session_maker = maker
    yield eng
    app.dependency_overrides.clear()
    await eng.dispose()


@pytest_asyncio.fixture
async def client(engine):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client2(engine):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def db_maker(engine):
    return app.state.test_session_maker


# ---- helpers -------------------------------------------------------------- #
def png_bytes(n: int = 0) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (60, 40), (n % 256, (n * 7) % 256, (n * 13) % 256))
    img.putpixel((n % 60, n % 40), (255, 255, 255))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def jpeg_bytes(n: int = 0) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (60, 40), (200, n % 256, 10))
    out = io.BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()


def text_pdf_bytes(text: str = "Canadian Tire receipt total 113.00 HST 13.00 thank you for shopping") -> bytes:
    from xhtml2pdf import pisa

    out = io.BytesIO()
    pisa.CreatePDF(src=f"<html><body><p>{text}</p></body></html>", dest=out)
    return out.getvalue()


def image_pdf_bytes() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (80, 80), (30, 60, 90)).save(out, format="PDF")
    return out.getvalue()


async def register(c, email="owner@example.com", password="password123", **extra):
    body = {"email": email, "first_name": "Pat", "last_name": "Builder", "password": password, **extra}
    r = await c.post("/api/register", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def upload(c, data=None, name="receipt.png", mime="image/png", expect=200):
    r = await c.post("/api/receipts/process", files={"file": (name, data if data is not None else png_bytes(), mime)})
    assert r.status_code == expect, r.text
    return r.json()


async def upgrade(c):
    r = await c.post("/api/billing/demo/upgrade")
    assert r.status_code == 200, r.text

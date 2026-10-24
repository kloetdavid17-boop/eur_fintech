from decimal import Decimal

import pytest
from sqlmodel import select

from app import plans, seed, storage
from app.config import settings
from app.models import Receipt, User
from app.validation import cents, parse_money, parse_quantity

from .conftest import png_bytes, register, upload


@pytest.mark.parametrize("raw,expected", [
    ("13.00", "13.00"), ("$1,234.56", "1234.56"), ("12,34", "12.34"), (13, "13.00"), (0.1, "0.10"),
    ("(5.00)", None), ("0.005", "0.01"), ("0.004", "0.00"), (None, None), ("", None),
])
def test_parse_money(raw, expected):
    if expected is None and raw not in (None, ""):
        with pytest.raises(ValueError):
            parse_money(raw)
    else:
        assert (None if expected is None else f"{parse_money(raw):.2f}") == expected


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", float("nan"), float("inf"), "1e999", "abc", True, "99999999.99", "-1"])
def test_parse_money_rejects(bad):
    with pytest.raises(ValueError):
        parse_money(bad)


def test_rounding_is_half_up_on_decimals():
    assert cents(Decimal("106.58") * Decimal("0.13")) == Decimal("13.86")
    assert cents(Decimal("2.675")) == Decimal("2.68")
    assert parse_quantity("2.0") == "2" and parse_quantity("1,5") == "1.5"


def test_plan_periods_toronto():
    from datetime import datetime, timezone

    # 2026-11-01 03:00 UTC is still Oct 31 in Toronto (UTC-4 until Nov 1 06:00 UTC)
    moment = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)
    assert plans.period_key(moment) == "2026-10"
    start, end = plans.period_bounds(moment)
    assert start.isoformat() == "2026-10-01T04:00:00+00:00" and end.isoformat() == "2026-11-01T04:00:00+00:00"
    assert plans.resets_on(moment).isoformat() == "2026-11-01"
    dec = plans.period_bounds(datetime(2026, 12, 15, tzinfo=timezone.utc))
    assert dec[1].year == 2027


async def test_seed_only_when_enabled(db_maker, monkeypatch):
    monkeypatch.setattr(seed, "async_session", db_maker)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "seed_demo", False)
    await seed.run()
    async with db_maker() as s:
        assert (await s.execute(select(User))).first() is None

    monkeypatch.setattr(settings, "seed_demo", True)
    monkeypatch.setattr(settings, "demo_password", "s3cret-demo")
    await seed.run()
    await seed.run()  # idempotent
    async with db_maker() as s:
        users = (await s.execute(select(User))).scalars().all()
        assert [u.email for u in users] == ["demo@tradetrack.ca"] and users[0].plan == "PREMIUM"
        receipts = (await s.execute(select(Receipt))).scalars().all()
        assert len(receipts) == 3 and all(r.is_sample and r.province == "ON" and "SAMPLE" in r.notes for r in receipts)
        assert {r.merchant for r in receipts} == {"Canadian Tire", "Home Depot", "Petro-Canada"}
        assert all(r.warnings == [] for r in receipts)  # sample maths is internally consistent


async def test_demo_login_after_seed(client, db_maker, monkeypatch):
    monkeypatch.setattr(seed, "async_session", db_maker)
    monkeypatch.setattr(settings, "seed_demo", True)
    await seed.run()
    r = await client.post("/api/login", data={"username": "demo@tradetrack.ca", "password": settings.demo_password})
    assert r.status_code == 200
    items = (await client.get("/api/receipts")).json()["items"]
    assert len(items) == 3 and all(i["is_sample"] for i in items)


async def test_s3_reported_only_when_fully_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "s3_endpoint", "https://s3.example.com")
    monkeypatch.setattr(settings, "s3_bucket", "b")
    assert (await client.get("/api/config")).json()["services"]["file_storage"] == "database"
    monkeypatch.setattr(settings, "s3_access_key", "k")
    monkeypatch.setattr(settings, "s3_secret_key", "s")
    assert (await client.get("/api/config")).json()["services"]["file_storage"] == "s3"


async def test_s3_failure_falls_back_to_database(client, monkeypatch):
    for k, v in dict(s3_endpoint="https://s3.invalid", s3_bucket="b", s3_access_key="k", s3_secret_key="s").items():
        monkeypatch.setattr(settings, k, v)

    class Broken:
        def put_object(self, **kw):
            raise RuntimeError("no s3")

    monkeypatch.setattr(storage, "_s3_client", lambda: Broken())
    await register(client)
    rec = await upload(client)
    assert rec["has_original_file"] is True
    assert (await client.get(f"/api/receipts/{rec['id']}/file")).status_code == 200


async def test_receipt_id_collision_retry(client, monkeypatch):
    from app import pipeline

    await register(client)
    first = await upload(client, png_bytes(1))
    seq = iter([first["id"], first["id"], "TT-2026-ZZZZZZ"])
    monkeypatch.setattr(pipeline, "_random_id", lambda year: next(seq))
    second = await upload(client, png_bytes(2))
    assert second["id"] == "TT-2026-ZZZZZZ"


def test_extraction_prompt_covers_discounts():
    from app.extraction import SYSTEM_PROMPT

    assert "discounts" in SYSTEM_PROMPT and "POSITIVE" in SYSTEM_PROMPT
    assert "Do not list those lines in" in SYSTEM_PROMPT

import csv
import io
import json

import pytest

from app import email as mailer
from app.config import settings

from .conftest import GOOD_RECEIPT, png_bytes, register, upgrade, upload


@pytest.fixture
async def two_users(client, client2):
    await register(client, "a@example.com")
    await register(client2, "b@example.com")


async def test_ownership_everywhere(client, client2, two_users, ai):
    rec = await upload(client, png_bytes(1))
    rid = rec["id"]
    await client.post(f"/api/receipts/{rid}/save")
    base = f"/api/receipts/{rid}"
    attempts = [
        ("get", base, None), ("get", base + "/file", None), ("get", base + "/pdf", None),
        ("patch", base, {"merchant": "Hacked"}), ("post", base + "/save", None),
        ("post", base + "/archive", None), ("post", base + "/unarchive", None),
        ("post", base + "/reprocess", None), ("delete", base, None),
    ]
    for method, url, body in attempts:
        r = await getattr(client2, method)(url, **({"json": body} if body else {}))
        assert r.status_code == 404, (method, url, r.status_code)
    lst = (await client2.get("/api/receipts")).json()
    assert lst["total"] == 0
    assert (await client2.get("/api/receipts/usage")).json()["saved_this_period"] == 0
    # untouched for the owner
    own = (await client.get(base)).json()
    assert own["merchant"] == "Canadian Tire" and own["processing_status"] == "SAVED"
    assert (await client.get(base + "/file")).status_code == 200


async def test_premium_gating_for_free_plan(client, two_users):
    for url in ["/api/receipts?date_from=2026-01-01", "/api/receipts?date_to=2026-12-31",
                "/api/receipts?min_amount=1", "/api/receipts?max_amount=100",
                "/api/receipts/export?format=csv", "/api/receipts/export?format=json",
                "/api/receipts/summary?month=2026-10", "/api/receipts/export/summary?month=2026-10&format=pdf"]:
        r = await client.get(url)
        assert r.status_code == 402 and r.json()["detail"]["code"] == "premium_required", url
    r = await client.post("/api/receipts/export/email", json={"month": "2026-10"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "premium_required"
    # basic filters stay free
    assert (await client.get("/api/receipts?q=x&category=Office%20supplies&status=SAVED")).status_code == 200


async def _saved(c, ai, n, **fields):
    ai.response = {**GOOD_RECEIPT, **fields}
    rec = await upload(c, png_bytes(n))
    r = await c.post(f"/api/receipts/{rec['id']}/save")
    assert r.status_code == 200, r.text
    return r.json()


async def test_premium_filters(client, two_users, ai):
    await upgrade(client)
    await _saved(client, ai, 10, receipt_date="2026-09-15", total="50.00", subtotal="44.25", tax_total="5.75",
                 tax_lines=[{"label": "HST", "amount": "5.75", "tax_type": "HST"}])
    await _saved(client, ai, 11, receipt_date="2026-10-15", total="500.00", subtotal="442.48", tax_total="57.52",
                 tax_lines=[{"label": "HST", "amount": "57.52", "tax_type": "HST"}])
    g = lambda **p: client.get("/api/receipts", params=p)  # noqa: E731
    assert (await g(date_from="2026-10-01")).json()["total"] == 1
    assert (await g(date_to="2026-09-30")).json()["total"] == 1
    assert (await g(min_amount="100")).json()["total"] == 1
    assert (await g(max_amount="100")).json()["total"] == 1
    assert (await g(date_from="nope")).status_code == 422
    assert (await g(min_amount="abc")).status_code == 422


async def test_csv_export_matches_stored_and_neutralises_injection(client, two_users, ai):
    await upgrade(client)
    saved = await _saved(client, ai, 20, merchant="=HYPERLINK(\"http://evil\",\"x\")", receipt_number="@cmd",
                         total="1234.56", subtotal="1092.53", tax_total="142.03",
                         tax_lines=[{"label": "+HST 13%", "amount": "142.03", "tax_type": "HST"}],
                         line_items=[{"description": "x", "amount": "1092.53"}], receipt_date="2026-10-07")
    r = await client.get("/api/receipts/export", params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert len(rows) == 1
    row = rows[0]
    assert row["merchant"].startswith("'=") and row["receipt_number"] == "'@cmd"
    assert row["tax_lines"].startswith("'+HST")
    assert (row["receipt_id"], row["date"], row["currency"]) == (saved["id"], "2026-10-07", "CAD")
    assert (row["subtotal"], row["tax_total"], row["total"], row["hst"]) == ("1092.53", "142.03", "1234.56", "142.03")
    assert row["gst"] == "" and row["category"] == saved["category"] and row["category_source"] == "AI suggestion"

    j = (await client.get("/api/receipts/export", params={"format": "json"})).json()
    assert j["count"] == 1 and j["receipts"][0]["total"] == "1234.56" and j["receipts"][0]["tax_lines"][0]["amount"] == "142.03"
    assert (await client.get("/api/receipts/export", params={"format": "xml"})).status_code == 422
    assert (await client.get("/api/receipts/export", params={"month": "2026-09"})).content.decode("utf-8-sig").count("\r\n") == 1  # header only
    assert (await client.get("/api/receipts/export", params={"category": "Nope"})).status_code == 422


async def test_summary_and_summary_exports(client, two_users, ai):
    await upgrade(client)
    for i, (cat, sub, tax, tot) in enumerate([("Office supplies", "100.00", "13.00", "113.00"),
                                              ("Office supplies", "50.00", "6.50", "56.50"),
                                              ("Tools and equipment", "10.00", "1.30", "11.30")]):
        await _saved(client, ai, 30 + i, category=cat, subtotal=sub, tax_total=tax, total=tot, receipt_date="2026-10-05",
                     tax_lines=[{"label": "HST", "amount": tax, "tax_type": "HST"}], line_items=[])
    await _saved(client, ai, 40, receipt_date="2026-09-05", total="9.00", subtotal="8.00", tax_total="1.00", line_items=[],
                 tax_lines=[])
    await _saved(client, ai, 41, receipt_date=None, total="9.00", subtotal="8.00", tax_total="1.00", line_items=[], tax_lines=[])
    s = (await client.get("/api/receipts/summary", params={"month": "2026-10"})).json()
    assert s["count"] == 3 and s["currency"] == "CAD" and s["undated_count"] == 1
    assert (s["subtotal"], s["tax_total"], s["total"]) == ("160.00", "20.80", "180.80")
    assert s["by_category"][0] == {"category": "Office supplies", "count": 2, "subtotal": "150.00", "tax_total": "19.50", "total": "169.50"}
    assert s["by_tax_type"]["HST"] == "20.80" and s["by_tax_type"]["GST"] == "0.00"
    assert "flagged_count" in s
    assert (await client.get("/api/receipts/summary", params={"month": "2026-13"})).status_code == 422
    pdf = await client.get("/api/receipts/export/summary", params={"month": "2026-10", "format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    c = await client.get("/api/receipts/export/summary", params={"month": "2026-10", "format": "csv"})
    assert "169.50" in c.text and "180.80" in c.text


async def test_email_to_accountant(client, two_users, ai, monkeypatch):
    await upgrade(client)
    await _saved(client, ai, 50, receipt_date="2026-10-05")
    r = await client.post("/api/receipts/export/email", json={"month": "2026-10"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "no_accountant_email"
    await client.put("/api/me", json={"accountant_email": "acct@example.com"})
    r = await client.post("/api/receipts/export/email", json={"month": "2026-10"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "email_not_configured"

    sent = []

    async def fake_send(msg, **kw):
        sent.append(msg)

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(mailer.aiosmtplib, "send", fake_send)
    r = await client.post("/api/receipts/export/email", json={"month": "2026-10"})
    assert r.status_code == 200 and r.json()["sent"] is True
    msg = sent[0]
    assert msg["To"] == "acct@example.com"
    assert {p.get_filename() for p in msg.iter_attachments()} == {"tradetrack-receipts-2026-10.csv", "tradetrack-summary-2026-10.pdf"}

    async def failing(msg, **kw):
        raise ConnectionError("smtp down")

    monkeypatch.setattr(mailer.aiosmtplib, "send", failing)
    r = await client.post("/api/receipts/export/email", json={"month": "2026-10"})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "email_send_failed"
    assert (await client.post("/api/receipts/export/email", json={"month": "bad"})).status_code == 422


async def test_pdf_escapes_user_text(client, two_users, ai):
    ai.response = {**GOOD_RECEIPT, "merchant": "<script>alert(1)</script> & Sons"}
    rec = await upload(client, png_bytes(60))
    r = await client.get(f"/api/receipts/{rec['id']}/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


# --------------------------------------------------------------------------- #
# Periods (quarter / year), province breakdown, accountant package
# --------------------------------------------------------------------------- #
async def _q3_data(client, ai):
    await _saved(client, ai, 60, receipt_date="2026-07-10", province="ON", subtotal="100.00", tax_total="13.00", total="113.00",
                 tax_lines=[{"label": "HST 13%", "amount": "13.00", "tax_type": "HST"}], line_items=[])
    await _saved(client, ai, 61, receipt_date="2026-09-20", province="BC", subtotal="100.00", tax_total="12.00", total="112.00",
                 tax_lines=[{"label": "GST 5%", "amount": "5.00", "tax_type": "GST"},
                            {"label": "PST 7%", "amount": "7.00", "tax_type": "PST"}], line_items=[])
    await _saved(client, ai, 62, receipt_date="2026-10-02", province="ON", subtotal="10.00", tax_total="1.30", total="11.30",
                 tax_lines=[{"label": "HST 13%", "amount": "1.30", "tax_type": "HST"}], line_items=[])


async def test_quarter_summary_by_province(client, two_users, ai):
    await upgrade(client)
    await _q3_data(client, ai)
    s = (await client.get("/api/receipts/summary", params={"date_from": "2026-07-01", "date_to": "2026-09-30"})).json()
    assert s["count"] == 2 and s["label"] == "2026-07-01 to 2026-09-30"
    assert (s["subtotal"], s["tax_total"], s["total"]) == ("200.00", "25.00", "225.00")
    assert s["by_tax_type"] == {"GST": "5.00", "HST": "13.00", "PST": "7.00", "QST": "0.00", "OTHER": "0.00"}
    by = {p["province"]: p for p in s["by_province"]}
    assert by["ON"]["tax"]["HST"] == "13.00" and by["ON"]["tax"]["GST"] == "0.00" and by["ON"]["count"] == 1
    assert by["BC"]["tax"]["GST"] == "5.00" and by["BC"]["tax"]["PST"] == "7.00" and by["BC"]["total"] == "112.00"
    # a plain month still works and keeps its label
    m = (await client.get("/api/receipts/summary", params={"month": "2026-10"})).json()
    assert m["label"] == "2026-10" and m["count"] == 1
    pdf = await client.get("/api/receipts/export/summary", params={"date_from": "2026-07-01", "date_to": "2026-09-30"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    csv_ = (await client.get("/api/receipts/export/summary",
                             params={"date_from": "2026-07-01", "date_to": "2026-09-30", "format": "csv"})).text
    assert "province,BC" in csv_ and "province_tax:BC,PST" in csv_


@pytest.mark.parametrize("params", [
    {"date_from": "2026-07-01"}, {"date_to": "2026-09-30"},
    {"date_from": "2026-09-30", "date_to": "2026-07-01"},
    {"date_from": "2026-01-01", "date_to": "2029-01-01"},
    {"month": "2026-10", "date_from": "2026-07-01", "date_to": "2026-09-30"},
    {"date_from": "nope", "date_to": "2026-09-30"},
])
async def test_invalid_periods_rejected(client, two_users, params):
    await upgrade(client)
    for url in ("/api/receipts/summary", "/api/receipts/export/summary", "/api/receipts/export/package"):
        r = await client.get(url, params=params)
        assert r.status_code == 422, (url, params, r.status_code)


async def test_accountant_package_contents_and_ownership(client, client2, two_users, ai):
    import zipfile

    await upgrade(client)
    await _q3_data(client, ai)
    # another user's receipt in the same period must never appear
    await upgrade(client2)
    await _saved(client2, ai, 70, receipt_date="2026-08-01", merchant="Someone Else Ltd", total="1.00", subtotal="1.00",
                 tax_total="0.00", tax_lines=[], line_items=[])
    r = await client.get("/api/receipts/export/package", params={"date_from": "2026-07-01", "date_to": "2026-09-30"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "tradetrack-accountant-package-2026-07-01_to_2026-09-30.zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert {"README.txt", "summary.pdf", "receipts.csv"} <= set(names)
    originals = [n for n in names if n.startswith("originals/")]
    assert len(originals) == 2 and all(n.endswith(".png") for n in originals)
    assert z.read("summary.pdf").startswith(b"%PDF")
    rows = list(csv.DictReader(io.StringIO(z.read("receipts.csv").decode("utf-8-sig"))))
    assert len(rows) == 2 and all("Someone Else" not in (x["merchant"] or "") for x in rows)
    assert {f"originals/{x['receipt_id']}.png" for x in rows} == set(originals)
    assert "deductible" in z.read("README.txt").decode()  # disclaimer travels with the package


async def test_package_free_plan_and_size_cap(client, two_users, ai, monkeypatch):
    from app import exports

    r = await client.get("/api/receipts/export/package")
    assert r.status_code == 402 and r.json()["detail"]["code"] == "premium_required"
    await upgrade(client)
    await _q3_data(client, ai)
    monkeypatch.setattr(exports, "MAX_PACKAGE_RECEIPTS", 1)
    r = await client.get("/api/receipts/export/package", params={"date_from": "2026-07-01", "date_to": "2026-09-30"})
    assert r.status_code == 413 and r.json()["detail"]["code"] == "package_too_large"


async def test_email_accepts_a_range(client, two_users, ai, monkeypatch):
    await upgrade(client)
    await _q3_data(client, ai)
    await client.put("/api/me", json={"accountant_email": "acct@example.com"})
    sent = []

    async def fake_send(msg, **kw):
        sent.append(msg)

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(mailer.aiosmtplib, "send", fake_send)
    r = await client.post("/api/receipts/export/email", json={"date_from": "2026-07-01", "date_to": "2026-09-30"})
    assert r.status_code == 200 and r.json()["receipts"] == 2
    assert {p.get_filename() for p in sent[0].iter_attachments()} == {
        "tradetrack-receipts-2026-07-01_to_2026-09-30.csv", "tradetrack-summary-2026-07-01_to_2026-09-30.pdf"}
    bad = await client.post("/api/receipts/export/email", json={"date_from": "2026-07-01"})
    assert bad.status_code == 422

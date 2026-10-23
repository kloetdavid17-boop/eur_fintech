import json

import pytest

from app import extraction
from app.config import settings

from .conftest import GOOD_RECEIPT, REAL_CALL_PROVIDER, image_pdf_bytes, jpeg_bytes, png_bytes, register, text_pdf_bytes, upload, upgrade


@pytest.fixture
async def user(client):
    return await register(client)


async def test_upload_png_extracts_and_is_needs_review(client, user, ai):
    r = await upload(client)
    assert r["id"].startswith("TT-") and len(r["id"].split("-")[2]) == 6
    assert r["processing_status"] == "NEEDS_REVIEW" and r["source"] == "UPLOAD"
    assert r["merchant"] == "Canadian Tire" and r["total"] == "113.00" and r["subtotal"] == "100.00"
    assert r["tax_lines"] == [{"label": "HST 13%", "amount": "13.00", "tax_type": "HST"}]
    assert r["category"] == "Tools and equipment" and r["category_is_ai_suggested"] is True
    assert r["receipt_date"] == "2026-10-06" and r["has_original_file"] is True
    assert r["extraction_confidence"] == "HIGH" and r["warnings"] == []
    assert ai.calls == 1


async def test_upload_jpeg_and_pdfs(client, user, ai):
    assert (await upload(client, jpeg_bytes(), "a.jpg", "image/jpeg"))["merchant"] == "Canadian Tire"
    assert (await upload(client, text_pdf_bytes(), "a.pdf", "application/pdf"))["file_mime_type"] == "application/pdf"
    assert (await upload(client, image_pdf_bytes(), "b.pdf", "application/pdf"))["merchant"] == "Canadian Tire"


async def test_pdf_text_layer_is_sent_as_text(client, user, monkeypatch):
    seen = []

    async def spy(doc):
        seen.append(doc)
        return json.dumps(GOOD_RECEIPT)

    monkeypatch.setattr(extraction, "call_provider", spy)
    await upload(client, text_pdf_bytes(), "t.pdf", "application/pdf")
    await upload(client, image_pdf_bytes(), "i.pdf", "application/pdf")
    await upload(client, png_bytes(3))
    assert [d.kind for d in seen] == ["pdf_text", "pdf_images", "image"]
    assert "Canadian Tire" in seen[0].text and seen[1].images and seen[2].images


async def test_magic_bytes_not_client_content_type(client, user, ai):
    r = await upload(client, b"just some text, not an image", "x.png", "image/png", expect=400)
    assert "Unsupported" in r["detail"]
    # a real PNG declared as text/plain is still accepted (type comes from the bytes)
    ok = await upload(client, png_bytes(5), "x.txt", "text/plain")
    assert ok["file_mime_type"] == "image/png"
    assert ai.calls == 1


async def test_corrupt_empty_oversize_rejected(client, user, ai, monkeypatch):
    await upload(client, b"", "e.png", expect=400)
    r = await upload(client, png_bytes()[:40], "c.png", expect=400)
    assert "corrupt" in r["detail"].lower()
    r = await upload(client, b"%PDF-1.4\nthis is not a real pdf", "c.pdf", "application/pdf", expect=400)
    assert "pdf" in r["detail"].lower()
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    await upload(client, png_bytes(), "big.png", expect=413)
    assert ai.calls == 0
    assert (await client.get("/api/receipts")).json()["total"] == 0  # nothing stored for bad files


async def test_ai_failure_422_keeps_failed_receipt_not_counted(client, user, ai):
    ai.response = extraction.ExtractionFailed("The AI service is busy right now. Please try again in a minute.")
    r = await client.post("/api/receipts/process", files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "extraction_failed" and d["receipt_id"]
    rec = (await client.get(f"/api/receipts/{d['receipt_id']}")).json()
    assert rec["processing_status"] == "FAILED" and rec["extraction_error"] and rec["has_original_file"]
    assert (await client.get("/api/receipts/usage")).json()["saved_this_period"] == 0
    # complete it by hand, then save
    p = await client.patch(f"/api/receipts/{rec['id']}", json={"merchant": "Local Hardware", "total": "20.00"})
    assert p.status_code == 200 and p.json()["processing_status"] == "NEEDS_REVIEW"
    assert (await client.post(f"/api/receipts/{rec['id']}/save")).status_code == 200
    # the same file again is not a duplicate of a FAILED one: it is simply retried / returned
    assert (await client.get("/api/receipts/usage")).json()["saved_this_period"] == 1


@pytest.mark.parametrize("bad", ["not json at all", "{broken", '{"merchant": NaN}', "[1,2]", ""])
async def test_malformed_ai_output_is_422_not_500(client, user, ai, bad):
    ai.response = bad
    r = await client.post("/api/receipts/process", files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "extraction_failed"


async def test_unexpected_provider_exception_is_422(client, user, ai):
    ai.response = RuntimeError("boom")
    r = await client.post("/api/receipts/process", files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 422


async def test_not_a_receipt_is_extraction_failed(client, user, ai):
    ai.response = {"is_receipt": False}
    r = await client.post("/api/receipts/process", files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 422


async def test_ai_not_configured_503_keeps_file(client, user, ai, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert (await client.get("/api/config")).json()["services"]["ai_configured"] is False
    r = await client.post("/api/receipts/process", files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 503
    d = r.json()["detail"]
    assert d["code"] == "ai_not_configured" and d["receipt_id"]
    assert ai.calls == 0
    rec = (await client.get(f"/api/receipts/{d['receipt_id']}")).json()
    assert rec["merchant"] is None and rec["total"] is None and rec["has_original_file"] is True
    assert (await client.get(f"/api/receipts/{rec['id']}/file")).status_code == 200


async def test_missing_unreadable_fields_stay_null(client, user, ai):
    ai.response = {"is_receipt": True, "merchant": "  ", "receipt_date": "06/10/2026", "currency": "dollars",
                   "subtotal": "abc", "total": "NaN", "tax_total": "Infinity", "category": "Pirate gold",
                   "tax_lines": [{"label": "Mystery fee", "amount": "1.00", "tax_type": "VAT"}, {"label": "HST", "amount": "oops"}],
                   "line_items": [{"description": "Thing", "amount": "1e999"}, {"amount": "3.00"}],
                   "province": "XX", "confidence": "HIGH"}
    r = await upload(client)
    assert r["merchant"] is None and r["receipt_date"] is None and r["subtotal"] is None and r["total"] is None
    assert r["category"] is None and r["category_is_ai_suggested"] is False and r["province"] is None
    assert r["currency"] == "CAD" and any(w["code"] == "currency_assumed" for w in r["warnings"])
    assert r["tax_lines"] == [{"label": "Mystery fee", "amount": "1.00", "tax_type": "OTHER"}]
    assert r["tax_total"] == "1.00"
    assert r["line_items"] == [{"description": "Thing", "quantity": None, "unit_price": None, "amount": None}]
    codes = {w["code"] for w in r["warnings"]}
    assert {"missing_merchant", "missing_date", "missing_total", "unclear_tax_type", "low_confidence"} <= codes
    assert r["extraction_confidence"] == "LOW"


async def test_floats_from_model_are_exact_decimals(client, user, ai):
    ai.response = '{"is_receipt": true, "merchant": "X", "subtotal": 0.1, "tax_total": 0.2, "total": 0.30, "confidence": "HIGH"}'
    r = await upload(client)
    assert (r["subtotal"], r["tax_total"], r["total"]) == ("0.10", "0.20", "0.30")


async def test_duplicate_upload_returns_existing_without_ai(client, user, ai):
    data = png_bytes(9)
    first = await upload(client, data)
    second = await upload(client, data, "other-name.png")
    assert second["id"] == first["id"] and second["processing_note"] and "already uploaded" in second["processing_note"]
    assert ai.calls == 1
    assert (await client.get("/api/receipts")).json()["total"] == 1
    assert (await client.get(f"/api/receipts/{first['id']}")).json()["processing_note"] is None


async def test_duplicates_are_per_user(client, client2, user, ai):
    data = png_bytes(11)
    a = await upload(client, data)
    await register(client2, "other@example.com")
    b = await upload(client2, data)
    assert a["id"] != b["id"] and ai.calls == 2


async def test_patch_updates_and_validates(client, user, ai):
    rec = await upload(client)
    url = f"/api/receipts/{rec['id']}"
    ok = await client.patch(url, json={"merchant": "Home Depot", "total": "120.50", "category": "Office supplies",
                                        "receipt_date": "2026-10-10", "id": "TT-HACK", "user_id": "x", "processing_status": "SAVED"})
    b = ok.json()
    assert ok.status_code == 200 and b["merchant"] == "Home Depot" and b["total"] == "120.50"
    assert b["category"] == "Office supplies" and b["category_is_ai_suggested"] is False
    assert b["id"] == rec["id"] and b["processing_status"] == "NEEDS_REVIEW"
    for payload, field in [({"receipt_date": "2026-13-45"}, "receipt_date"), ({"receipt_date": "yesterday"}, "receipt_date"),
                           ({"total": "twelve"}, "total"), ({"total": "-5"}, "total"), ({"subtotal": "1e999"}, "subtotal"),
                           ({"total": "NaN"}, "total"), ({"category": "Pirate gold"}, "category"), ({"province": "ZZ"}, "province"),
                           ({"currency": "dollar"}, "currency"), ({"receipt_time": "25:99"}, "receipt_time"),
                           ({"line_items": [{"description": ""}]}, "line_items"),
                           ({"tax_lines": [{"label": "HST", "amount": "x"}]}, "tax_lines")]:
        r = await client.patch(url, json=payload)
        assert r.status_code == 422, payload
        assert r.json()["detail"]["field"] == field, payload
    # a failed patch changes nothing
    assert (await client.get(url)).json()["merchant"] == "Home Depot"
    # clearing a field with null works
    assert (await client.patch(url, json={"receipt_number": None})).json()["receipt_number"] is None


async def test_ai_category_flag_clears_when_category_sent(client, user, ai):
    rec = await upload(client)
    assert rec["category_is_ai_suggested"] is True
    r = await client.patch(f"/api/receipts/{rec['id']}", json={"category": rec["category"]})
    assert r.json()["category_is_ai_suggested"] is False


async def test_warnings_totals_mismatch_and_province_rate(client, user, ai):
    rec = await upload(client)
    url = f"/api/receipts/{rec['id']}"
    r = (await client.patch(url, json={"total": "150.00"})).json()
    w = {x["code"]: x for x in r["warnings"]}
    assert "totals_mismatch" in w and w["totals_mismatch"]["severity"] == "warning"
    # amounts are untouched by warnings
    assert r["total"] == "150.00" and r["tax_total"] == "13.00"
    # within 0.02 tolerance -> no mismatch
    r = (await client.patch(url, json={"total": "113.02"})).json()
    assert "totals_mismatch" not in {x["code"] for x in r["warnings"]}
    # Ontario but 5% shown -> province hint warning, amount preserved
    r = (await client.patch(url, json={"tax_lines": [{"label": "GST", "amount": "5.00", "tax_type": "GST"}],
                                       "tax_total": "5.00", "total": "105.00"})).json()
    codes = {x["code"] for x in r["warnings"]}
    assert "tax_rate_differs" in codes and "tax_type_unexpected" in codes and r["tax_total"] == "5.00"
    # QC: GST+QST correct, no rate warning
    r = (await client.patch(url, json={"province": "QC", "tax_lines": [{"label": "TPS", "amount": "5.00", "tax_type": "GST"},
                                                                       {"label": "TVQ", "amount": "9.98", "tax_type": "QST"}],
                                       "tax_total": "14.98", "total": "114.98"})).json()
    assert "tax_rate_differs" not in {x["code"] for x in r["warnings"]}, r["warnings"]


async def test_warnings_line_items_future_and_old_dates(client, user, ai):
    rec = await upload(client)
    url = f"/api/receipts/{rec['id']}"
    r = (await client.patch(url, json={"line_items": [{"description": "A", "amount": "50.00"}, {"description": "B", "amount": "10.00"}]})).json()
    assert "line_items_mismatch" in {x["code"] for x in r["warnings"]}
    r = (await client.patch(url, json={"receipt_date": "2099-01-01"})).json()
    assert "future_date" in {x["code"] for x in r["warnings"]}
    r = (await client.patch(url, json={"receipt_date": "2015-01-01"})).json()
    assert "old_date" in {x["code"] for x in r["warnings"]}


async def test_save_requires_merchant_and_total(client, user, ai):
    ai.response = {"is_receipt": True, "merchant": "Shop", "confidence": "MEDIUM"}
    rec = await upload(client)
    r = await client.post(f"/api/receipts/{rec['id']}/save")
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "missing_required_fields" and d["fields"] == ["total"]
    await client.patch(f"/api/receipts/{rec['id']}", json={"total": "9.99"})
    assert (await client.post(f"/api/receipts/{rec['id']}/save")).status_code == 200
    # a saved receipt cannot lose its required fields
    r = await client.patch(f"/api/receipts/{rec['id']}", json={"merchant": None})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "missing_required_fields"


async def test_save_is_idempotent_and_counts_once(client, user, ai):
    rec = await upload(client)
    for _ in range(3):
        r = await client.post(f"/api/receipts/{rec['id']}/save")
        assert r.status_code == 200 and r.json()["processing_status"] == "SAVED" and r.json()["reviewed_at"]
    u = (await client.get("/api/receipts/usage")).json()
    assert u["saved_this_period"] == 1 and u["limit"] == 5 and u["remaining"] == 4 and u["plan"] == "FREE"
    assert u["period_label"] and u["resets_on"] and u["period_start"] < u["period_end"]


async def test_free_limit_enforced_on_sixth_save(client, user, ai):
    ids = [(await upload(client, png_bytes(100 + i)))["id"] for i in range(7)]
    for rid in ids[:5]:
        assert (await client.post(f"/api/receipts/{rid}/save")).status_code == 200
    r = await client.post(f"/api/receipts/{ids[5]}/save")
    assert r.status_code == 402
    d = r.json()["detail"]
    assert d["code"] == "free_limit_reached" and d["limit"] == 5 and d["used"] == 5 and d["period_end"] and d["message"]
    assert (await client.get(f"/api/receipts/{ids[5]}")).json()["processing_status"] == "NEEDS_REVIEW"
    # saving an already-saved one still works (idempotent, not blocked)
    assert (await client.post(f"/api/receipts/{ids[0]}/save")).status_code == 200
    # processing is not blocked by the limit, only saving
    assert (await client.get("/api/receipts/usage")).json()["remaining"] == 0


async def test_delete_does_not_refund_allowance(client, user, ai):
    ids = [(await upload(client, png_bytes(200 + i)))["id"] for i in range(7)]
    for rid in ids[:5]:
        await client.post(f"/api/receipts/{rid}/save")
    assert (await client.delete(f"/api/receipts/{ids[0]}")).status_code == 204
    assert (await client.get(f"/api/receipts/{ids[0]}")).status_code == 404
    assert (await client.post(f"/api/receipts/{ids[5]}/save")).status_code == 402
    assert (await client.get("/api/receipts/usage")).json()["saved_this_period"] == 5


async def test_unsaved_failed_and_duplicate_do_not_count(client, user, ai):
    data = png_bytes(300)
    await upload(client, data)
    await upload(client, data)  # duplicate
    ai.response = extraction.ExtractionFailed("x")
    await client.post("/api/receipts/process", files={"file": ("f.png", png_bytes(301), "image/png")})
    assert (await client.get("/api/receipts/usage")).json()["saved_this_period"] == 0


async def test_archive_unarchive_and_list_filters(client, user, ai):
    ai.response = {**GOOD_RECEIPT, "merchant": "Alpha_Tools 100%"}
    a = await upload(client, png_bytes(400))
    ai.response = {**GOOD_RECEIPT, "merchant": "Beta Lumber", "category": "Building materials and supplies"}
    b = await upload(client, png_bytes(401))
    await client.post(f"/api/receipts/{b['id']}/save")
    lst = (await client.get("/api/receipts")).json()
    assert lst["total"] == 2 and lst["items"][0]["id"] == b["id"]  # newest first
    assert (await client.get("/api/receipts", params={"q": "lumber"})).json()["total"] == 1
    assert (await client.get("/api/receipts", params={"q": "100%"})).json()["total"] == 1  # LIKE wildcards escaped
    assert (await client.get("/api/receipts", params={"q": "%"})).json()["total"] == 1
    assert (await client.get("/api/receipts", params={"category": "Building materials and supplies"})).json()["total"] == 1
    assert (await client.get("/api/receipts", params={"status": "SAVED"})).json()["total"] == 1
    assert (await client.get("/api/receipts", params={"status": "BOGUS"})).status_code == 422
    r = await client.post(f"/api/receipts/{b['id']}/archive")
    assert r.json()["processing_status"] == "ARCHIVED"
    assert (await client.get("/api/receipts")).json()["total"] == 1
    assert (await client.get("/api/receipts", params={"status": "ARCHIVED"})).json()["total"] == 1
    assert (await client.post(f"/api/receipts/{b['id']}/save")).status_code == 409
    assert (await client.post(f"/api/receipts/{b['id']}/unarchive")).json()["processing_status"] == "SAVED"
    assert (await client.get("/api/receipts/usage")).json()["saved_this_period"] == 1  # archive/unarchive never double counts
    assert a["id"]


async def test_file_and_pdf_downloads(client, user, ai):
    data = png_bytes(500)
    rec = await upload(client, data, "my receipt.png")
    f = await client.get(f"/api/receipts/{rec['id']}/file")
    assert f.status_code == 200 and f.content == data and f.headers["content-type"] == "image/png"
    assert f.headers["content-disposition"].startswith("inline") and "x-frame-options" not in f.headers
    p = await client.get(f"/api/receipts/{rec['id']}/pdf")
    assert p.status_code == 200 and p.content.startswith(b"%PDF") and p.headers["content-type"] == "application/pdf"


async def test_reprocess(client, user, ai):
    ai.response = extraction.ExtractionFailed("The AI service is busy.")
    r = await client.post("/api/receipts/process", files={"file": ("a.png", png_bytes(600), "image/png")})
    rid = r.json()["detail"]["receipt_id"]
    ai.response = dict(GOOD_RECEIPT)
    ok = await client.post(f"/api/receipts/{rid}/reprocess")
    assert ok.status_code == 200 and ok.json()["merchant"] == "Canadian Tire" and ok.json()["processing_status"] == "NEEDS_REVIEW"
    await client.post(f"/api/receipts/{rid}/save")
    assert (await client.post(f"/api/receipts/{rid}/reprocess")).status_code == 409


async def test_process_rate_limited(client, user, ai, monkeypatch):
    monkeypatch.setattr(settings, "process_max_per_minute", 2)
    await upload(client, png_bytes(700))
    await upload(client, png_bytes(701))
    await upload(client, png_bytes(702), expect=429)


async def test_openai_error_mapping(monkeypatch):
    import httpx
    import openai

    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

    class Boom:
        def __init__(self, exc):
            self.exc = exc
            self.chat = self
            self.completions = self

        async def create(self, **kw):
            raise self.exc

    doc = extraction.PreparedDocument("text", text="x")
    for exc in [openai.APITimeoutError(request=req),
                openai.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None),
                openai.APIConnectionError(request=req),
                openai.InternalServerError("oops", response=httpx.Response(500, request=req), body=None)]:
        monkeypatch.setattr(extraction, "_get_client", lambda e=exc: Boom(e))
        with pytest.raises(extraction.ExtractionFailed):
            await REAL_CALL_PROVIDER(doc)

"""Premium exports, the period summary (month, quarter, year) and the accountant ZIP.

Everything here is derived directly from the stored receipt rows: amounts, dates, tax lines and
categories are written exactly as stored (money as 2-decimal strings). Summary totals use
``Decimal`` and are rounded to cents only for display.
"""

import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from app.models import Receipt, as_utc, money_str, receipt_to_out
from app.plans import PERIOD_TZ
from app.tax import TAX_TYPES

CENT = Decimal("0.01")
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")


def month_range(month: str) -> tuple[date, date]:
    """First day and last day (inclusive) of 'YYYY-MM'. Raises ValueError."""
    m = _MONTH_RE.match(month or "")
    if not m:
        raise ValueError("month must look like 2026-10")
    y, mo = int(m.group(1)), int(m.group(2))
    start = date(y, mo, 1)
    nxt = date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)
    return start, date.fromordinal(nxt.toordinal() - 1)


def resolve_period(month: str | None, date_from: date | None, date_to: date | None, today: date) -> tuple[date, date, str]:
    """(start, end inclusive, label) for a month OR a custom range. Raises ValueError.

    A range is how quarters and years are requested (the client turns "Q3 2026" into
    2026-07-01..2026-09-30). The label is ``YYYY-MM`` for a month, else ``start to end``."""
    if date_from or date_to:
        if month:
            raise ValueError("send either month or date_from/date_to, not both")
        if not (date_from and date_to):
            raise ValueError("date_from and date_to must be sent together")
        if date_from > date_to:
            raise ValueError("date_from must not be after date_to")
        if (date_to - date_from).days > 731:
            raise ValueError("a summary can cover at most two years")
        return date_from, date_to, f"{date_from.isoformat()} to {date_to.isoformat()}"
    month = month or f"{today.year:04d}-{today.month:02d}"
    start, end = month_range(month)
    return start, end, month


def safe_cell(value) -> str:
    """Neutralise CSV/spreadsheet formula injection in TEXT cells."""
    if value is None:
        return ""
    s = str(value)
    return "'" + s if s.startswith(_FORMULA_CHARS) else s


def _tax_by_type(r: Receipt) -> dict[str, Decimal]:
    out = {t: Decimal("0") for t in TAX_TYPES}
    for t in r.tax_lines or []:
        out[t.get("tax_type") if t.get("tax_type") in out else "OTHER"] += Decimal(t["amount"])
    return out


# --------------------------------------------------------------------------- #
# Receipts export
# --------------------------------------------------------------------------- #
CSV_COLUMNS = [
    "receipt_id", "date", "time", "merchant", "receipt_number", "category", "category_source",
    "currency", "subtotal", "discounts", "tax_total", "total",
    "gst", "hst", "pst", "qst", "other_tax", "tax_lines", "province", "source", "status",
    "reviewed_at", "notes",
]


def receipts_csv(receipts: list[Receipt]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for r in receipts:
        by_type = _tax_by_type(r)
        has = lambda t: money_str(by_type[t]) if any(x.get("tax_type") == t for x in (r.tax_lines or [])) else ""  # noqa: E731
        w.writerow([
            r.id,
            r.receipt_date.isoformat() if r.receipt_date else "",
            r.receipt_time or "",
            safe_cell(r.merchant),
            safe_cell(r.receipt_number),
            safe_cell(r.category),
            "" if r.category is None else ("AI suggestion" if r.category_is_ai_suggested else "chosen by owner"),
            r.currency,
            money_str(r.subtotal) or "",
            money_str(r.discounts) or "",
            money_str(r.tax_total) or "",
            money_str(r.total) or "",
            has("GST"), has("HST"), has("PST"), has("QST"), has("OTHER"),
            safe_cell("; ".join(f"{t['label']}: {t['amount']}" for t in (r.tax_lines or []))),
            r.province or "",
            r.source,
            r.processing_status,
            as_utc(r.reviewed_at).isoformat() if r.reviewed_at else "",
            safe_cell(r.notes),
        ])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel reads accents correctly


def receipts_json(receipts: list[Receipt]) -> bytes:
    payload = {
        "exported_at": datetime.now(PERIOD_TZ).astimezone().isoformat(),
        "count": len(receipts),
        "receipts": [receipt_to_out(r).model_dump(mode="json") for r in receipts],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------------- #
# Period summary
# --------------------------------------------------------------------------- #
def build_summary(month: str, saved: list[Receipt]) -> dict:
    start, end = month_range(month)
    return build_period_summary(start, end, month, saved)


def build_period_summary(start: date, end: date, label: str, saved: list[Receipt]) -> dict:
    """``saved`` = the owner's SAVED receipts (any date). Receipts are placed by their receipt
    date; undated ones are only counted (``undated_count``) when they were saved inside the
    period. Non-CAD receipts are not added to CAD totals (``other_currency_count``)."""
    included: list[Receipt] = []
    undated = other_currency = 0
    for r in saved:
        if r.receipt_date is None:
            saved_at = as_utc(r.reviewed_at or r.created_at).astimezone(PERIOD_TZ).date()
            if start <= saved_at <= end:
                undated += 1
            continue
        if not (start <= r.receipt_date <= end):
            continue
        if r.currency != "CAD":
            other_currency += 1
            continue
        included.append(r)

    zero = Decimal("0")
    tot = {"subtotal": zero, "tax_total": zero, "total": zero}
    cats: dict[str, dict] = defaultdict(lambda: {"count": 0, "subtotal": zero, "tax_total": zero, "total": zero})
    by_type = {t: zero for t in TAX_TYPES}
    provs: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "subtotal": zero, "tax_total": zero, "total": zero, "tax": {t: zero for t in TAX_TYPES}}
    )
    flagged = 0
    for r in included:
        pv = provs[r.province or "Unknown"]
        pv["count"] += 1
        for f in ("subtotal", "tax_total", "total"):
            pv[f] += getattr(r, f) or zero
        for t, v in _tax_by_type(r).items():
            pv["tax"][t] += v
        key = r.category or "Uncategorized"
        c = cats[key]
        c["count"] += 1
        for f in ("subtotal", "tax_total", "total"):
            v = getattr(r, f) or zero
            c[f] += v
            tot[f] += v
        for t, v in _tax_by_type(r).items():
            by_type[t] += v
        if any(w.get("severity") == "warning" for w in (r.warnings or [])):
            flagged += 1

    q = lambda d: f"{d.quantize(CENT):.2f}"  # noqa: E731
    return {
        "month": start.strftime("%Y-%m"),  # first month of the period (kept for older clients)
        "label": label,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "currency": "CAD",
        "count": len(included),
        "undated_count": undated,
        "other_currency_count": other_currency,
        "subtotal": q(tot["subtotal"]),
        "tax_total": q(tot["tax_total"]),
        "total": q(tot["total"]),
        "by_category": sorted(
            (
                {"category": k, "count": v["count"], "subtotal": q(v["subtotal"]),
                 "tax_total": q(v["tax_total"]), "total": q(v["total"])}
                for k, v in cats.items()
            ),
            key=lambda x: (-Decimal(x["total"]), x["category"]),
        ),
        "by_tax_type": {t: q(v) for t, v in by_type.items()},
        "by_province": sorted(
            (
                {"province": k, "count": v["count"], "subtotal": q(v["subtotal"]), "tax_total": q(v["tax_total"]),
                 "total": q(v["total"]), "tax": {t: q(a) for t, a in v["tax"].items()}}
                for k, v in provs.items()
            ),
            key=lambda x: (x["province"] == "Unknown", x["province"]),
        ),
        "flagged_count": flagged,
    }


def summary_csv(summary: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["section", "name", "count", "subtotal", "tax_total", "total"])
    for c in summary["by_category"]:
        w.writerow(["category", safe_cell(c["category"]), c["count"], c["subtotal"], c["tax_total"], c["total"]])
    for t, amount in summary["by_tax_type"].items():
        w.writerow(["tax_type", t, "", "", amount, ""])
    for p in summary.get("by_province", []):
        w.writerow(["province", p["province"], p["count"], p["subtotal"], p["tax_total"], p["total"]])
        for t, amount in p["tax"].items():
            if Decimal(amount):
                w.writerow([f"province_tax:{p['province']}", t, "", "", amount, ""])
    w.writerow(["total", summary.get("label", summary["month"]), summary["count"], summary["subtotal"], summary["tax_total"], summary["total"]])
    return ("﻿" + buf.getvalue()).encode("utf-8")


# --------------------------------------------------------------------------- #
# Accountant package (ZIP): summary PDF + receipts CSV + the original files
# --------------------------------------------------------------------------- #
MAX_PACKAGE_RECEIPTS = 300
MAX_PACKAGE_BYTES = 40 * 1024 * 1024
_MIME_EXT = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"}

PACKAGE_README = """TradeTrack accountant package

summary.pdf     Expense summary for the period, by category, tax type and province.
receipts.csv    One row per saved receipt, exactly as stored (amounts, tax lines, category, warnings-free values).
originals/      The original uploaded file for each receipt, named by receipt ID (column receipt_id in the CSV).

Notes
- Amounts and tax are what the receipts show. Categories may be AI suggestions chosen or confirmed by the owner.
- TradeTrack does not provide tax advice. Whether an expense is deductible or tax is recoverable is for the
  owner and their accountant to decide.
- Receipts saved without a file (for example sample data) have no entry in originals/.
"""


def original_name(r: Receipt) -> str:
    ext = _MIME_EXT.get(r.file_mime_type or "")
    if not ext and r.original_filename and "." in r.original_filename:
        tail = r.original_filename.rsplit(".", 1)[1].lower()
        ext = tail if tail.isalnum() and len(tail) <= 5 else None
    return f"originals/{r.id}.{ext or 'bin'}"


def build_package(summary_pdf: bytes, csv_bytes: bytes, originals: dict[str, bytes]) -> bytes:
    """``originals`` maps archive path -> bytes. Pure function so it is easy to test."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", PACKAGE_README)
        z.writestr("summary.pdf", summary_pdf)
        z.writestr("receipts.csv", csv_bytes)
        for name, data in originals.items():
            z.writestr(name, data)
    return buf.getvalue()

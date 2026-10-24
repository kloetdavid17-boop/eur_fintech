"""Pure-Python PDF rendering: HTML (Jinja2, autoescape ON) -> PDF via xhtml2pdf.

No native libraries are needed. Two documents:
* a per-receipt TradeTrack PDF (all plans),
* a monthly expense summary PDF (Premium).
All user-provided text is escaped by Jinja's autoescape.
"""

import io
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models import Receipt, receipt_to_out

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html"]),
)


def _pdf_from_html(html: str) -> bytes:
    # Imported lazily so importing this module stays cheap.
    from xhtml2pdf import pisa

    out = io.BytesIO()
    result = pisa.CreatePDF(src=html, dest=out, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF rendering failed ({result.err} error(s))")
    return out.getvalue()


def render_receipt_pdf(receipt: Receipt) -> bytes:
    o = receipt_to_out(receipt)
    html = _env.get_template("receipt.html").render(
        receipt_id=o.id,
        merchant=o.merchant,
        receipt_date=o.receipt_date,
        receipt_time=o.receipt_time,
        receipt_number=o.receipt_number,
        province=o.province,
        status=o.processing_status.replace("_", " ").title(),
        source=o.source.title(),
        is_sample=o.is_sample,
        category=o.category,
        ai_suggested=o.category_is_ai_suggested,
        currency=o.currency,
        line_items=[li.model_dump() for li in o.line_items],
        subtotal=o.subtotal,
        discounts=o.discounts,
        tax_lines=[t.model_dump() for t in o.tax_lines],
        tax_total=o.tax_total,
        total=o.total,
        warnings=[w.model_dump() for w in o.warnings],
        notes=o.notes,
    )
    return _pdf_from_html(html)


def render_summary_pdf(summary: dict, receipts: list[Receipt], business: str) -> bytes:
    label = summary.get("label") or summary["month"]
    if len(label) == 7:  # a single month, YYYY-MM
        y, m = label.split("-")
        month_label = date(int(y), int(m), 1).strftime("%B %Y")
    else:  # a custom range such as a quarter or a year
        month_label = label
    rows = [
        {
            "date": r.receipt_date.isoformat() if r.receipt_date else "",
            "merchant": r.merchant or "",
            "category": r.category or "Uncategorized",
            "tax_total": f"{r.tax_total:.2f}" if r.tax_total is not None else "n/a",
            "total": f"{r.total:.2f}" if r.total is not None else "n/a",
        }
        for r in sorted(receipts, key=lambda x: (x.receipt_date or date.min, x.id))
    ]
    html = _env.get_template("summary.html").render(
        summary=summary, month_label=month_label, business=business, receipts=rows
    )
    return _pdf_from_html(html)


def receipt_filename(receipt: Receipt, ext: str) -> str:
    return f"tradetrack-{receipt.id}.{ext}"  # ids are filesystem-safe (TT-2026-A1B2C3)


def download_headers(filename: str, *, inline: bool = False) -> dict:
    """Attachment headers. ``no-store``: exports are private and rendered from current data."""
    disposition = "inline" if inline else "attachment"
    return {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }

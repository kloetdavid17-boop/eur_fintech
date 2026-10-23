"""Parsing, validation and warnings for receipt data.

Everything numeric goes through ``Decimal`` with explicit rounding (to cents, ROUND_HALF_UP);
floats are never used for arithmetic. Non-finite values (NaN, Infinity) are rejected.

Warnings are *checks that ask the user to double-check*. They never block saving (the only
hard requirement on save is merchant + total) and they never change any amount. The province
table in ``tax.py`` is used only to word a warning, never to compute or overwrite a value.
"""

import math
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.models import EXPENSE_CATEGORIES, Receipt, ReceiptUpdate
from app.plans import PERIOD_TZ
from app.tax import PROVINCE_BY_CODE, PROVINCE_CODES, TAX_TYPES, infer_tax_type

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.02")          # allowed rounding difference when comparing sums
MAX_AMOUNT = Decimal("9999999.99")   # fits Numeric(10, 2)
RATE_TOLERANCE = Decimal("0.005")    # 0.5 percentage points
MAX_LINE_ITEMS = 100
MAX_TAX_LINES = 10

_CATEGORY_LOOKUP = {c.lower(): c for c in EXPENSE_CATEGORIES}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class FieldError(ValueError):
    """A user-supplied value is invalid; ``field`` names the offending field."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Primitive parsers
# --------------------------------------------------------------------------- #
def parse_money(value, *, allow_negative: bool = False) -> Decimal | None:
    """Return a Decimal rounded to cents, or None for empty. Raises ValueError if invalid."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("not a finite number")
        d = Decimal(str(value))
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        negative = s.startswith("(") and s.endswith(")")
        s = re.sub(r"(?i)\b(cad|usd|cdn)\b|[$\s()]", "", s)
        if negative:
            s = "-" + s
        if "," in s and "." in s:
            s = s.replace(",", "")
        elif "," in s:
            if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):
                s = s.replace(",", "")
            elif re.fullmatch(r"-?\d+,\d{1,2}", s):
                s = s.replace(",", ".")
            else:
                raise ValueError("not a number")
        if not re.fullmatch(r"-?\d+(\.\d+)?", s):
            raise ValueError("not a number")
        try:
            d = Decimal(s)
        except InvalidOperation as exc:
            raise ValueError("not a number") from exc
    else:
        raise ValueError("not a number")
    if not d.is_finite():
        raise ValueError("not a finite number")
    d = cents(d)
    if d < 0 and not allow_negative:
        raise ValueError("must not be negative")
    if abs(d) > MAX_AMOUNT:
        raise ValueError("amount is too large")
    return d


def parse_quantity(value) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("not a number")
    try:
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("not a finite number")
            d = Decimal(str(value))
        else:
            d = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("not a number") from exc
    if not d.is_finite() or d < 0 or d > Decimal("100000"):
        raise ValueError("quantity out of range")
    d = d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP).normalize()
    return format(d, "f")


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    if not _DATE_RE.fullmatch(s):
        raise ValueError("expected YYYY-MM-DD")
    try:
        d = date.fromisoformat(s)
    except ValueError as exc:
        raise ValueError("not a real calendar date") from exc
    if d.year < 1900:
        raise ValueError("date is too old")
    return d


def parse_time(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if len(s) >= 5 and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d:[0-5]\d", s):
        s = s[:5]
    if not _TIME_RE.fullmatch(s):
        raise ValueError("expected HH:MM")
    return s


def _clean_text(value, max_len: int) -> str | None:
    if value is None:
        return None
    s = " ".join(str(value).split())  # collapse whitespace/newlines
    return s[:max_len] or None


def clean_text(value, max_len: int) -> str | None:
    return _clean_text(value, max_len)


def category_or_none(value) -> str | None:
    if not isinstance(value, str):
        return None
    return _CATEGORY_LOOKUP.get(value.strip().lower())


# --------------------------------------------------------------------------- #
# Line items / tax lines (strict for users, lenient for AI output)
# --------------------------------------------------------------------------- #
def normalize_line_items(items, *, strict: bool) -> list[dict]:
    out: list[dict] = []
    if not isinstance(items, list):
        if strict and items is not None:
            raise FieldError("line_items", "line_items must be a list")
        return out
    if strict and len(items) > MAX_LINE_ITEMS:
        raise FieldError("line_items", f"At most {MAX_LINE_ITEMS} line items are allowed")
    for i, raw in enumerate(items[:MAX_LINE_ITEMS], start=1):
        if not isinstance(raw, dict):
            if strict:
                raise FieldError("line_items", f"Line item {i} is not an object")
            continue
        description = _clean_text(raw.get("description"), 200)
        if not description:
            if strict:
                raise FieldError("line_items", f"Line item {i} needs a description")
            continue
        item = {"description": description, "quantity": None, "unit_price": None, "amount": None}
        for key, parser in (
            ("quantity", parse_quantity),
            ("unit_price", lambda v: parse_money(v, allow_negative=True)),
            ("amount", lambda v: parse_money(v, allow_negative=True)),
        ):
            try:
                val = parser(raw.get(key))
            except ValueError as exc:
                if strict:
                    raise FieldError("line_items", f"Line item {i}: invalid {key} ({exc})") from exc
                val = None  # unreadable -> unavailable, never guessed
            item[key] = None if val is None else (val if key == "quantity" else f"{val:.2f}")
        out.append(item)
    return out


def normalize_tax_lines(items, *, strict: bool) -> list[dict]:
    out: list[dict] = []
    if not isinstance(items, list):
        if strict and items is not None:
            raise FieldError("tax_lines", "tax_lines must be a list")
        return out
    if strict and len(items) > MAX_TAX_LINES:
        raise FieldError("tax_lines", f"At most {MAX_TAX_LINES} tax lines are allowed")
    for i, raw in enumerate(items[:MAX_TAX_LINES], start=1):
        if not isinstance(raw, dict):
            if strict:
                raise FieldError("tax_lines", f"Tax line {i} is not an object")
            continue
        try:
            amount = parse_money(raw.get("amount"))
        except ValueError as exc:
            if strict:
                raise FieldError("tax_lines", f"Tax line {i}: invalid amount ({exc})") from exc
            amount = None
        if amount is None:
            if strict:
                raise FieldError("tax_lines", f"Tax line {i} needs an amount")
            continue
        label = _clean_text(raw.get("label"), 60)
        tax_type = raw.get("tax_type")
        tax_type = tax_type.strip().upper() if isinstance(tax_type, str) else None
        if tax_type not in TAX_TYPES:
            if strict and tax_type:
                raise FieldError("tax_lines", f"Tax line {i}: tax_type must be one of {', '.join(TAX_TYPES)}")
            tax_type = infer_tax_type(label)
        if not label:
            label = tax_type if tax_type != "OTHER" else "Tax"
        out.append({"label": label, "amount": f"{amount:.2f}", "tax_type": tax_type})
    return out


def tax_lines_sum(tax_lines: list[dict]) -> Decimal | None:
    if not tax_lines:
        return None
    return cents(sum((Decimal(t["amount"]) for t in tax_lines), Decimal("0")))


# --------------------------------------------------------------------------- #
# PATCH
# --------------------------------------------------------------------------- #
def apply_patch(r: Receipt, patch: ReceiptUpdate) -> set[str]:
    """Apply the fields the client actually sent. Raises FieldError on the first bad value.
    Returns the set of field names that were applied."""
    sent = patch.model_fields_set
    applied: set[str] = set()

    def money(field: str):
        try:
            return parse_money(getattr(patch, field))
        except ValueError as exc:
            raise FieldError(field, f"{field.replace('_', ' ').capitalize()} is not a valid amount ({exc})") from exc

    if "merchant" in sent:
        r.merchant = _clean_text(patch.merchant, 120)
        applied.add("merchant")
    if "receipt_date" in sent:
        try:
            r.receipt_date = parse_date(patch.receipt_date)
        except ValueError as exc:
            raise FieldError("receipt_date", f"Date must be a valid YYYY-MM-DD date ({exc})") from exc
        applied.add("receipt_date")
    if "receipt_time" in sent:
        try:
            r.receipt_time = parse_time(patch.receipt_time)
        except ValueError as exc:
            raise FieldError("receipt_time", f"Time must be HH:MM ({exc})") from exc
        applied.add("receipt_time")
    if "currency" in sent:
        cur = (patch.currency or "").strip().upper()
        if not _CURRENCY_RE.fullmatch(cur):
            raise FieldError("currency", "Currency must be a 3-letter code such as CAD")
        r.currency = cur
        applied.add("currency")
    if "receipt_number" in sent:
        r.receipt_number = _clean_text(patch.receipt_number, 60)
        applied.add("receipt_number")
    if "line_items" in sent:
        r.line_items = normalize_line_items(patch.line_items or [], strict=True)
        applied.add("line_items")
    if "tax_lines" in sent:
        r.tax_lines = normalize_tax_lines(patch.tax_lines or [], strict=True)
        applied.add("tax_lines")
    for field in ("discounts", "subtotal", "tax_total", "total"):
        if field in sent:
            setattr(r, field, money(field))
            applied.add(field)
    if "tax_lines" in applied and "tax_total" not in sent and r.tax_total is None:
        r.tax_total = tax_lines_sum(r.tax_lines)  # plain sum of the printed tax lines
    if "province" in sent:
        prov = (patch.province or "").strip().upper() or None
        if prov is not None and prov not in PROVINCE_CODES:
            raise FieldError("province", "Province must be a two-letter Canadian province or territory code")
        r.province = prov
        applied.add("province")
    if "category" in sent:
        if patch.category is None or not patch.category.strip():
            r.category = None
        else:
            cat = _CATEGORY_LOOKUP.get(patch.category.strip().lower())
            if cat is None:
                raise FieldError("category", "Category must be one of the listed expense categories")
            r.category = cat
        r.category_is_ai_suggested = False  # the owner has decided
        applied.add("category")
    if "notes" in sent:
        notes = (patch.notes or "").strip()
        if len(notes) > 2000:
            raise FieldError("notes", "Notes can be at most 2000 characters")
        r.notes = notes or None
        applied.add("notes")
    return applied


def missing_required(r: Receipt) -> list[str]:
    missing = []
    if not (r.merchant and r.merchant.strip()):
        missing.append("merchant")
    if r.total is None:
        missing.append("total")
    return missing


# --------------------------------------------------------------------------- #
# Warnings
# --------------------------------------------------------------------------- #
STICKY_WARNING_CODES = {"currency_assumed"}


def _w(code: str, severity: str, field: str | None, message: str) -> dict:
    return {"code": code, "severity": severity, "field": field, "message": message}


def compute_warnings(r: Receipt, *, default_province: str | None = None, today: date | None = None) -> list[dict]:
    """Server-side checks on the current receipt data. Pure: does not change the receipt."""
    today = today or datetime.now(PERIOD_TZ).date()
    out: list[dict] = []

    if not (r.merchant and r.merchant.strip()):
        out.append(_w("missing_merchant", "warning", "merchant", "Merchant was not found. Please enter it."))
    if r.receipt_date is None:
        out.append(_w("missing_date", "warning", "receipt_date", "Date was not found. Please enter it."))
    else:
        if r.receipt_date > today + timedelta(days=1):
            out.append(_w("future_date", "warning", "receipt_date", "This date is in the future. Please check it."))
        elif r.receipt_date < today - timedelta(days=730):
            out.append(_w("old_date", "info", "receipt_date", "This receipt is more than two years old. Please check the date."))
    if r.total is None:
        out.append(_w("missing_total", "warning", "total", "Total was not found. Please enter it."))
    if r.currency and r.currency != "CAD":
        out.append(_w("non_cad_currency", "info", "currency",
                      f"Amounts are in {r.currency}. TradeTrack does not convert currencies."))

    lines = r.line_items or []
    tax_lines = r.tax_lines or []
    tl_sum = tax_lines_sum(tax_lines)
    tax = r.tax_total if r.tax_total is not None else tl_sum
    disc = r.discounts or Decimal("0")

    # Line items vs subtotal
    amounts = [Decimal(li["amount"]) for li in lines if li.get("amount") is not None]
    if lines and len(amounts) == len(lines):
        items_sum = cents(sum(amounts, Decimal("0")))
        reference = r.subtotal
        if reference is None and r.total is not None and tax is not None:
            reference = r.total - tax
        if reference is not None and abs(items_sum - reference) > TOLERANCE and \
                abs(items_sum - disc - reference) > TOLERANCE:
            out.append(_w("line_items_mismatch", "warning", "line_items",
                          f"Line items add up to {items_sum:.2f}, which differs from the subtotal "
                          f"({reference:.2f}). Please check the line items."))

    # Tax lines vs tax total
    if r.tax_total is not None and tl_sum is not None and abs(tl_sum - r.tax_total) > TOLERANCE:
        out.append(_w("tax_lines_mismatch", "warning", "tax_lines",
                      f"Tax lines add up to {tl_sum:.2f} but the tax total is {r.tax_total:.2f}."))

    # Subtotal + tax vs total
    if r.subtotal is not None and r.total is not None:
        if tax is not None:
            ok = abs(r.subtotal + tax - r.total) <= TOLERANCE or abs(r.subtotal - disc + tax - r.total) <= TOLERANCE
            if not ok:
                out.append(_w("totals_mismatch", "warning", "total",
                              f"Subtotal ({r.subtotal:.2f}) + tax ({tax:.2f}) = {cents(r.subtotal + tax):.2f}, "
                              f"which differs from the total ({r.total:.2f}). Please check the amounts."))
        elif abs(r.total - r.subtotal) > TOLERANCE:
            out.append(_w("tax_unclear", "warning", "tax_total",
                          "The total is higher than the subtotal but no tax amount was read. "
                          "Please check the tax."))

    # Tax type clarity
    if any(t.get("tax_type") == "OTHER" for t in tax_lines):
        out.append(_w("unclear_tax_type", "warning", "tax_lines",
                      "A tax line could not be identified as GST, HST, PST or QST. Please check its type."))

    # Typical province rate (hint only; never changes amounts)
    code = r.province or default_province
    prov = PROVINCE_BY_CODE.get(code or "")
    if prov and r.subtotal is not None and r.subtotal > 0 and tax is not None:
        implied = tax / r.subtotal
        if abs(implied - prov.typical_rate) > RATE_TOLERANCE:
            note = "" if r.province else f" (compared with your default province, {prov.name})"
            out.append(_w("tax_rate_differs", "info", "tax_total",
                          f"The tax on this receipt is {implied * 100:.1f}% of the subtotal; the typical rate in "
                          f"{prov.name} is {prov.tax_hint}{note}. Some items are zero-rated or exempt, so this may "
                          f"be correct. Please check."))
        used = {t["tax_type"] for t in tax_lines if t.get("tax_type") != "OTHER"}
        if used and not used.issubset(set(prov.expected_types)):
            out.append(_w("tax_type_unexpected", "info", "tax_lines",
                          f"{', '.join(sorted(used))} is not the usual tax for {prov.name} ({prov.tax_hint}). "
                          f"The receipt may be from another province."))

    if r.extraction_confidence == "LOW":
        out.append(_w("low_confidence", "warning", None,
                      "The AI had low confidence reading this receipt. Please check every field."))
    return out


def refresh_warnings(r: Receipt, *, default_province: str | None, keep_sticky: bool = True) -> None:
    sticky = [w for w in (r.warnings or []) if keep_sticky and w.get("code") in STICKY_WARNING_CODES]
    r.warnings = sticky + compute_warnings(r, default_province=default_province)

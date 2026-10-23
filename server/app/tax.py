"""Canadian tax reference data.

This table is a REFERENCE ONLY. It is used to (a) show a hint in the UI and (b) produce
a *warning* when the tax printed on a receipt differs from the province's typical rate.
It is never used to compute, fill in or overwrite amounts: tax amounts are always the
ones shown on the receipt (or typed by the user). Adding a province or changing a rate
means editing this one table.

Rates are the general rates in effect in 2026 and are hints, not tax advice. Many
purchases are zero-rated or exempt, some businesses are not registered, and a receipt
can legitimately differ from the typical rate.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Province:
    code: str
    name: str
    tax_hint: str
    # Typical combined rate on the pre-tax amount and the tax types expected on a receipt.
    typical_rate: Decimal
    expected_types: tuple[str, ...]


def _p(code: str, name: str, hint: str, rate: str, *types: str) -> Province:
    return Province(code, name, hint, Decimal(rate), tuple(types))


PROVINCES: list[Province] = [
    _p("AB", "Alberta", "GST 5%", "0.05", "GST"),
    _p("BC", "British Columbia", "GST 5% + PST 7%", "0.12", "GST", "PST"),
    _p("MB", "Manitoba", "GST 5% + PST 7%", "0.12", "GST", "PST"),
    _p("NB", "New Brunswick", "HST 15%", "0.15", "HST"),
    _p("NL", "Newfoundland and Labrador", "HST 15%", "0.15", "HST"),
    _p("NS", "Nova Scotia", "HST 14%", "0.14", "HST"),
    _p("NT", "Northwest Territories", "GST 5%", "0.05", "GST"),
    _p("NU", "Nunavut", "GST 5%", "0.05", "GST"),
    _p("ON", "Ontario", "HST 13%", "0.13", "HST"),
    _p("PE", "Prince Edward Island", "HST 15%", "0.15", "HST"),
    _p("QC", "Quebec", "GST 5% + QST 9.975%", "0.14975", "GST", "QST"),
    _p("SK", "Saskatchewan", "GST 5% + PST 6%", "0.11", "GST", "PST"),
    _p("YT", "Yukon", "GST 5%", "0.05", "GST"),
]

PROVINCE_BY_CODE = {p.code: p for p in PROVINCES}
PROVINCE_CODES = set(PROVINCE_BY_CODE)
TAX_TYPES = ("GST", "HST", "PST", "QST", "OTHER")

# Labels commonly printed on receipts -> tax type (used only to read a label, not to compute).
_LABEL_HINTS = {
    "GST": "GST", "TPS": "GST",
    "HST": "HST", "TVH": "HST",
    "PST": "PST", "RST": "PST",
    "QST": "QST", "TVQ": "QST",
}


def province_list() -> list[dict]:
    return [{"code": p.code, "name": p.name, "tax_hint": p.tax_hint} for p in PROVINCES]


def infer_tax_type(label: str | None) -> str:
    """Read a tax type from the label printed on the receipt; 'OTHER' when unclear."""
    if not label:
        return "OTHER"
    tokens = "".join(c if c.isalnum() else " " for c in label.upper()).split()
    found = {_LABEL_HINTS[t] for t in tokens if t in _LABEL_HINTS}
    return found.pop() if len(found) == 1 else "OTHER"

# Canadian tax model

## Principles
- **Amounts are as printed on the receipt.** Tax lines are stored per receipt (`label`, `amount`,
  `tax_type` = GST / HST / PST / QST / OTHER). TradeTrack never computes or overwrites a tax amount from a rate.
- **The province table is a reference, used only for hints and warnings** (`server/app/tax.py`). Adding a province
  or changing a rate means editing that one table.
- **No tax advice.** Categories are AI *suggestions* the user can change. TradeTrack never states or implies that an
  expense is deductible or that tax is recoverable. Registration status (`gst_hst_registered`, `gst_hst_number`)
  is optional and only stored, never assumed.

## Reference rates (general rates; hints only)
| Province | Typical tax |
|---|---|
| ON | HST 13% |
| NB, NL, PE | HST 15% |
| NS | HST 14% |
| QC | GST 5% + QST 9.975% |
| BC | GST 5% + PST 7% |
| MB | GST 5% + PST 7% |
| SK | GST 5% + PST 6% |
| AB, NT, NU, YT | GST 5% |

Ontario is the default demo jurisdiction. Zero-rated and exempt items, partly taxable baskets and unregistered
businesses all legitimately differ from these rates, which is why a mismatch is an *info* warning, not an error.

## Rounding and comparison rules (`validation.py`)
- All values are `Decimal`; floats are never used. Non-finite values (NaN, Infinity) are rejected.
- Amounts are rounded to cents with `ROUND_HALF_UP`.
- Comparisons allow a tolerance of **0.02**.

## Warning codes
Warnings never block saving; they ask the user to double-check. Only **merchant and total** are required to save.

| Code | Severity | Meaning |
|---|---|---|
| `missing_merchant`, `missing_date`, `missing_total` | warning | not read from the receipt |
| `future_date` / `old_date` | warning / info | date after tomorrow / more than two years ago |
| `line_items_mismatch` | warning | line items do not add up to the subtotal (also checked net of discounts) |
| `totals_mismatch` | warning | subtotal + tax differs from total (also checked net of discounts) |
| `tax_lines_mismatch` | warning | tax lines do not add up to the tax total |
| `tax_unclear` | warning | total exceeds subtotal but no tax was read |
| `unclear_tax_type` | warning | a tax line could not be identified as GST/HST/PST/QST |
| `tax_rate_differs` | info | tax / subtotal differs from the province's typical rate by more than 0.5 points |
| `tax_type_unexpected` | info | e.g. GST only on an Ontario receipt |
| `low_confidence` | warning | the model reported LOW confidence (also forced when merchant or total is missing) |
| `currency_assumed` | info | no currency printed; CAD shown |
| `non_cad_currency` | info | receipt is not in CAD; no conversion is done |

The province used for the rate check is the receipt's own `province` (if read); otherwise the account's default
province, and the message says so.

## Tests
`tests/test_misc.py` (parsing/rounding, non-finite rejection) and `tests/test_receipts.py` (mismatch, province
rate, tolerance, line items, dates).

# Assignment mapping and honest status

How each requirement in the assignment brief is met, and how it was checked. "Tested" means a check
was actually run; "not run" means the code exists but needs an outside account that was not available.

| Requirement | Implementation | Status |
|---|---|---|
| TradeTrack brand, Canadian market, CAD, GST/HST/PST/QST, province-aware, Ontario demo | Whole UI and API; `tax.py` holds a province table used **only** for hints and warnings, never to compute or overwrite amounts | Done; tax warnings tested |
| Page 1: landing and capture (upload, camera, email explainer, plans, CTAs, labelled sample) | `pages/Landing.tsx`, `UploadZone`, `SampleReceiptDemo`, `PlanCards` | Done; checked in a browser at 390 px and 1280 px |
| Page 2: receipt detail (fields, line items, taxes, category, confidence/warnings, preview, edit, save, export) | `pages/ReceiptDetail.tsx`, `ReceiptForm` | Done; edit, save and refresh persistence checked in a browser against a real PostgreSQL database |
| Page 3: dashboard (history, search/filter, usage, plans, forwarding, exports, profile, privacy) | `pages/Dashboard.tsx` and tab components | Done; the receipts list and usage meter were checked in a browser against the real backend, the other tabs only against mocked data |
| Upload validation, corrupt/unsupported files, duplicates | `extraction.py` (type by file contents), `pipeline.py` (SHA-256 duplicates) | Tested |
| Real AI extraction (images and PDFs), category suggestion, nothing invented | OpenAI in `extraction.py`; unreadable fields stay `null` | Logic tested with a fake provider. **The live OpenAI call was not run** (needs a key) |
| AI failure and not-configured handling | `422 extraction_failed` (receipt kept), `503 ai_not_configured` (file kept, manual entry) | Tested, including in a browser |
| Validation: dates, amounts, totals vs tax vs subtotal | `validation.py`, explicit `Decimal` rounding, 2-cent tolerance | Tested |
| Email forwarding (secure alias, signature, replay, attachments, dedupe) | `routers/inbound.py`, Mailgun route | Checks tested with locally signed requests. **No real Mailgun delivery was run** |
| Freemium: Free 5/month, Premium unlimited, server-side, central config | `plans.py`, save-time check | Tested, including 6th save returning `402` against PostgreSQL |
| Billing: real Stripe when configured, labelled demo otherwise | `routers/billing.py`, `stripe_service.py` | Demo mode tested end to end. **Live Stripe was not run**; webhook signature rejection tested |
| Exports: PDF, CSV, JSON, month/quarter/year summary with tax by province, accountant ZIP package, email to accountant | `exports.py`, `pdf.py` | CSV/JSON/summary values checked against stored data; PDF checked to be a real PDF. Email tested with a mocked mail server; the ZIP contents and owner-only filtering are tested |
| QuickBooks / Wave / Xero integration | **Not built.** Needs OAuth developer credentials and approval; CSV/JSON/PDF and accountant email are the working hand-off | Documented, not claimed |
| Ownership and security (owner-only, 404 for others, anonymous 401, rate limits, formula-injection safe) | `routers/receipts.py`, `auth.py`, `ratelimit.py` | Tested, including against PostgreSQL |
| Schema safety on the existing Neon database | `tt_` tables, `ensure_schema()`; older tables untouched | Tested by starting the app against a PostgreSQL database that already held old-style tables |
| Private file storage | Database (default) or S3, only via the authenticated endpoint | Database path tested byte-for-byte; S3 tested with a mock only |

## What was run

- `cd server && pytest -q`: **91 tests passed** (SQLite, fake AI, no network).
- `cd client && npm run build`: type-check and build pass.
- A PostgreSQL 16 server with TLS was started locally. The app was started against it (alongside
  old-style tables), then about 50 HTTP checks and a 9-step browser journey (sign up, upload, complete,
  save, refresh, dashboard, signed-out access) passed.
- Not run: Neon itself, real OpenAI, Stripe, Mailgun, S3 and SMTP calls; keyboard and screen-reader use;
  browsers other than Chromium.

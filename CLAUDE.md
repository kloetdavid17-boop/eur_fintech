# CLAUDE.md — TradeTrack MVP ("Less paperwork. More business.")

A **receipt and expense-management** MVP for a Canadian Online Retailing assignment. A self-employed
person or small business uploads a receipt (image/PDF) or forwards one by email; AI extracts the
transaction data and suggests an expense category; the user reviews, corrects, and saves it to their
private account; the account dashboard tracks usage against a free/premium plan. Keep it **flat,
small, and demo-ready** — this is a graded MVP, not an enterprise app.

Stack: FastAPI + SQLModel + PostgreSQL (async) backend; React 19 + Vite + Tailwind + React Query
frontend. UI copy is **Canadian English**. Currency is **CAD**. Tax terminology is **GST/HST/PST/QST**,
province-aware, with **Ontario** as the default demo jurisdiction.

> This file supersedes the previous ZZPay/EN16931 invoicing spec. That product (public receipts,
> checkout, refunds as linked credit notes, UBL e-invoicing) is retired. Infrastructure (deploy, DB,
> auth pattern, PDF rendering) is preserved; the domain model and the three pages are new.

## Invariants — do not break these

1. **Receipts are private, owner-only.** There is no public, no-login receipt view. Every receipt
   read/write endpoint requires `CurrentUser` and must filter by `owner_id`. Never trust a client-
   supplied user/account ID — always derive ownership from the authenticated session.
2. **No invented data.** AI extraction must only populate fields it actually read from the document.
   Missing/unreadable fields are marked `unavailable` or left for manual entry — never guessed,
   never defaulted to plausible-looking values (no fake merchant names, dates, or totals).
3. **Suggestions, not advice.** Expense category, tax classification, and deductibility are always
   presented as AI *suggestions* the user can override. Never state or imply a receipt's tax is
   recoverable or that an expense is deductible — that determination is the user's/their accountant's.
4. **Province-aware tax, not a universal rate.** Tax fields (GST, HST, PST, QST) are stored per
   receipt as extracted, not computed from a single hardcoded rate. Ontario (HST 13%) is the default
   seed/demo scenario; the schema must not assume every business or every province works the same way.
5. **Server-enforced usage limits.** Free-plan monthly receipt allowance (default 5/month) is checked
   and enforced in the backend on save, based on successfully *saved* receipts in the current billing
   period — never on the client, never counting failed uploads or duplicates.
6. **No fabricated integrations.** If an AI/OCR provider, inbound-email provider, payment provider, or
   accounting-platform integration isn't actually configured and working, say so in the UI/API
   response. Never show a fake "success" or "connected" state for something that didn't run.
7. **No secrets in the frontend or in git.** All provider keys (AI, email, Stripe, file storage) are
   server-side env vars (`ZZPAY_*` prefix kept so the live Render service keeps working). Never commit `.env`; never return secrets or password hashes in responses.
8. **Don't store payment-card data.** Billing uses a provider (Stripe) token/session flow only.

## What's retired from the previous (ZZPay) spec

- Public, no-login receipt/PDF/PNG access — **removed**; everything is behind auth now.
- Checkout flow, merchant/customer roles — **removed**; there is one role: the account owner uploading
  their own expense receipts.
- Refund as a linked `CreditNote` — **removed**; no sales exist to refund. (Receipts may be edited,
  archived, or deleted by their owner instead — see Page 3.)
- EN 16931 / UBL e-invoice compliance (`ubl.py`, `einvoice.py`, `UblComplianceError`) — **removed**;
  not applicable to expense tracking. Replace with Canadian tax-field validation instead.
- `user_id` nullable on `Receipt` — **removed**; every receipt has a required, server-set owner.

## Product pages (three, per assignment requirement)

1. **Landing + receipt capture** — brand/value prop, upload area (image/PDF, camera capture on
   mobile), email-forwarding explainer, plan overview, CTAs to process a receipt / sign up / sign in.
2. **Receipt detail + results** — extracted fields, line items, subtotal/tax/total, category
   suggestion, confidence/warnings, file preview, edit-and-confirm, save, export, back to dashboard.
3. **Account dashboard** — auth, profile, receipt history with search/filter, usage-vs-plan counter,
   upgrade flow, email-forwarding setup/instructions, exports, archive/delete, privacy settings.

Login, registration, and subscription upgrade can be modals/overlays or sub-routes — they are not
separate "main pages" for the purposes of the three-page requirement.

## Data model (replaces `User` / `Receipt` / `CreditNote`)

- **User** — keep auth fields (Argon2 hash, email). Add: business name (optional), default province,
  plan (`free` / `premium`), billing period anchor, forwarding-alias identifier.
- **Receipt** — owner_id (required FK), source (`upload` / `email`), file reference (storage key, not
  raw bytes in Postgres), status (`processing` / `needs_review` / `saved` / `failed`), merchant, date,
  currency, receipt_number, line items (JSON or child table), subtotal, discounts, tax lines (type +
  amount, e.g. `HST 13%`), total, category (AI-suggested + user-confirmed), confidence/warning flags,
  created/updated timestamps.
- **UsageCounter** (or computed) — receipts saved per user per billing month, for free-plan enforcement.
- Drop `CreditNote` entirely. Province/tax-rate reference data can be a small static table or config,
  not hardcoded into business logic, so more provinces can be added later.

## Layout

| | |
|---|---|
| Backend | `server/app/` — `main.py`, `config.py`, `database.py` (`ensure_schema`), `models.py` (`tt_*` tables + schemas), `auth.py`, `plans.py` (plans/limits, change here), `tax.py`, `validation.py`, `extraction.py` (OpenAI), `pipeline.py` (shared intake), `storage.py`, `exports.py`, `pdf.py`, `email.py`, `stripe_service.py`, `ratelimit.py`, `seed.py`, `routers/` (`users`, `receipts`, `billing`, `inbound`, `config`), `templates/` |
| Frontend | `client/src/` — `api.ts`, `auth.tsx`, `App.tsx`, `pages/` (`Landing`, `ReceiptDetail`, `Dashboard`), `components/`, `hooks/`, `lib/` |
| Tests | `server/tests/` — pytest + httpx against in-memory SQLite with a fake AI provider |
| Docs | `docs/api.md` is the API contract (keep it in sync); also `architecture`, `database`, `deployment`, `assignment-mapping`, `canadian-tax-model`, `ai-extraction`, `email-forwarding`, `subscription-model`, `ai-orchestration` |

## Conventions

- **Backend stays flat.** Tables + Pydantic schemas in `models.py`. No Repository/DAO/Domain layers.
- **One router per resource** under `routers/` (`users`, `receipts`, `billing`, `inbound`, `config`), mounted in
  `main.py`. Use `Depends(get_session)`; commit happens in the dependency on success.
- **Auth:** Argon2 + JWT in the httponly cookie, unchanged pattern. `CurrentUser` (strict) —
  `OptionalUser` is no longer needed anywhere in the receipts flow since nothing is public.
- **Money:** `Decimal` / `Numeric(10, 2)`; decimals serialized as **strings** in JSON. Timestamps are
  tz-aware UTC. New tables carry the `tt_` prefix; never drop or alter the old ZZPay tables. Receipt IDs: `TT-{year}-{6 random uppercase alphanumerics}`.
- **Rendering stays pure-Python** (xhtml2pdf + pypdfium2) — no native libs.
- **Frontend:** typed calls in `api.ts`; server state via React Query; `useAuth` is **blocking** for
  the dashboard/receipt-detail routes now (no auth ⇒ redirect to sign in), since nothing is public
  anymore. Downloads via `lib/download.ts` (fetch+blob). Icons from `react-icons/pi`. Reusable UI in
  `components/`; pages in `pages/`.

## External services (new — document actual configuration status)

- **AI extraction**: OpenAI (`ZZPAY_OPENAI_API_KEY`, model `ZZPAY_OPENAI_MODEL`); must be a real server-side call when configured, with
  explicit error/timeout handling. If unconfigured, the API must return a clear "extraction
  unavailable" error, never fake data.
- **Inbound email**: real provider (e.g. Postmark/Mailgun/SendGrid inbound parse) with webhook
  signature verification; if not configured, the dashboard must say so plainly rather than implying
  it works.
- **File storage**: originals are stored in `tt_receipt_files` by default (documented in
  `docs/database.md`) or in an S3-compatible bucket when fully configured; private access only through
  the authenticated `/file` endpoint, no public URLs.
- **Billing**: Stripe test mode, CAD pricing, webhook-verified subscription status. If not fully wired,
  use a clearly labelled demo upgrade flow — never imply a real charge occurred.

All credentials are env vars, documented in `docs/`, never hardcoded or committed.

## Running

- DB: `docker compose up -d` (Postgres locally). Reset schema with `docker compose down -v && up -d`.
- Backend: `cd server && uvicorn app.main:app --reload --port 8000` (creates tables + seeds on start).
- Frontend: `cd client && npm run dev`.
- Tests: `cd server && pytest`.

## Don't

- Don't make any receipt or its file publicly viewable without auth.
- Don't fabricate AI extraction results, merchant names, line items, or totals.
- Don't apply a single hardcoded tax rate to every transaction regardless of province.
- Don't state or imply an expense is tax-deductible or that tax is recoverable.
- Don't enforce plan limits only on the client.
- Don't claim an AI, email, storage, or billing integration works when it isn't actually configured.
- Don't return `password_hash` (or any secret) in any response. Don't hardcode secrets.
- When you change a feature, **update the README and the relevant `docs/` file** in the same change.

# TradeTrack — Less paperwork. More business.

TradeTrack is a receipt and expense-management web app for Canadian self-employed people,
tradespeople, contractors and small businesses. Upload a receipt photo or PDF (or forward an emailed
receipt), let AI read it, review and correct the result, and keep it ready for bookkeeping.

Built for an Online Retailing assignment as a **freemium** product. Everything the interface
advertises is implemented; features that need an outside account (AI, email, payments) say plainly
when they are not configured instead of pretending to work. See [What works and what needs
credentials](#what-works-and-what-needs-credentials).

> TradeTrack gives suggestions, not tax or accounting advice. Expense categories and tax details
> are AI suggestions you confirm; nothing in the app says an expense is deductible or that tax is
> recoverable. Check with your accountant.

## The three pages

| Page | Route | What it does |
|---|---|---|
| Landing and capture | `/` | Value proposition, receipt upload (file picker, drag and drop, phone camera), how it works, email-forwarding explainer, plans, a clearly labelled sample receipt. |
| Receipt detail | `/receipts/:id` | Extracted merchant, date, line items, taxes (GST/HST/PST/QST), total, suggested category, confidence and warnings, original-file preview. Edit, confirm and save, download, archive, delete. |
| Account dashboard | `/dashboard` | Receipt history with search and filters, usage for the month, plan and upgrade, email-forwarding setup, exports, profile and privacy. Sign-in and sign-up are modals. |

## Plans (change them in one place: `server/app/plans.py`)

| | Free | Premium |
|---|---|---|
| Price | CAD $0 | CAD $5.99 / month |
| Saved receipts | 5 per calendar month (Toronto time), enforced on the server | Unlimited |
| AI extraction, category suggestion, PDF summary, search by text/category/status | Yes | Yes |
| Date and amount filters, monthly summary, CSV/JSON export, email to accountant | No | Yes |
| Email forwarding (unique private address) | No | Yes |

Only successfully **saved** receipts count. Failed uploads, duplicates and unsaved drafts never use
the allowance, and deleting a saved receipt does not give the month's allowance back.

## Run it locally

```bash
docker compose up -d                       # local PostgreSQL (port 5434)
cd server
python -m venv .venv && source .venv/bin/activate     # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                       # set ZZPAY_JWT_SECRET; add ZZPAY_OPENAI_API_KEY for real extraction
python -m uvicorn app.main:app --reload --port 8000

cd ../client && npm install && npm run dev  # http://localhost:5173 (proxies /api to :8000)
```

In development a demo account is created: `demo@tradetrack.ca` / `demo1234` (Premium, with three
receipts clearly labelled as **sample** data). Sign up a normal account to see the Free plan.

**Tests:** `cd server && pytest -q` (in-memory SQLite, fake AI provider, no network or credentials) and
`cd client && npm run build` (type-checks and builds).

## What works and what needs credentials

| Capability | Status |
|---|---|
| Accounts, sign-in, owner-only receipts, usage limits, plans, exports, PDF, search, archive/delete | Working. Covered by the automated tests. |
| Upload validation (type by file contents, size, empty/corrupt), duplicate detection | Working. Tested. |
| AI receipt reading and category suggestion (OpenAI) | **Needs `ZZPAY_OPENAI_API_KEY`.** Without it, uploads are kept and you type the details by hand; the app says so. The live OpenAI call has not been run. |
| Subscription payments (Stripe) | **Needs three Stripe settings**, otherwise a labelled **demo** upgrade that takes no payment. Live Stripe calls have not been run. |
| Email forwarding (Mailgun) | **Needs a Mailgun domain and signing key.** Signature, replay and ownership checks are tested with locally signed requests; a real Mailgun delivery has not been run. |
| Email to accountant (SMTP) | **Needs SMTP settings**; otherwise the endpoint returns "not configured". Tested with a mocked mail server. |
| File storage | Originals are stored in the database by default; an S3-compatible bucket is optional. The S3 path is tested only with a mock. |
| Accounting-platform integrations (QuickBooks, Wave, Xero) | **Not built.** CSV, JSON and PDF exports and "email to accountant" are the working hand-off. |

Details: [docs/assignment-mapping.md](docs/assignment-mapping.md).

## Deploying

Render (frontend and API) plus Neon (PostgreSQL). Step-by-step, environment variables and the
service set-up guides are in [docs/deployment.md](docs/deployment.md). New data goes into `tt_`-prefixed
tables, so a database that already holds older tables is left untouched
([docs/database.md](docs/database.md)).

## Documentation

[architecture](docs/architecture.md) · [API contract](docs/api.md) · [database](docs/database.md) ·
[Canadian tax model](docs/canadian-tax-model.md) · [AI extraction](docs/ai-extraction.md) ·
[email forwarding](docs/email-forwarding.md) · [subscription model](docs/subscription-model.md) ·
[deployment](docs/deployment.md) · [assignment mapping](docs/assignment-mapping.md) ·
[AI agents used](docs/ai-orchestration.md)

## Repository layout

```
server/app/   FastAPI backend: routers/ (users, receipts, billing, inbound, config), models, plans,
              extraction, pipeline, validation, tax, storage, exports, pdf, email, stripe_service
server/tests/ pytest suite
client/src/   React 19 + Vite + Tailwind + React Query: api.ts, auth.tsx, pages/, components/
docs/         contract and guides
```

Educational project for an Online Retailing assignment. No warranty.

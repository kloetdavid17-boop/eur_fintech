# TradeTrack API

FastAPI + SQLModel + PostgreSQL (async). Flat, readable backend for the TradeTrack receipt MVP.
The API contract is `docs/api.md` (repo root).

## Run locally

```bash
docker compose up -d              # from the repo root: local Postgres
cd server
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env              # set ZZPAY_JWT_SECRET (and ZZPAY_OPENAI_API_KEY for real extraction)
python -m uvicorn app.main:app --reload --port 8000
```

Swagger: http://localhost:8000/docs - health: `/api/health` - what is configured: `/api/config`.
In development a demo account is seeded: `demo@tradetrack.ca` / `demo1234` (Premium, 3 SAMPLE receipts).

## Tests

```bash
cd server && pytest -q            # in-memory SQLite, fake AI provider; no network or credentials
```

## Layout

```
app/
  main.py          app + startup (ensure_schema, optional seed)
  config.py        ZZPAY_* settings (+ derived "is it configured" flags)
  plans.py         plan prices/limits/features + Toronto calendar-month period (change plans here)
  tax.py           province tax reference (hints/warnings only)
  validation.py    Decimal parsing, PATCH validation, warnings
  extraction.py    file validation, OpenAI extraction, normalisation
  pipeline.py      shared intake: validate -> dedupe -> store -> extract (uploads + inbound email)
  storage.py       original files: database (default) or S3
  exports.py       CSV/JSON/monthly summary      pdf.py  receipt + summary PDFs
  email.py         SMTP (email to accountant)    stripe_service.py  Stripe helpers
  models.py        tt_* tables + schemas         database.py  engine, ensure_schema()
  routers/         users, receipts, billing, inbound, config
docs/ (repo root): database.md, canadian-tax-model.md, ai-extraction.md, email-forwarding.md, subscription-model.md
```

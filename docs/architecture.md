# Architecture

```
 Browser (React SPA)  ──  /api/*  ──►  FastAPI  ──►  PostgreSQL (Neon)
   pages: /, /receipts/:id, /dashboard     │  ├─ OpenAI   (read receipts)        optional
                                           │  ├─ Stripe   (subscriptions)        optional
 Mailgun route ──► POST /api/inbound/...  ─┤  ├─ SMTP     (email to accountant)  optional
                                           │  └─ S3 bucket (original files)      optional
```

One backend service and one static site. The static host forwards `/api/*` to the backend, so the
browser sees a single origin and the httponly login cookie works without CORS tricks.

## Receipt intake pipeline (`pipeline.py`)

Uploads and forwarded emails use the same path:

1. Validate the file: type is decided from the file's own bytes (not the browser's claim), size limit,
   not empty, not corrupt.
2. Hash it (SHA-256). If this user already has the same file, return the existing receipt; the AI is
   not called again and nothing new is created.
3. Store the original (database by default, S3 if configured).
4. Extract with OpenAI (images directly; PDFs via their text layer, else rendered pages). Numbers are
   parsed as `Decimal`; anything unreadable stays `null`. Failures and timeouts become a `FAILED`
   receipt with a clear message, never a fake success.
5. Validate and attach warnings (missing fields, totals that do not add up, tax unusual for the
   province, low confidence). Warnings never block saving; saving needs only merchant and total.
6. The user reviews and corrects, then **saves**. Saving checks the plan limit on the server and
   writes one usage row.

## Data (see [database.md](database.md))

`tt_users`, `tt_receipts`, `tt_receipt_files`, `tt_usage_events`, `tt_inbound_events`,
`tt_inbound_tokens`. Money is `Numeric(10,2)` and travels as strings in JSON. Every receipt has a
required owner.

## Security model

- Auth: Argon2 password hashes, JWT in an httponly cookie (`Secure` outside development, SameSite Lax);
  bearer tokens are also accepted. Login and upload endpoints are rate limited (per process, in memory).
- Ownership is enforced in the backend on every receipt route, including the file and PDF downloads;
  another user's receipt returns 404. Files are never public.
- The plan and usage limit come only from the server; the client cannot set them.
- Inbound email: Mailgun HMAC signature and timestamp checked, replayed tokens rejected, the account is
  identified only by the secret recipient alias (never the sender), attachments validated by contents,
  duplicate messages and files skipped, only a minimal log kept (no bodies or subjects).
- Stripe webhooks are signature-verified. No card data touches the app.
- Exports escape spreadsheet formulas; PDFs and pages escape user text.
- Secrets live only in server environment variables.

## Known limitations

- Login and upload rate limits are per process (in memory); a multi-instance deployment would need a
  shared store. Inbound-email replay tokens are kept in the database, so they already work across instances.
- No schema migration tool yet: new columns go through `ensure_schema()` (see [database.md](database.md)).
- Free Render services sleep after idle, so the first request can take about a minute.

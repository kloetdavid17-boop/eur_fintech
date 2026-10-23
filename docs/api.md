# TradeTrack API contract (v1)

Single source of truth shared by the backend (`server/app/`) and the frontend
(`client/src/api.ts`). All routes live under `/api`. JSON unless noted. **Money is always a
string** (`"13.00"`), never a float. Timestamps are ISO-8601 UTC. Auth is an httponly cookie
(`tradetrack_token`); a `Authorization: Bearer` header is also accepted.

Errors use FastAPI's shape: `{"detail": "text"}` **or** `{"detail": {"code": "...", "message": "..."}}`.
The UI should show `detail.message ?? detail`. Known `code`s are listed per endpoint.

Status codes the UI must handle: `401` (not signed in), `402` (plan limit / premium feature),
`404` (also returned for *someone else's* receipt), `409` (conflict), `413`/`400` (bad file),
`422` (validation), `429` (rate limited), `503` (service not configured).

## Public

| Route | Notes |
|---|---|
| `GET /api/health` | `{status:"ok", app:"TradeTrack"}` |
| `GET /api/config` | Everything the UI needs to be honest about what is configured (below) |

### `GET /api/config`
```json
{
  "app_name": "TradeTrack",
  "currency": "CAD",
  "plans": [
    {"id":"FREE","name":"Free","price_cad":"0.00","monthly_receipt_limit":5,
     "features":["Upload receipts (image or PDF)","AI extraction + category suggestion", "..."]},
    {"id":"PREMIUM","name":"Premium","price_cad":"5.99","monthly_receipt_limit":null,
     "features":["Unlimited saved receipts","CSV / JSON export", "..."]}
  ],
  "feature_matrix": [{"feature":"CSV & JSON export","free":false,"premium":true}],
  "categories": ["Tools and equipment", "..."],
  "provinces": [{"code":"ON","name":"Ontario","tax_hint":"HST 13%"}],
  "upload": {"max_mb":10,"allowed_types":["image/jpeg","image/png","image/webp","application/pdf"]},
  "services": {
    "ai_configured": true,
    "inbound_email_configured": false,
    "inbound_domain": null,
    "billing_mode": "demo",
    "smtp_configured": false,
    "file_storage": "database"
  }
}
```
`billing_mode` is `"stripe"` (real Stripe Checkout) or `"demo"` (simulated upgrade, **no payment is
taken** — the UI must label it as a demo). `file_storage` is `"s3"` or `"database"`.

## Account (`users.py`)

| Route | Body → Response |
|---|---|
| `POST /api/register` | `{email, first_name, last_name, password(min 8), business_name?, province?, accountant_email?}` → `201 UserOut`, **sets the auth cookie** (already signed in). `409` if email exists. |
| `POST /api/login` | form `username=<email>&password=` (`application/x-www-form-urlencoded`) → `{access_token, token_type}`, sets cookie. `401` on bad credentials. `429` after repeated failures. |
| `POST /api/logout` | → `{detail}` |
| `GET /api/me` | → `UserOut` (`401` when signed out) |
| `PUT /api/me` | `{first_name?, last_name?, business_name?, province?, accountant_email?, gst_hst_registered?, gst_hst_number?}` → `UserOut` |
| `POST /api/me/forwarding-alias/rotate` | → `UserOut` with a new alias (old address stops working) |
| `GET /api/me/inbound-log` | → `[{id, received_at, status, reason, attachments, receipt_ids[]}]` (newest first, max 50). `status`: `PROCESSED`, `REJECTED`, `DUPLICATE`, `FAILED`. No email bodies/subjects are stored. |
| `GET /api/me/export` | → full JSON export of the account + all receipts (privacy / portability) |
| `DELETE /api/me` | `{password}` → `204`; permanently deletes the account, receipts, files |

```
UserOut = {
  id, email, first_name, last_name, business_name|null, province ("ON"...),
  accountant_email|null, gst_hst_registered: bool|null, gst_hst_number|null,
  plan: "FREE"|"PREMIUM", subscription_status|null,
  forwarding_alias, forwarding_address|null,   // null unless inbound email is configured
  created_at
}
```

## Receipts (`routers/receipts.py`) — all require sign-in and are owner-only

```
ReceiptOut = {
  id,                                   // "TT-2026-A1B2C3"
  source: "UPLOAD"|"EMAIL",
  processing_status: "NEEDS_REVIEW"|"SAVED"|"FAILED"|"ARCHIVED",
  extraction_confidence: "HIGH"|"MEDIUM"|"LOW"|"UNKNOWN",
  extraction_error|null,
  original_filename|null, file_mime_type|null, has_original_file: bool,
  is_sample: bool,                      // true for clearly-labelled demo data
  merchant|null, receipt_date|null ("YYYY-MM-DD"), receipt_time|null ("HH:MM"),
  currency, receipt_number|null,
  line_items: [{description, quantity|null, unit_price|null, amount|null}],
  discounts|null,
  subtotal|null,
  tax_lines: [{label, amount, tax_type: "GST"|"HST"|"PST"|"QST"|"OTHER"}],
  tax_total|null, total|null,
  province|null,
  category|null, category_is_ai_suggested: bool,
  warnings: [{code, severity:"info"|"warning", field|null, message}],
  notes|null,                           // the owner's own free-text note
  processing_note|null,                 // e.g. "This looks like a receipt you already uploaded"
  reviewed_at|null, created_at, updated_at
}
```
`null` always means *unavailable / not read* — the UI shows "Not available", never a guess.
`warnings` are server-generated checks (missing fields, line items ≠ subtotal, subtotal + tax ≠ total,
tax differs from the typical rate for the province, unusual date, low confidence). They never block
saving; they ask the user to double-check.

| Route | Details |
|---|---|
| `POST /api/receipts/process` | multipart `file` → `ReceiptOut` (`NEEDS_REVIEW`). `400` bad type/size/empty/corrupt (`detail` string). **Duplicate** (same file hash for this user) → `200` with the *existing* receipt and `processing_note` set; AI is not called again. `422 {code:"extraction_failed", message, receipt_id}` — a `FAILED` receipt exists and can be completed manually. `503 {code:"ai_not_configured", message}` — if a `receipt_id` is present the file was kept and the receipt can be completed manually. `429` rate limit. |
| `POST /api/receipts/{id}/reprocess` | Re-run extraction on the stored file (FAILED/NEEDS_REVIEW). Same errors as `process`. |
| `PATCH /api/receipts/{id}` | Partial update (`merchant, receipt_date, receipt_time, currency, receipt_number, line_items, discounts, subtotal, tax_lines, tax_total, total, province, category, notes`). Server re-validates and refreshes `warnings`. `422` on invalid date/amount/category. |
| `POST /api/receipts/{id}/save` | Confirms the receipt → `SAVED` (counts toward the monthly allowance). Idempotent. `402 {code:"free_limit_reached", message, limit, used, period_end}`. `422 {code:"missing_required_fields", message, fields:["merchant","total"]}`. |
| `POST /api/receipts/{id}/archive` / `unarchive` | Soft hide / restore (`ReceiptOut`). |
| `DELETE /api/receipts/{id}` | `204`. Permanently removes the receipt, its file and its usage row. |
| `GET /api/receipts/{id}` | `ReceiptOut` |
| `GET /api/receipts/{id}/file` | The original upload (binary, `inline`). `404` if none stored. Never public. |
| `GET /api/receipts/{id}/pdf` | TradeTrack PDF summary of the saved data (all plans). |
| `GET /api/receipts?q=&category=&status=&date_from=&date_to=&min_amount=&max_amount=&limit=&offset=` | → `{items: ReceiptOut[], total}`; newest first; hides `ARCHIVED` unless `status=ARCHIVED`. **Free plan:** `q`, `category`, `status` only — using date/amount filters returns `402 {code:"premium_required"}`. |
| `GET /api/receipts/usage` | → `{plan, saved_this_period, limit|null, remaining|null, period_start, period_end, period_label, resets_on}` (calendar month, `America/Toronto`). |

### Premium-only (`402 {code:"premium_required", message}` on the Free plan)
| Route | Details |
|---|---|
| `GET /api/receipts/summary?month=YYYY-MM` | `{month, currency, count, undated_count, subtotal, tax_total, total, by_category:[{category,count,subtotal,tax_total,total}], by_tax_type:{GST,HST,PST,QST,OTHER}, flagged_count}` — SAVED receipts only. |
| `GET /api/receipts/export?format=csv\|json&month=&date_from=&date_to=&category=` | Attachment download of SAVED receipts, columns/fields match the stored data exactly. |
| `GET /api/receipts/export/summary?month=YYYY-MM&format=csv\|pdf` | Monthly expense summary download. |
| `POST /api/receipts/export/email` | `{month:"YYYY-MM"}` → emails CSV + summary PDF to the account's accountant. `400 {code:"no_accountant_email"}`, `503 {code:"email_not_configured"}` (never a fake success). |

## Billing (`routers/billing.py`)
| Route | Details |
|---|---|
| `GET /api/billing/status` | `{plan, subscription_status, mode:"stripe"\|"demo", can_manage, current_period_end|null, cancel_at_period_end}` |
| `POST /api/billing/checkout` | `mode=stripe` → `{url}` (redirect the browser to Stripe Checkout). In demo mode → `409 {code:"billing_demo_mode"}`. |
| `POST /api/billing/portal` | `mode=stripe` → `{url}` (Stripe customer portal: cancel / payment method). |
| `POST /api/billing/demo/upgrade`, `/demo/downgrade` | Only when `mode=demo` (else `404`). Flips the plan on the server. **No payment is taken** — label it as a demo in the UI. |
| `POST /api/billing/webhook` | Stripe → server only. Signature verified. Not for the frontend. |

After returning from Stripe Checkout (`/dashboard?billing=success`) the plan changes via webhook, so
the UI should poll `GET /api/billing/status` for a few seconds.

## Inbound email (`routers/inbound.py`) — provider → server only
`POST /api/inbound/mailgun` (Mailgun "forward to URL" route). HMAC-SHA256 signature + timestamp
freshness verified, token replay rejected. The *recipient alias* (an unguessable secret local-part)
identifies the account — never the sender address. Premium accounts only. Attachments are validated
by magic bytes and run through the same extraction pipeline; results land as `NEEDS_REVIEW` receipts
with `source:"EMAIL"`.

## Frontend routes
`/` Landing + capture · `/receipts/:id` Receipt detail · `/dashboard` Account & management
(auth required). Login / register are modals. `*` → `/`.

## Backend notes / deviations

Implemented in `server/`. Where the contract was ambiguous or deliberately changed:

1. **Delete keeps the usage row.** `DELETE /api/receipts/{id}` removes the receipt and its file but
   *keeps* its `tt_usage_events` row for the period (contract said it removes it). Otherwise "save,
   delete, upload again" would give unlimited free receipts. The row goes away only with the account.
2. **Error bodies.** Invalid field values: `422 {code:"invalid_field", message, field}`. `429` always
   `{code:"rate_limited", message}`. Archived receipt save: `409 {code:"receipt_archived"}`; reprocess of
   a saved receipt: `409 {code:"not_reprocessable"}`. Premium routes: `402 {code:"premium_required"}`.
3. **`quantity`** in line items is a decimal *string* (e.g. `"2"`, `"1.5"`) like all numbers; the PATCH body
   accepts a number or a string.
4. **Process outcomes.** A `FAILED` earlier attempt for the same file is retried on the same receipt instead
   of being reported as a duplicate. With no AI key the response is `503 ai_not_configured` with a
   `receipt_id`; that receipt is `FAILED` with `extraction_error` explaining it (file kept, editable).
   A manual `PATCH` of a `FAILED` receipt moves it to `NEEDS_REVIEW`.
5. **Currency.** If the receipt shows no currency, `currency` is `"CAD"` (the column is not nullable) and an
   info warning `currency_assumed` says so. If the AI omits `tax_total` but reads tax lines, `tax_total` is
   the plain sum of those printed lines.
6. **Summary.** `by_category[].category` is `"Uncategorized"` when empty. Extra field `other_currency_count`:
   non-CAD receipts are excluded from the CAD totals. Receipts are placed in the month of their receipt
   date; undated receipts are only counted in `undated_count` (for the month they were saved).
7. **`POST /api/receipts/export/email`** returns `{sent:true, to, month, receipts}` on success; `502
   email_send_failed` if SMTP fails. Every failure is non-2xx.
8. **`DELETE /api/me`** with a wrong password returns `403` (not 401, so the UI does not log out). If a live
   Stripe subscription cannot be cancelled: `502 subscription_cancel_failed`, account not deleted.
9. **Inbound email** responses (for Mailgun, not the UI): `403` bad/stale/replayed signature, `406`
   unknown recipient or non-Premium account (permanent, no retry), `200` with `{status: processed|duplicate|
   rejected|failed}` otherwise, `503` when not configured.
10. **Stripe** return URLs are `<frontend origin>/dashboard?billing=success|cancel`; the origin is
    `ZZPAY_FRONTEND_URL` or the first `ZZPAY_CORS_ORIGINS` entry.
11. **Cookie** is `SameSite=Lax` by default (as specified). If the frontend and API are on different
    *sites* (e.g. two `onrender.com` subdomains), browsers will not send it on API calls: serve the API
    through the frontend origin (proxy/rewrite) or set `ZZPAY_COOKIE_SAMESITE=none`. `Authorization: Bearer`
    is always accepted.
12. `GET /api/receipts/{id}/pdf` works for any status (not only SAVED).

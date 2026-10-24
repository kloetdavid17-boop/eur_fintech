# Subscription model

## Plans (one place: `server/app/plans.py`)
| | Free | Premium |
|---|---|---|
| Price | CAD 0.00 | CAD 5.99 / month |
| Saved receipts | 5 per calendar month | unlimited |
| Upload, AI extraction, edit, PDF/file download, text/category/status search | yes | yes |
| Date and amount filters, summary by month/quarter/year (tax by province), accountant package (ZIP), CSV/JSON export, email to accountant, email forwarding | no | yes |

Overrides: `ZZPAY_FREE_MONTHLY_LIMIT`, `ZZPAY_PREMIUM_PRICE_CAD`. The feature list and comparison table served by
`GET /api/config` come from `plans.py`, so the UI cannot advertise something the plan config does not list.

## Rules (enforced on the server)
- The period is the **calendar month in America/Toronto**.
- Only **saved** receipts count (`POST /api/receipts/{id}/save`, checked server-side, row-locked on Postgres).
  Uploads, failed extractions, duplicates and unsaved reviews never count. Saving twice never double counts
  (unique usage row per receipt). Archive/unarchive does not change the count.
- Deleting a saved receipt does **not** give the allowance back in the same month (prevents delete-and-resave gaming).
- At the limit the save returns `402 free_limit_reached` with `limit`, `used`, `period_end`.
- After a downgrade, receipts saved this month still count against the free limit.
- The plan is only changed by the server: registration is always FREE; the client cannot send a plan.

## Demo mode (default; no Stripe keys)
`GET /api/billing/status` -> `mode: "demo"`. `POST /api/billing/demo/upgrade|downgrade` flip the plan.
**No payment is taken**; the UI must label this as a demo. These routes return 404 in Stripe mode.

## Real Stripe mode
Active when `ZZPAY_STRIPE_SECRET_KEY` **and** `ZZPAY_STRIPE_PRICE_ID` are set.
1. In Stripe (test mode first) create a Product with a **recurring monthly Price in CAD** (5.99). Copy the price id (`price_...`).
2. Set `ZZPAY_STRIPE_SECRET_KEY` (`sk_test_...`), `ZZPAY_STRIPE_PRICE_ID`, and `ZZPAY_FRONTEND_URL` (or rely on the first CORS origin).
3. Add a webhook endpoint `https://<backend>/api/billing/webhook` for events `checkout.session.completed`,
   `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`; copy its signing secret
   to `ZZPAY_STRIPE_WEBHOOK_SECRET`. (Local: `stripe listen --forward-to localhost:8000/api/billing/webhook`.)
4. Enable the Customer Portal in Stripe settings (cancel + payment method).

Flow: `POST /api/billing/checkout` -> `{url}` -> Stripe Checkout -> returns to `<frontend>/dashboard?billing=success|cancel`.
The plan changes **only** from a webhook with a valid signature (invalid -> 400; missing secret -> 503). Users are matched by
stored Stripe ids or by the `user_id` metadata the server attached to the session. `past_due` keeps Premium while Stripe
retries; `canceled`/`unpaid` returns to Free; the end of an old subscription does not affect a newer one.
`POST /api/billing/portal` opens the Stripe customer portal. Deleting an account cancels its live subscription first.
Card data never touches TradeTrack.

## Testing status
Demo mode, plan limits, webhook signature rejection and the webhook state transitions are covered by tests
(`tests/test_billing.py`, with locally signed payloads). **Real Stripe Checkout/portal/cancel calls have not been run.**

## Confirmation emails
- **Welcome email** when an account is created, and a **Premium order confirmation** when an account becomes Premium
  (demo upgrade, or the verified Stripe webhook). The confirmation says what was bought (CAD price per month) and is
  labelled honestly: "demo, no payment taken", "TEST MODE, no real money charged" (key starts `sk_test_`), or a plain
  Stripe payment note. It is sent once per upgrade, however many webhook events Stripe delivers.
- Both are best effort. If no provider is configured the API reports `not_configured` and the UI says nothing about an
  email; if the provider rejects it the API reports `failed` and the UI says it could not be sent. The UI only says an
  email was sent when the provider accepted it. A failed email never blocks signing up or paying.

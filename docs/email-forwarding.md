# Email forwarding (Mailgun)

Users forward a receipt email to their personal TradeTrack address. **Premium feature.** It only works once
you configure Mailgun - until then `GET /api/config` reports `inbound_email_configured: false`, the UI shows no
address (`forwarding_address` is `null`) and the endpoint answers `503`.

## How it works
`alias@<ZZPAY_INBOUND_DOMAIN>` -> Mailgun receives it -> Mailgun POSTs it to `https://<backend>/api/inbound/mailgun`.
Each account has a random alias (80 bits, e.g. `r3f9a...`), rotatable with `POST /api/me/forwarding-alias/rotate`
(the old address stops working at once).

## Security checks (in order)
1. HMAC-SHA256 of `timestamp + token` with `ZZPAY_MAILGUN_SIGNING_KEY` (constant-time compare) - else `403`.
2. Timestamp within +-5 minutes (`ZZPAY_INBOUND_MAX_AGE_SECONDS`) - else `403`.
3. Token not seen before (stored hashed in `tt_inbound_tokens`) - replays get `403`.
4. The **recipient alias** selects the account. The sender address/name is never used for identification. Unknown alias -> `406`.
5. Account must be Premium - else `406` and a REJECTED entry in the owner's log.
6. Duplicates: same `Message-Id` (hashed) or same attachment file hash -> no second receipt, no second AI call.
7. Attachments (max 5): validated by magic bytes and size; unsupported/corrupt ones are skipped and logged.
   Attachments go through the same pipeline as uploads. If there are no attachments, a text rendering of the body
   (plain, or HTML stripped) is sent to the extractor and **discarded** (not stored).
8. Only a minimal `tt_inbound_events` row is stored (no sender, subject or body); the owner sees it at `GET /api/me/inbound-log`.

Resulting receipts have `source: "EMAIL"` and status `NEEDS_REVIEW` (or `FAILED` if extraction failed).
Mailgun treats `406` as "do not retry".

## Setup steps
1. Create a Mailgun account and add a **receiving domain** (a subdomain is best, e.g. `receipts.yourdomain.ca`).
2. At your DNS provider add the Mailgun **MX records** for that subdomain (`mxa.mailgun.org`, `mxb.mailgun.org`,
   priorities 10) plus the SPF/DKIM records Mailgun shows. Wait until Mailgun shows the domain as verified.
3. In Mailgun -> Receiving -> **Create route**:
   - Expression type: *Match Recipient*, pattern `.*@receipts.yourdomain.ca`
   - Action: *Forward* to `https://<your-backend>/api/inbound/mailgun`
   - Keep *Stop* ticked. (Use the default multipart/form-data "parsed" forwarding.)
4. In Mailgun -> Settings -> API security copy the **HTTP webhook signing key**.
5. Set on the backend (Render env): `ZZPAY_INBOUND_DOMAIN=receipts.yourdomain.ca` and `ZZPAY_MAILGUN_SIGNING_KEY=<key>`.
   Redeploy. `GET /api/config` should now show `inbound_email_configured: true`.
6. Make sure `ZZPAY_OPENAI_API_KEY` is set too, otherwise forwarded receipts are kept as `FAILED` manual-entry receipts.

## Testing it
- Upgrade a test account (demo upgrade or real), copy its forwarding address from the dashboard, and email a
  receipt PDF/photo to it. Within a minute a `NEEDS_REVIEW` receipt with source EMAIL should appear and
  `GET /api/me/inbound-log` shows `PROCESSED`.
- Mailgun's "Logs" and the route's webhook response codes show delivery problems.
- Automated tests (`tests/test_inbound.py`) use a local signature with a test key: bad signature, stale timestamp,
  replay, unknown alias, free plan, duplicate message/file, bad and oversize attachments, body-only email, AI failure,
  alias rotation. **A real Mailgun delivery has not been tested.**

## Limits
The replay/rate-limit state for tokens is in the database; the per-account rate limit (60/min) is per process.

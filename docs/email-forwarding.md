# Email forwarding (Gmail inbox or Mailgun)

Users forward a receipt email to their personal TradeTrack address. **Premium feature.** It only works once
you configure Mailgun - until then `GET /api/config` reports `inbound_email_configured: false`, the UI shows no
address (`forwarding_address` is `null`) and the endpoint answers `503`.

There are two ways to receive the forwarded emails. They share all the rules below (plan check, duplicates,
attachment validation, AI extraction, the owner's log); only how the email arrives differs.

| | Gmail inbox (no domain, free) | Mailgun (needs your own domain) |
|---|---|---|
| Address users see | `inbox+<alias>@gmail.com` | `<alias>@receipts.yourdomain.com` |
| How it arrives | TradeTrack checks the inbox about once a minute (IMAP) | Mailgun POSTs to `/api/inbound/mailgun` |
| Needs | a Gmail account + app password; server kept awake | a domain, MX records, a Mailgun route |
| Delay | up to about a minute | seconds |

If both are configured, Mailgun is used.

## Gmail inbox (no domain)
1. Create a Gmail account used only for TradeTrack (for example `tradetrack.receipts@gmail.com`).
2. Turn on **2-step verification** for it, then create an **App password** (Google Account > Security > App
   passwords). Use that 16-character password, never the real one.
3. In Render (backend service) set `ZZPAY_INBOUND_GMAIL_ADDRESS=<that address>` and
   `ZZPAY_INBOUND_GMAIL_APP_PASSWORD=<app password>`, then redeploy. `GET /api/config` should show
   `inbound_mode: "gmail"`; after a minute `inbound_ok` becomes `true` (or `false` if the login was refused).
4. **Keep the backend awake.** Polling only happens while the server runs, and Render's free plan sleeps after
   15 minutes without traffic. Ping `https://<backend>/api/health` every 5 minutes (UptimeRobot is free). One
   always-on free service fits inside Render's 750 free hours a month. Emails that arrive while it sleeps wait
   in the inbox and are picked up when it wakes.
5. Make sure `ZZPAY_OPENAI_API_KEY` is set too.

Behaviour: the alias in the recipient (`To`, `Delivered-To`, ...) selects the account; the sender never does.
Mail without a known alias is ignored and costs no AI call. Handled messages are marked read and moved to the
inbox's Trash. A message that fails three times in a row (for example a database error) is closed out so it
cannot loop. Gmail's own "confirm forwarding" emails are ignored, which also means **automatic forwarding rules in
Gmail cannot be set up** (the confirmation code never reaches the user): users forward emails one at a time.
Inline images smaller than 30 KB (logos, tracking pixels) are not treated as receipts.

Privacy: forwarded emails pass through this one mailbox, owned by whoever runs the site. A dedicated inbox is the
cleaner choice. TradeTrack stores no sender, subject or body (only the minimal log row).

Using an existing (personal) Gmail instead works as a fallback, and the poller is safe for it: each check lists only
unread mail from the last 3 days and reads just the recipient headers. A message is downloaded, handled and moved to
Trash **only if** it is addressed to `<inbox>+<alias>@gmail.com` and the alias belongs to a TradeTrack account. All
other mail (and mail to a `+tag` that is not a TradeTrack alias) is never downloaded, marked read or moved. The app
password still gives the server IMAP access to that whole mailbox, so keep it in the Render environment only, and
revoke it (Google Account, Security, App passwords) when the demo is over.

## Mailgun (own domain)
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
  alias rotation. **A real Mailgun delivery has not been tested.** The Gmail path (`tests/test_inbox.py`) is tested against a
fake IMAP server and crafted messages; **a real Gmail login and delivery have not been tested** until the owner
sets the two variables above and forwards a real email.

## Limits
The replay/rate-limit state for tokens is in the database; the per-account rate limit (60/min) is per process.

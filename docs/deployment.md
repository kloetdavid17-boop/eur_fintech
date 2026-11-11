# Deployment (Render + Neon)

Two Render services plus a Neon database. All settings below are environment variables on Render;
nothing secret goes in GitHub.

## 1. Database (Neon)

1. Create a Neon project and copy the **direct** connection string (not the `-pooler` host).
2. Use it as `ZZPAY_POSTGRES_URL`. The app converts the URL for its async driver and turns TLS on.
3. On first start the app creates its own `tt_*` tables. Any older tables in the same database (for
   example from the earlier ZZPay version) are **not touched** or deleted.

## 2. Backend (Render Web Service)

| Setting | Value |
|---|---|
| Branch | the branch you deploy from (see "Which branch" below) |
| Root directory | `server` |
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/api/health` |
| Python | 3.12 (`PYTHON_VERSION=3.12.8`) |

Environment variables (all optional ones can be added later; the app reports what is missing at
`/api/config`):

| Variable | Needed? | Purpose |
|---|---|---|
| `ZZPAY_ENVIRONMENT=production` | **Yes** | Secure cookies, no demo seeding. |
| `ZZPAY_JWT_SECRET` | **Yes** | Long random string (`python -c "import secrets; print(secrets.token_hex(32))"`). |
| `ZZPAY_POSTGRES_URL` | **Yes** | Neon connection string. |
| `ZZPAY_CORS_ORIGINS` | Yes | Your frontend URL, e.g. `https://your-site.onrender.com`. |
| `ZZPAY_FRONTEND_URL` | For Stripe | Same frontend URL; used for the return links after payment. |
| `ZZPAY_OPENAI_API_KEY` | For AI reading | Without it, receipts are kept and filled in by hand. Optional `ZZPAY_OPENAI_MODEL` (default `gpt-4o-mini`). |
| `ZZPAY_STRIPE_SECRET_KEY`, `ZZPAY_STRIPE_PRICE_ID`, `ZZPAY_STRIPE_WEBHOOK_SECRET` | For real payments | Without them: labelled demo upgrade. Guide: [subscription-model.md](subscription-model.md). |
| `ZZPAY_MAILGUN_SIGNING_KEY`, `ZZPAY_INBOUND_DOMAIN` | For email forwarding | Guide: [email-forwarding.md](email-forwarding.md). |
| `ZZPAY_BREVO_API_KEY` + `ZZPAY_SMTP_FROM` | For the welcome email, the Premium order confirmation and "email to accountant". **Use this on Render's free plan**, which blocks outgoing SMTP ports 25, 465 and 587. `ZZPAY_SMTP_FROM` must be a sender address verified in Brevo, e.g. `TradeTrack <you@gmail.com>` | |
| `ZZPAY_SMTP_HOST` (+ `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_TLS`) | Alternative to Brevo when the host allows SMTP | |
| `ZZPAY_S3_ENDPOINT`, `_BUCKET`, `_ACCESS_KEY`, `_SECRET_KEY`, `_REGION` | Optional | Store originals in a private bucket instead of the database. |
| `ZZPAY_SEED_DEMO=true`, `ZZPAY_DEMO_PASSWORD` | Optional | Creates `demo@tradetrack.ca` with sample receipts. Handy for a grading demo; it uses a publicly known default password unless you set one. |

Full list with comments: `server/.env.example`.

## 3. Frontend (Render Static Site)

| Setting | Value |
|---|---|
| Root directory | `client` |
| Build command | `npm install && npm run build` |
| Publish directory | `dist` |

Add two **rewrite** rules, in this order:

1. `/api/*` → `https://YOUR-BACKEND.onrender.com/api/*`
2. `/*` → `/index.html`

The first keeps the browser on one origin, which the login cookie needs. If you ever serve the API
from a different site instead, set `ZZPAY_COOKIE_SAMESITE=none` and use HTTPS everywhere.

## Which branch

Render deploys whichever branch each service is set to. The finished TradeTrack rebuild lives on
branch `tradetrack-build`. The `dev` branch currently holds a half-converted state (new models with
old ZZPay routes) that cannot start, so deploy `tradetrack-build`: either point both Render services
at it, or merge it into `dev`.

## After deploying: checklist

1. `https://YOUR-BACKEND.onrender.com/api/health` returns `{"status":"ok","app":"TradeTrack"}`.
2. `/api/config` shows which services are configured (`ai_configured`, `billing_mode`, ...). Anything
   `false` or `demo` is expected until you add that service's variables.
3. Open the site, create an account, upload a receipt. With an OpenAI key you get extracted fields;
   without one you get the "not configured" notice and can type the details.
4. Free Render services sleep after about 15 minutes idle (first request ~1 minute). Open the site
   a minute before a demo, or use a paid instance.

## Rolling back

The app never modifies or drops older tables, so the original ZZPay data in the same database stays
intact. The last working ZZPay version is commit `f07486f`; redeploying that commit brings it back.

## Free-plan sleep (Render)
Render's free web services sleep after about 15 minutes without traffic, and waking takes up to roughly a minute. The
frontend retries the settings request for about a minute and shows "The server is waking up" instead of an error, but
the first visitor still waits. Two fixes: (1) ping `https://<backend>/api/health` every 5 minutes with a free uptime
monitor (e.g. UptimeRobot), or (2) move the backend to a paid instance (also removes the outgoing-SMTP block).

## Test mode notice
When `ZZPAY_STRIPE_SECRET_KEY` starts with `sk_test_`, `/api/config` reports `services.billing_test_mode: true` and the
upgrade buttons show the Stripe test card (4242 4242 4242 4242) so testers can pay without being charged. A live key
hides the note automatically.

## Email forwarding wording
Until `ZZPAY_INBOUND_DOMAIN` and `ZZPAY_MAILGUN_SIGNING_KEY` are set, the Premium feature list and comparison table
say "Email-forwarding receipt capture (coming soon)" and the how-it-works step does not mention forwarding.

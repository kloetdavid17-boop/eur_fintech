# Database (Neon / PostgreSQL)

## Tables (all prefixed `tt_`)

| Table | Purpose |
|---|---|
| `tt_users` | Accounts: Argon2 password hash, business profile, province, plan, Stripe ids, secret forwarding alias |
| `tt_receipts` | One row per receipt. `user_id` is NOT NULL; unique `(user_id, file_sha256)` prevents duplicate uploads |
| `tt_receipt_files` | Original upload bytes (`bytea`) when file storage is `database` (default) |
| `tt_usage_events` | One row per SAVED receipt (`receipt_id` unique). The free-plan limit counts these per Toronto calendar month. No foreign key to receipts on purpose: deleting a receipt does not refund the allowance |
| `tt_inbound_events` | Minimal log of forwarded emails (time, status, short reason, attachment count, receipt ids, hash of Message-Id). No sender, subject or body |
| `tt_inbound_tokens` | Mailgun webhook tokens already used (replay protection), pruned after an hour |

Money is `Numeric(10,2)`; JSON responses use strings. Receipt dates are `DATE`, timestamps are timezone-aware UTC.

## Old ZZPay tables

The live Neon database still contains the legacy ZZPay tables `users`, `receipts` and `credit_notes` with
different columns. TradeTrack **never reads, alters or drops them** - that is why every new table has the `tt_`
prefix (`create_all` cannot alter existing tables). Once you no longer need the old data you can drop them
manually, e.g. `DROP TABLE credit_notes, receipts, users;` (not done automatically).

## Schema management: `ensure_schema()`

Runs on every startup (`app/database.py`). It is idempotent and additive only:

1. `create_all` creates any missing `tt_*` table.
2. On PostgreSQL it runs each statement in `ADDITIVE_COLUMNS`
   (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`). SQLite (tests) skips this step.

It never drops or rewrites anything.

### Adding a column later
1. Add the field to the model in `app/models.py`.
2. Append one statement to `ADDITIVE_COLUMNS` in `app/database.py`, e.g.
   `"ALTER TABLE tt_receipts ADD COLUMN IF NOT EXISTS payment_method VARCHAR"`.
   Never edit or remove earlier entries.
3. Deploy. Fresh databases get the column from `create_all`, existing ones from the `ALTER`.

Changing a column type, renaming or dropping needs a manual migration (or Alembic); that is out of scope here.

## Local development
`docker compose up -d` starts Postgres on port 5434. Reset: `docker compose down -v && docker compose up -d`.
`ZZPAY_POSTGRES_URL` (a Neon connection string) overrides the individual host/port/user fields; TLS is enabled for it.

## Status of testing
The test suite runs on in-memory SQLite. The PostgreSQL-specific paths (`ALTER ... IF NOT EXISTS`, `bytea`,
row lock `SELECT ... FOR UPDATE` in save) have **not** been run against a real Postgres/Neon instance in this repo's tests.

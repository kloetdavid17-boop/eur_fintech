# TradeTrack conventions (for coding agents)

Keep the codebase flat and readable. Full invariants are in `CLAUDE.md`; the API contract is
`docs/api.md` and must stay in sync with both `server/` and `client/src/api.ts`.

## Backend (FastAPI + SQLModel)
- Code lives directly under `server/app/`; tables and schemas in `models.py`; one router per resource.
- Every receipt route filters by the authenticated owner and returns 404 for anyone else's receipt.
- Plan limits and prices come from `plans.py` and are enforced on the server at save time.
- Money is `Decimal`, serialized as strings. AI output is never trusted: parse, validate, leave
  unreadable fields `null`. Never invent data. Never claim deductibility or recoverable tax.
- An unconfigured integration (AI, Stripe, Mailgun, SMTP, S3) must say so via `/api/config` and a
  clear error. Never a fake success.
- Tests: `cd server && pytest -q` (SQLite, fake AI). Add a test with every behaviour change.

## Frontend (React + Vite + Tailwind)
- One typed function per API call in `src/api.ts`; components never call axios directly.
- Money stays a string end to end. `null` shows as "Not available".
- Auth is the httponly cookie; no tokens in browser storage.
- Verify with `cd client && npm run build`.

## Docs and hygiene
- Update `README.md` and the relevant `docs/` file in the same change as any feature change.
- Never commit `.env` or secrets. Never run `git reset --hard` / `clean` on a working copy without
  first snapshotting it to a branch.

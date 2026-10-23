# AGENTS.md — TradeTrack

Instructions for any coding agent working on this repository. `CLAUDE.md` has the full invariants;
`docs/api.md` is the API contract; `.claude/rules/conventions.md` has the coding conventions.

TradeTrack is a receipt and expense-management app for Canadian self-employed people and small
businesses (FastAPI + SQLModel + PostgreSQL backend; React 19 + Vite + Tailwind frontend), with a
freemium model (Free: 5 saved receipts a month; Premium: unlimited).

## Never break
1. Receipts are private and owner-only; ownership is enforced in the backend.
2. No invented data: unreadable fields stay `null`; AI output is a suggestion the user confirms.
3. Never state or imply an expense is deductible or tax is recoverable.
4. Tax is province-aware and preserved as printed on the receipt.
5. Plan limits are enforced on the server, counting saved receipts only.
6. No fake integrations: an unconfigured service says so.
7. No secrets in git or the frontend. Don't store card data.
8. Never drop or alter the old ZZPay tables (new tables use the `tt_` prefix).

## Before finishing
`cd server && pytest -q` and `cd client && npm run build`; update `README.md` and the relevant
`docs/` file.

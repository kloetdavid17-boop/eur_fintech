# .claude/instructions.md

Entry point for coding agents in this repo. Authoritative guidance:

- [`../CLAUDE.md`](../CLAUDE.md): invariants, layout, conventions.
- [`../docs/api.md`](../docs/api.md): the API contract shared by backend and frontend.
- [`rules/conventions.md`](rules/conventions.md): coding conventions.
- [`../AGENTS.md`](../AGENTS.md): agent-agnostic summary.

TradeTrack: private, owner-only receipts; no invented data; suggestions not tax advice; province-aware
tax; server-enforced plan limits; honest "not configured" states. Verify with `cd server && pytest -q`
and `cd client && npm run build`, and update `README.md` and `docs/` with every feature change.

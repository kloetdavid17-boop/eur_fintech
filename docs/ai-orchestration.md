# AI agents used

## Which agents

| Agent | Role |
|---|---|
| **Claude** (via Claude Code) | Audited the repository, planned the rebuild, delegated the backend and the frontend to two parallel sub-agents working against one written API contract (`docs/api.md`), then reviewed and tested the result and wrote the documentation. |
| **ChatGPT** | Used earlier, for the original FinTech assignment, for interpreting the brief and drafting prompts. |
| **Product owner (David)** | Chose the product direction (TradeTrack, freemium, Canadian market), wrote the requirements prompt, approved the hosting stack (Render + Neon + Stripe test mode), and decides what is deployed. |

## How the rebuild was done

1. **Audit first.** The existing repository was read before any change. It was half-converted from
   the earlier ZZPay product and could not start (broken imports, an AI module with an undefined
   error class and a mismatched signature, and receipt numbers that would collide after a delete).
2. **One contract.** `docs/api.md` is the single source of truth for routes, JSON shapes and error
   codes. The backend and frontend sub-agents each built to it independently.
3. **Decisions recorded before building**: new `tt_`-prefixed tables so existing Neon data is never
   touched; random receipt ids; usage limits counted on the server from saved receipts; originals kept
   in the database by default; honest "not configured" states for every outside service.
4. **Independent verification.** The lead re-ran the 91 backend tests, rebuilt the frontend, started
   the app against a real PostgreSQL database that already held old-style tables, ran HTTP checks and a
   browser journey, and inspected screenshots. Each of those checks is listed in
   [assignment-mapping.md](assignment-mapping.md), along with what could not be run.

## What went wrong

- During the session a `git reset --hard` run to sync with GitHub discarded uncommitted edits to
  tracked frontend files, which appeared in the folder from a source nobody could identify. Surviving
  files and the written API contract were used to rebuild. Lesson applied: snapshot to a local branch
  before touching a working copy.
- Several things cannot be proven without outside accounts (live AI, payments, inbound email). They
  are built to work when configured and are marked "not run" rather than claimed.

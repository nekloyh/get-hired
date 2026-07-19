# Real accounts: Supabase Auth + Postgres for checkpoints, ledger, exports

**Type:** Slice
**Kind:** enhancement
**Tracked on GitHub:** [#84](https://github.com/nekloyh/get-hired/issues/84) (R-29)

## What to build

The shared bearer token (R-07/#62) is a ≤50-user stopgap. A multi-user product needs identity and
a database that is not per-process SQLite (single-worker constraint, "database is locked" risk,
no per-user isolation). Per remediation decision B2:

- **Supabase Auth** — JWT verified in FastAPI middleware; the WebSocket authenticates via first
  client frame (same transport rule as R-07, never a query param).
- **Postgres** — LangGraph checkpoints move to `PostgresSaver` (the checkpointer seam is the live
  dependency named in ADR 0004's status stamp), the ledger becomes a table, exports gain a
  metadata table. Sessions are owned by user id; export and WS endpoints authorize ownership.
- **Migration** — export all legacy sessions to disk first (R-08/#63), start Postgres clean;
  a script migrates `.skill-ledger.json` → the ledger table.

## Acceptance criteria

- [ ] Two real accounts cannot read each other's sessions, exports, or WS streams (tests).
- [ ] Server restart loses nothing: checkpoints, ledger, exports all survive (integration test
      against a disposable Postgres).
- [ ] Ledger migration script proven on a copied `.skill-ledger.json` fixture.
- [ ] Single-worker guard (R-12/#67) re-evaluated: document which parts the Postgres move lifts
      and which remain.
- [ ] `.env.example` documents the new vars; quickstart still works in no-auth local mode.

## Blocked by

- R-07/#62 (the auth seam this replaces), R-11/#66 (deploy artifact to run Postgres next to).

## Status

**Open.** Spec'd 2026-07-19 from remediation decision B2; scheduled Later (Wave 3). The
`PostgresSaver` migration also closes ADR 0004's "whatever replaces SqliteSaver" pointer.

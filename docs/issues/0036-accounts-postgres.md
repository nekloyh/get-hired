# Real accounts: Supabase Auth + Postgres for checkpoints, ledger, exports

**Type:** Slice
**Kind:** enhancement
**Tracked on GitHub:** [#84](https://github.com/nekloyh/get-hired/issues/84) (R-29)

## What to build

The shared bearer token (R-07/#62) is a trusted-installation boundary, not per-Candidate identity
or a measured capacity limit. Accounts and server-enforced ownership are mandatory before public
launch or private histories between Candidates. They do not block personal/trusted-pilot progress
work. See the canonical [M4 branch](README.md#m4--public-launch-branch-identity-and-operations).

The existing B2 Supabase/Postgres implementation proposal is retained below for evaluation.
**Identity is required; this database migration is conditional.** Before implementation, record
why hosting/auth integration or measured storage needs justify Postgres, plus migration and
restore evidence. SQLite itself is not the reason account authorization is missing.

- **Proposed auth implementation: Supabase Auth** — JWT verified in FastAPI middleware; the WebSocket authenticates via first
  client frame (same transport rule as R-07, never a query param).
- **Conditional Postgres migration** — LangGraph checkpoints move to `PostgresSaver` (the checkpointer seam is the live
  dependency named in ADR 0004's status stamp), the ledger becomes a table, exports gain a
  metadata table. Sessions are owned by user id; export and WS endpoints authorize ownership.
- **Migration if selected** — preserve legacy exports, in-flight checkpoints and history before
  cutover; test on copied synthetic data and retain rollback. Explicitly assign verified owners or
  quarantine unowned data; never infer ownership from a client-supplied Candidate ID. Migrate the
  latest ledger and new Session summaries without inventing earlier history.

## Acceptance criteria

- [ ] Two real accounts cannot read, write, list, export, resume, cancel or delete each other's
      data; include swapped Candidate IDs and expired/revoked credentials (M4 route matrix).
- [ ] Server restart loses nothing: checkpoints, ledger, exports all survive (integration test
      against the selected store; disposable Postgres if migration is selected).
- [ ] If storage changes, migration and rollback are proven on copied synthetic checkpoint,
      ledger and history fixtures; unowned legacy records remain inaccessible.
- [ ] Retention/delete covers all stores and backup expiry; a clean-environment restore preserves
      ownership and does not silently resurrect deleted records.
- [ ] If Postgres is selected, document which storage constraints it lifts and which runtime
      constraints remain; retain the single-worker guard until M6 proves safe coordination.
- [ ] `.env.example` documents the new vars; quickstart still works in no-auth local mode.

## Blocked by

- M2 before implementation; public launch requires M3 and M4 PASS on the final routes/data model.
- Reuse the existing R-07/#62 auth seam and R-11/#66 deployment; they are already present locally.
- Postgres alone does not replace process-local runtime coordination. Keep the worker guard
  unless M6 independently proves cross-process ownership, routing and durability.

## Status

**Open in the local plan; remote status not refreshed.** Reordered 2026-09-13 as conditional
M4, a public-launch blocker rather than a pilot-dashboard prerequisite. #84 remains the tracker.
Auth/storage choice is not promoted to an Accepted ADR by this planning update.

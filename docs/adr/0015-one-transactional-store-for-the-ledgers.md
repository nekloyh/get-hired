# One transactional store for the ledgers (SQLite)

**Status: Proposed — gated on the spike and migration dry-run below. Not applied to code until
Accepted.**

The Skill ledger and the usage ledger (with its fault sidecar) move into **one SQLite database** in
WAL mode, through the standard library's `sqlite3`. Every read-modify-write becomes a `BEGIN IMMEDIATE`
transaction instead of thread lock + `flock` + atomic rename. The public functions the rest of the
code calls stay as they are: `usage.record_usage`, `usage_for_day`, `session_run_spend`,
`reserve_questions`, `reconcile_accounting`, `accounting_gate`, `ledger.load_priors`, `load_states`,
`update_posteriors`, `save_posteriors`. Only the storage under them changes, plus one new reader,
`skill_history`, for #127. LangGraph checkpoints keep their own `SqliteSaver` file, and exports stay
Markdown files.

## Why

Durable state is four stores (`docs/data-model.md` §1), and two of them are hand-rolled files whose
correctness rests on lock choreography:

- **Usage ledger**: append-only JSONL, an `.unreconciled` sidecar for held rows, an inter-process
  `flock`, and two module thread locks (`_FAULT_LOCK`, `_LEDGER_WRITE_LOCK`) that must be taken in
  a fixed order or two threads deadlock. `usage.py` is the largest module in the package.
- **Skill ledger**: one JSON file in which each save replaces a Candidate's whole record, under
  `_SAVE_LOCK` + `flock` + atomic rename.

Defects cluster exactly here, and every fix so far has added a lock:

| Defect | State |
|---|---|
| #123 overlapping reconciles billed held rows twice | fixed: reconcile now runs under the write lock |
| M0-12 a second process erased another Candidate's record | fixed: `flock` around the merge |
| #122 same-Candidate read → fuse → save lost the first writer's evidence | fixed (#158): the read moved inside the lock |
| #125 the rails re-read the whole JSONL ~8× per question | open: no index is possible |
| #126 the usage ledger grows for the life of the deployment | open: no retention |
| #127 one snapshot per Candidate, so no history to chart | open, and blocks #83 |

The next product steps (#127 → #83, then #84's account ownership and deletion) all change this
layer again. Each would add another hand-rolled format or another lock.

## Design under trial

Schema, version 1. Columns are a sketch; the spike fixes them.

- `usage_events(id, ts, day, session, provider, model, kind, prompt_tokens, completion_tokens, fault,
  payload)`, indexed on `(day, provider)` and `(session)`. The rails read `day = today` through the
  index (#125). Retention is a `DELETE … WHERE day < ?` against a configured horizon (#126).
- `usage_faults(id, ts, provider, model, detail, reconciled_at)`. This replaces the sidecar. Reconcile
  is one transaction that inserts the held rows into `usage_events` and stamps `reconciled_at`, so
  #123's double-bill cannot recur by construction.
- `skill_snapshots(id, candidate_id, completed_at, source, session_id, skills_json)`, indexed on
  `(candidate_id, completed_at)`. The current priors are the latest row, so ADR 0006 is unchanged:
  probing surfaces still read decayed Beta priors only. Every row is history (#127), which ADR 0006's
  addendum allows presentation surfaces (#83) to read.
- `meta(key, value)` holds `schema_version`.

Concurrency: WAL lets readers proceed during a write. `busy_timeout` bounds the wait. Every
read-modify-write (`update_posteriors`, `reconcile_accounting`, `reserve_questions`) is a
`BEGIN IMMEDIATE` transaction, and SQLite's own file lock replaces `flock` and the thread locks on
these paths. `coach session` or `coach postmortem` running beside the server stays correct.

Migration: on first open, if the database is empty and the legacy files exist, import both in one
transaction, then **rename** the legacy files to `*.migrated-<date>` (never delete). Keep the legacy
readers for one release so a rollback can still read them. The pilot runbook's backup step switches to
`sqlite3 … ".backup"`, because `cp` of a live WAL database is not a backup.

`#84` (Postgres, accounts) later becomes a port of one schema behind these same functions, instead
of a port of four file formats.

## Gate

Accept when both of these are measured and recorded under `docs/audits/`:

1. **Rail cost.** Measure the rails' read cost and the per-row write cost, JSONL against an indexed
   SQLite table, at the real 1.5k rows and at a synthetic 50k rows.
2. **Migration dry-run on copies of the real ledgers.** Every aggregate the rails and `coach usage`
   read must match, Python against SQL. Every Candidate's `load_priors` must be identical. The
   inputs must be untouched. A restore through SQLite's backup API must reproduce every number.

If (1) shows the indexed read is not materially cheaper, or (2) cannot reproduce today's numbers
exactly, this stays Proposed and the files stay.

*Amended 2026-10-12, before any measurement was taken.* The first version also required
`tests/test_usage.py` to pass **unmodified** on the new backend. That cannot happen: 34 of its 82
tests exercise the JSONL format itself (torn lines, the sidecar, mode bits), and those failure modes
do not exist under SQLite. The requirement moves to the implementation's definition of done (#143).
The 48 behaviour tests pass unmodified. Each format test is replaced 1:1 by a test for its SQLite
counterpart (locked or busy database, corrupt file, full disk mid-transaction), or retired with a
reason, and the mapping is listed in the PR. The #122/#123 race tests are ported, not dropped.

**Measured 2026-10-12** ([`../audits/adr-0015-gate-2026-10-12.md`](../audits/adr-0015-gate-2026-10-12.md)):
(1) at 50k rows one node boundary costs 276 ms with JSONL and 0.73 ms with SQLite, and writes are
equal (≈0.01 ms per row). (2) The import passes with 0 mismatches on both real ledgers, on all 3
Candidates' priors, on a 5,956-row edge-case ledger and on the restored backup, and the inputs are
untouched. Both gate conditions hold. Acceptance is the maintainer's call.

## Considered Options

- **History array inside the Skill-ledger JSON (#127 only).** It is the smallest change for #127. The
  whole-file rewrite grows with history, the lock choreography stays, and #125/#126 are untouched.
- **An append-only events file for Skill snapshots**, consistent with the usage ledger. It copies
  #125's full-scan problem into a second file and still gives no transaction across the two ledgers.
- **Postgres now (#84).** That is the eventual public-launch store, but it adds a server dependency
  to a local single-user tool. Accounts are a launch gate, not a pilot need (`docs/roadmap.md` §1).
  The functions above are the seam that makes Postgres a later port.
- **Keep adding locks.** That is what happened through #123, M0-12 and #122. Each fix was correct,
  and each made the next change harder to reason about.

*Source: GH #143, 2026-10-06. The defect table cites issues, not lines, because the code has moved
since several of them were filed.*

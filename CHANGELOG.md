# Changelog

Notable changes per released tag. The format is loosely [Keep a Changelog]; versions are `0.x`, so a
**minor** bump is where a breaking change lands.

This is one of the three places status may live: GitHub holds work, ADRs hold decisions, and this
file holds what shipped ([rule](docs/issues/README.md#where-status-lives)). Two things it deliberately
does not do. It does not claim a gate is green that is not: a release that ships with a red gate
says so under **Known red**. And it does not list every commit, because `git log <tag>..<tag>` does
that better. It records what a reader upgrading between tags has to know.

Every PR that changes behaviour, a command or a document's location adds a line under
`[Unreleased]`; `scripts/release.sh prepare` turns that section into the release entry.

[Keep a Changelog]: https://keepachangelog.com/en/1.1.0/
[#96]: https://github.com/nekloyh/get-hired/issues/96

---

## [Unreleased]

### Changed

- **Status lives in three places only**: GitHub milestones (work), this file (what shipped) and ADR
  `Status:` lines (decisions) ([#140]). `README.md`, `CLAUDE.md`, `docs/roadmap.md`,
  `docs/issues/README.md` and `docs/pilot-runbook.md` no longer repeat it. `CLAUDE.md` had called the
  judge green at 35/35 for two months after the gate went red.
- **The three root reports are dated records in `docs/audits/`**: `AUDIT.md` →
  `forensic-audit-2026-09-14.md`, `QA-REPORT.md` → `qa-report-2026-09-15.md`, `MILESTONE-REPORT.md` →
  `milestone-v0.1.0-pilot-2026-09-15.md`. The 2026-09-13 planning pass left `docs/issues/README.md`
  for `docs/audits/implementation-plan-2026-09-13.md`. `docs/audits/README.md` maps the old names.
- **Work is tracked as `#NN` in three milestones**: `v0.3.0 Stable`, then `v0.4.0 Foundation`;
  `Later` is frozen. The old `Now`/`Next` wave milestones are retired.
- **`docs/roadmap.md` §2 is corrected**: `coach bench` scores fixed answers, so a judge change costs
  judge tokens. A local simulated candidate cannot make it cheaper; screening a wording on a few cases
  before confirming on all 35 can ([#145]).

### Added

- **CI runs every Monday** and on demand (`workflow_dispatch`), so a pause cannot hide a calendar,
  toolchain or dependency break ([#138]). GitHub disables a public repo's schedule after 60 days with no
  activity. Dependabot alerts and security fixes are on; version-update PRs are not.
- **A judge fingerprint and `judge.lock`** ([#141]): a sha256 of the exact requests the judge would send
  for three canonical answers covering every `evaluate` request path. `tests/test_judge_lock.py` fails on
  any prompt, anchor, schema, escalation-policy, model, temperature or endpoint change. `coach bench`
  prints the fingerprint, says whether it matches the lock, and stamps it into the report. It found
  one judge change that had shipped unbenched: #129 removed `"self_critique":null` from the three
  Panel prompts in 0.2.0. The 2026-09-15 bench never escalated, so its measurement still holds.
- **ADR 0009 addenda (e) and (f) are on `main`** ([#141]). They were cited as binding but existed only
  on the unmerged #96 branch. Addendum (g) records the lock.
- **`scripts/release.sh`**: `prepare <ver>` edits only `pyproject.toml`, `uv.lock` and this file;
  `tag <ver>` gates, tags and pushes the tag in the same step ([#140]).

### Fixed

- **Two writers for the same Candidate no longer lose each other's Skill evidence** ([#122]). A finishing
  Session (web or CLI) and a `coach postmortem` each read the Candidate's ledger record outside the
  lock, merged onto it, and saved, so the second save replaced the first's Skills, with no exception
  and no log line. `ledger.update_posteriors` now runs load → update → save as one critical section
  under the existing thread lock and flock, and both writers go through it.

[#122]: https://github.com/nekloyh/get-hired/issues/122
[#138]: https://github.com/nekloyh/get-hired/issues/138
[#140]: https://github.com/nekloyh/get-hired/issues/140
[#141]: https://github.com/nekloyh/get-hired/issues/141
[#145]: https://github.com/nekloyh/get-hired/issues/145

---

## [0.2.0] — 2026-09-20

Dead code removed, the two 1,400-line files split, and the replay bench made measurable. No
behaviour change was intended anywhere in this release; where one was possible, it is named below.

### Removed — breaking

- **`coach ingest-resources`, `session --resource-store` and `session --resource-persist-dir`** are
  gone with the Chroma resource store ([#130]). The store was never on a default path — the web API
  hardcoded `memory`, both CLI call sites defaulted to it, and there was no `Settings` field and no
  `"auto"` branch — and the catalog it indexed is two entries per Skill behind a hard `skill=`
  filter, so an embedder had nothing left to rank. The Study Planner now always uses
  `InMemoryResourceStore`. **This is the whole reason this release is 0.2.0 and not 0.1.1.**
- **`SelfCritiqueTrace` and the `self_critique` field** on `Evaluation` ([#129]). Nothing has been
  able to produce a value for months. Session exports lose exactly three `"self_critique": null`
  lines; the replay artifact `data/replay/deep-learning-strong.json` keeps its five on purpose — it
  is a drifted checkpoint, and reading it is the absent/extra-key test.
- **`docs/reference/`** (1,261 lines): the two archived MVP planning docs every agent was told to
  load and then told not to implement from. `git log --diff-filter=D -- docs/reference` finds them.

### Added

- **Replay artifacts record the pack they ran against** ([#113]), and `replay_decision` feeds that
  bank back into the decision. Before this, every replay silently measured the built-in bank:
  the same `final_state` replayed through two artifacts differing only in the recorded pack yields
  `advance_plan` against one and `extra_question` against the other. `REPLAY_ARTIFACT_VERSION` is
  now `2`; version 1 artifacts still read.
- **`scripts/gate.sh`** — every check CI runs, one `PASS`/`FAIL` per line and a single `GATE: OK`.
  It exists because the repeated failure here is an `&&` chain stopping early, or a `tail -n` that
  eats mypy's verdict line.
- **CI runs the two browser specs**, and `.github/e2e-ran.sh` fails the job on `skipped > 0` — four
  `test.skip` branches meant a skipped spec reported green. `COACH_E2E_MODE` defaults to `demo`, so
  the reconnect spec no longer needs a funded API key.
- **`ruff format --check` gates CI** ([#131]); 26 files had drifted.
- **Session threads are named `session-<id>`**, so a `faulthandler` or `py-spy` dump on a wedged
  deployment names the Session instead of `Thread-7`.

### Changed

- **`web_api.py` 1,375 → 329 lines** and **`cli.py` 1,392 → 629** ([#124]), split along the seams the
  issue names: `web_protocol`, `web_runtime`, `web_ops`, `web_session_driver`, `cli_parser`,
  `cli_session`. Proven behaviour-preserving by `tests/test_serde_golden.py` — all six goldens
  regenerate byte-identical — plus an unchanged suite, a live `/api/health`, and a full
  `coach session --scripted` run. **If you monkeypatch into these modules, patch the module that
  *reads* the name:** `STALE_RUNTIME_JOIN_SECONDS` is read in `web_runtime`, and
  `diagnose_or_degrade` is called from both `cli` and `cli_session`.

### Fixed

- **`reconcile_accounting` rewrote the fault sidecar unlocked and non-atomically** ([#123]), which
  could lose a billed row under a concurrent writer. It now holds the module's own write lock and the
  inter-process `flock`, and publishes through `atomic_write_text`.
- **A damaged checkpoint database is reported once, with a remedy**, instead of N tracebacks that
  never say what is wrong. The sweep stops and says plainly that resume is not reliable until the
  file is repaired (`PRAGMA integrity_check`, `REINDEX`, or delete and start clean).
- **The suite no longer writes thousands of log records into a closed stream** ([#134]). Measured:
  **2,441** per green run, of which two to four surfaced as a `--- Logging error ---` block. The
  cause was `cli.main`'s `logging.basicConfig(force=True)` binding a root handler to a `capsys`
  stream pytest then closes — not, as the issue assumed, a late Session thread. Seventeen tests did
  also leave a Session thread running, and now join it.
- **A regression test with a hardcoded future date** stopped being a time bomb: it stamped
  `2026-09-15` into a ledger row that only counts toward the current UTC day, so it went red on its
  own four days later.

### Known red

- **Judge calibration bench: 34/35** ([#96]). `depth` and `system_thinking` have no anchor at 3, and
  a missing middle BARS anchor is a measured language-fairness bug, not a style question — the same
  answer split 2 (EN) vs 4 (VN) on `correctness` before its `3` was added. The gate is median-of-k
  (k=3) at production temperature and **a band is never widened to turn a red green**.
- **`.env`'s `COACH_ALLOWED_ORIGINS` is the local-dev pair** (`http://localhost:5173`,
  `http://127.0.0.1:5173`). It must be the production origin before any deploy —
  `docs/pilot-runbook.md` §1 line 2.

[#113]: https://github.com/nekloyh/get-hired/issues/113
[#123]: https://github.com/nekloyh/get-hired/issues/123
[#124]: https://github.com/nekloyh/get-hired/issues/124
[#129]: https://github.com/nekloyh/get-hired/issues/129
[#130]: https://github.com/nekloyh/get-hired/issues/130
[#131]: https://github.com/nekloyh/get-hired/issues/131
[#134]: https://github.com/nekloyh/get-hired/issues/134

---

## [0.1.0-pilot] — 2026-09-15

The first tag a trusted pilot could run against: M0a, M0b and M1 complete. Full record in
[`docs/audits/milestone-v0.1.0-pilot-2026-09-15.md`](docs/audits/milestone-v0.1.0-pilot-2026-09-15.md); what to check before letting anyone in is
[`docs/pilot-runbook.md`](docs/pilot-runbook.md).

- **Usage accounting is durable and fails loud** — a metered call is refused when the ledger cannot
  be written, rather than spending silently off the books.
- **Bounds everywhere the Session takes input** — answer length, frame size, output tokens, queue
  depth, active Sessions, and lifecycle cleanup.
- **Budget exhaustion suspends and resumes** instead of writing a zero-evidence `failed` question
  (ADR 0005's third category).
- **A durable answer survives a crash**, driven through the real compose stack rather than asserted.
- **Full-stack nginx/TLS dry-run**, which found two defects and fixed both: WebSocket frames were
  unbounded by nginx, and nginx reported no health of its own.

[Unreleased]: https://github.com/nekloyh/get-hired/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/nekloyh/get-hired/compare/v0.1.0-pilot...v0.2.0
[0.1.0-pilot]: https://github.com/nekloyh/get-hired/releases/tag/v0.1.0-pilot

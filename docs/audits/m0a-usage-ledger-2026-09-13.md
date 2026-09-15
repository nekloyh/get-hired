# M0a / F1 — writable durable usage ledger, visible accounting failure

**Date:** 2026-09-13 · **Milestone:** M0a (first reviewable vertical slice, `docs/issues/README.md`)
· **Work ID:** F1 · **Verdict: GO for M0a.**

M0a green certifies this slice only. It does **not** certify the rest of M0 (F2/F3 — bounds,
admission, quota orchestration remain open), and it does not authorise public launch.

## 1. Provenance

| Field | Value |
| --- | --- |
| Base commit | `2dac711b3b9efc292406222e369fcd0a45301872` (branch `main`) |
| Working tree | dirty; uncommitted. `git diff HEAD -- .env.example Dockerfile docker-compose.yml docs/deploy.md src/interview_coach tests` → sha256 `6171259282e65e6f7b2f721372b5b3f232aee58a2ae31b2d6a73c1d949acfeac` |
| Not part of this slice | `CLAUDE.md`, `README.md`, `docs/issues/0035/0036/0037`, `docs/issues/README.md`, `docs/audits/baseline-2026-09-02.md`, `docs/research/` were already modified/untracked before this work and were left untouched. |
| Image under test | `coach-m0a:test`, built from this tree, `sha256:17cbd074843b7379ccfe0d19b29e10e183f8b5ba28821fc5ec8974ab4bbcc560` |
| Runtime | Docker 29.7.2, Linux 7.1.8 (CachyOS), Python 3.12.13, container UID **10001** |
| Role → provider/model | **N/A — offline only.** No paid API was contacted. The fake is the HTTP transport alone; the real `OpenAIClient`, its real `_create()` and the real `record_usage()` run. |
| Prompt hash / decoding params / pack version / eval-set hash | **N/A** — this slice touches no prompt, no judge and no pack. No calibration or replay gate applies (nothing about scoring changed). |
| Fake provider | deterministic `prompt_tokens=100`, `completion_tokens=20` per call (`scratchpad/m0a/probe.py`, reproduced in §6) |

## 2. The defect, reproduced before it was fixed

Not inferred from code reading — executed. The pre-fix `usage.py` and `llm.py` (`git show HEAD:…`)
were bind-mounted over the image's installed source, `COACH_USAGE_LEDGER` unset so the repo-anchored
default applied, and the probe made 3 fake metered calls:

```
usage ledger write failed ([Errno 13] Permission denied: '/app/logs'); dropping entry {...}   (x3)
{
  "ledger": "/app/logs/usage-ledger.jsonl",
  "provider_calls_actually_made": 3,
  "ledger_rows": null,
  "usage_for_day": {},
  "remaining_today_openai": 2500000,
  "uid": 10001
}
```

360 tokens spent, **zero** recorded, budget reported **pristine**, exit code 0. Root cause, also
executed in the image: `DEFAULT_LEDGER_PATH` resolves to `/app/logs/usage-ledger.jsonl`; `/app` is
`root:root 0755`; `mkdir /app/logs` as uid 10001 → `PermissionError`. Compose set every other state
path but not this one.

This is the failure mode the plan's baseline table called an *Inference*. It is now measured.

## 3. What changed

**Configuration**

- `Dockerfile`: `COACH_USAGE_LEDGER=/app/state/usage-ledger.jsonl` in `ENV`, so a bare
  `docker run <image>` is correct too, not only compose.
- `docker-compose.yml`: the same value in the `environment:` block, which overrides `.env`'s
  host-path copy of the key (verified in §4).
- `.env.example`, `docs/deploy.md` §5/§7/§8: the path, the two failure conditions and their remedies.

**Behaviour** (`usage.py`, plus four one-line seams)

- A failed ledger write no longer returns quietly. It latches an **accounting fault** — in process
  (so it works when nothing can be written) *and* in a sidecar `…​.jsonl.unreconciled` beside the
  ledger (so it outlives a process; the CLI is one process per invocation).
- Two conditions are kept apart, because their honest remedies differ:
  - **before any call** — `check_ledger_writable()`: the path cannot be appended to *or read*.
    Nothing is unaccounted for. Fixing the path clears it, with no bookkeeping to repair.
  - **after a billed call** — `record_usage()` could not write a token row. The day's spend is
    **undetermined**, which is not zero. The unwritten row (token counts included) is parked in the
    sidecar and the condition stays **UNRECONCILED** until `coach usage --reconcile` *replays* it
    into the ledger. Reconciliation folds the spend back in; it never forgives it.
- Enforcement, at three depths:
  - `_OpenAICompatibleClient._create()` — the call boundary. Refuses with `AccountingUnavailable`
    before issuing the request. The writability probe runs once per ledger path per process (only
    *successes* are memoised, so an operator who repairs the path is unblocked without a restart);
    the latch is checked every call. This is what covers callers that never pass through a start
    gate — the bench, the forge, one-off commands.
  - `start_refusal_reason()` / `question_cap_reason()` / `budget_stop_reason()` — the existing
    rails, which are all arithmetic over this file. They now check accounting *first*: a rail that
    counts rows before asking whether the file can be counted is reading an unknown number.
  - `question_node` and `diagnose_or_degrade` — typed re-raises, the same shape as the existing
    `except CandidateIntent: raise`. A refusal to spend is a fact about our bookkeeping, not
    evidence about the Candidate; without these it becomes a zero-evidence `failed` question and the
    Session *advances* — the fake-evidence corruption ADR 0005 forbids.
- `record_usage()` still never raises. A ledger write happens mid-judgment, after the provider has
  answered; crashing there is worse than a late row. What changed is what happens *next*.
- Two reader bugs found by the new tests and fixed: `_all_rows()` raised `IsADirectoryError` on an
  unreadable ledger (a rail crashed rather than blocked), and `question_cap_reason()` — which the
  web start path evaluates *first* — counted rows before any health check.

**Test isolation** (`tests/conftest.py`): every test now gets its own `COACH_USAGE_LEDGER` and a
reset accounting latch. This also closes finding 19 of the 2026-09-02 baseline (fixtures appending
`mimo/test-model` rows into the operator's real ledger — fabricated evidence about spend).

## 4. Acceptance criteria — results

All results below were re-executed against the final tree (image
`sha256:17cbd07…`) after a late correctness fix to `--reconcile`'s partial-failure path. Container
runs use the fixed image as uid 10001 on **disposable** volumes (`m0a-state`,
`m0a-midrun`, `m0a-rails`, `m0a-prefix-state`), created for this run and removed afterwards. No real
state was read or written.

| # | Criterion | Result | Evidence |
| --- | --- | --- | --- |
| 1 | One fake metered call is accounted exactly once | **PASS** | `ledger_rows: 1`, `usage_for_day.openai = {calls:1, prompt:100, completion:20, total:120}`, `remaining_today 2,500,000 → 2,499,880`, `ledger: /app/state/usage-ledger.jsonl`, `uid: 10001` |
| 2 | Ledger and budget balance survive restart **and container replacement**, volume retained | **PASS** | 5 calls → 600 tokens. `docker restart` → 600. `docker rm` + a fresh container (`hostname 61451da30c8a`) on the same volume → 600. File on the volume: 5 JSONL rows, `coach coach`. |
| 3 | A deliberately unwritable path fails visibly and stops metered work | **PASS** | Old default `/app/logs/usage-ledger.jsonl` → `AccountingUnavailable`, **`provider_calls_actually_made: 0`**. `coach usage` leads with `ACCOUNTING: …`. `coach session` → `Refusing to start this Session: Usage accounting is unavailable …`, **exit 2**, Diagnostic never reached. |
| 4 | An accounting write failing *after* a call neither ignores the cost nor keeps calling | **PASS** | Ledger broken mid-run: the billed call's row is parked (`~120 token(s) held in …​.unreconciled`), the **next call is refused** (`calls` stays at 2), repairing the path alone leaves `still_blocked: true`, `--reconcile` → `Reconciled 1 held ledger row(s) … (~120 token(s) restored)` and the day total goes from `{}` to 120. |
| 5 | Existing budget rails are not broken | **PASS** | Daily rail still refuses with its own wording (`~400 tokens remain … estimated at ~6,200 … resets at 00:00 UTC`). Full suite **833 passed**, 9 deselected, 2 xfailed, 7.6 s. `ruff check` and `mypy` clean. |
| — | Demo stays usable without an API | **PASS** | A demo Session completes in-container with **no provider configured** *and* `COACH_USAGE_LEDGER` pointed at an unwritable path: `session_completed`, `status: complete`, zero ledger rows written. |
| — | Compose precedence | **PASS** | `.env` carrying `COACH_USAGE_LEDGER=logs/usage-ledger.jsonl` + the `environment:` block → `docker compose config` resolves `/app/state/usage-ledger.jsonl`, and the container reads that value. |

### Offline test coverage added

`tests/test_usage.py` (+15), `tests/test_llm.py` (+6), `tests/test_web_api.py` (+3),
`tests/test_cli.py` (+4), `tests/test_supervisor.py` (+1). Targeted run: **323 passed**, 6.0 s.
Named invariants pinned: an unrecorded billed call is never counted as zero; a repaired path does
not forgive it; reconciliation restores the true day total; an accounting refusal never becomes a
`failed` transcript item; the gate is not swallowed by `chat_json`'s `(ValidationError, ValueError)`
retry; a refusal is not a provider failure, so the router does not spend a *second* provider's
allowance working around our inability to count; and a `--reconcile` run before the path is fixed
neither loses the held row nor replays it twice when the operator retries.

## 5. Limitations — what this run does **not** prove

1. **No live provider was used.** Fake-provider evidence proves mechanics only. Real usage-field
   shapes, partial responses and provider-side billing are untested here (by design: no run budget).
2. **Concurrency is untested.** Single-threaded probes only. The latch is lock-guarded and appends
   are `O_APPEND` single-writer, but two Sessions racing on one broken ledger was not measured. The
   plan assigns concurrent admission to **M0b/F3**.
3. **One residual hole, bounded and known.** If the ledger *and* its sidecar are both unwritable,
   the fault is held in memory only; a process restart forgets that a specific call went
   unrecorded. Metered work still stays blocked, because the same unwritable path fails the pre-call
   probe — so the system never resumes spending blind. What is lost is the *record* that a past call
   was unaccounted for. Pinned by
   `test_a_fault_that_cannot_even_be_parked_still_blocks_this_process`.
4. **Reconciliation is manual and trusts the operator's timing.** `--reconcile` replays the parked
   rows; it cannot recover a fault that carries no row (case 3). It says so rather than rounding to
   zero (`"… stays unknown, not zero"`).
5. **In-flight billed calls can still complete after a refusal.** The gate stops the *next* call;
   it cannot recall one already sent. This is the same bounded liability the plan records for
   quota stops — not a hard provider invoice cap.
6. **Not re-executed:** the browser E2E, the calibration bench, the replay bench. None are gated by
   this slice (no prompt, judge, or pack changed) and re-running them would not be evidence about
   accounting.
7. `docker restart` and container replacement were exercised with the state volume retained, as the
   criterion specifies. Volume **loss** is still total loss of the balance — §5 of `docs/deploy.md`
   says so, and the backup command there now covers this file.

## 6. Reproducing this

Probe (`probe.py`) and demo probe kept in the session scratchpad, not committed: they are
disposable harness, and `tests/` is excluded from the image on purpose. Both are reconstructible
from the descriptions above; the probe fakes only `openai.OpenAI` (a `create()` returning a fixed
`usage` of 100/20) and injects it into a real `OpenAIClient`.

```bash
docker build -t coach-m0a:test .
docker volume create m0a-state

# AC1: one fake metered call, stock image config
docker run --rm -v "$PWD/probe.py:/probe.py:ro" -v m0a-state:/app/state \
  --entrypoint python coach-m0a:test /probe.py call 1

# AC2: restart, then replace the container, volume retained
docker run -d --name m0a-app -v m0a-state:/app/state coach-m0a:test
docker exec m0a-app coach usage
docker restart m0a-app && docker exec m0a-app coach usage
docker rm -f m0a-app
docker run -d --name m0a-app2 -v m0a-state:/app/state coach-m0a:test
docker exec m0a-app2 coach usage

# AC3: the old default path, which uid 10001 cannot write
docker run --rm -v "$PWD/probe.py:/probe.py:ro" -v m0a-state:/app/state \
  --entrypoint env coach-m0a:test -u COACH_USAGE_LEDGER python /probe.py refuse 3

# AC4: the ledger breaks under a running process, after a billed call
docker run --rm -v "$PWD/probe.py:/probe.py:ro" -v m0a-midrun:/app/state \
  --entrypoint python coach-m0a:test /probe.py midrun

# the defect, on the pre-fix code
git show HEAD:src/interview_coach/usage.py > prefix/usage.py
git show HEAD:src/interview_coach/llm.py   > prefix/llm.py
docker run --rm -v "$PWD/probe.py:/probe.py:ro" \
  -v "$PWD/prefix/usage.py:/app/src/interview_coach/usage.py:ro" \
  -v "$PWD/prefix/llm.py:/app/src/interview_coach/llm.py:ro" \
  -v m0a-prefix-state:/app/state \
  --entrypoint env coach-m0a:test -u COACH_USAGE_LEDGER python /probe.py call 3

docker rm -f m0a-app2; docker volume rm m0a-state m0a-midrun m0a-prefix-state
```

Offline: `uv run pytest -q` · `uv run ruff check` · `uv run mypy`.

## 7. Trackers

`#66` (R-11 deploy artifact) and `#80` (R-25 budget rails) are both **CLOSED**; this slice extends
their output rather than reopening them, and no open issue covers the ledger path. **No new issue
was filed** — the work is done here, and filing one for completed work would duplicate the
backlog. `#119` (a terminal `insufficient_quota` inside a question still writes one zero-evidence
`failed` item) stays **open and untouched**: it is a quota defect, assigned to M0b/F3. The typed
re-raise added here is for `AccountingUnavailable` only and does not fix or overlap it.

## 8. Decision

**GO for M0a.** All five acceptance criteria pass against a real container, at the real UID, on
disposable volumes, with the defect reproduced beforehand on the pre-fix code. The residual risks in
§5 are recorded, bounded, and none of them lets the system resume metered spending while accounting
is broken.

M0b (F2 bounds and lifecycle, F3 atomic admission and quota suspension) is unaffected by this
verdict and remains a separate gate. Nothing here permits public launch.

# Issue 0015 Audit — Groq Cutover Execution + Live Validation

Date: 2026-07-06

## Scope

Executed the Groq cutover that issue 0004 built the mechanism for but never happened (per the
2026-07 stability audit), then live-validated it end-to-end, including the four issues
(0016/0018/0019/0020) that had only ever been proven with fakes.

## Config changes

- `.env` moved from the legacy `LLM_PROVIDER=mimo` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`
  scheme to the documented `PRIMARY_PROVIDER` / `MIMO_*` / `GROQ_*` scheme. `GROQ_MODEL` had never
  been set at all — `GROQ_API_KEY` alone was a silent no-op, since `ProviderSettings.configured`
  requires `api_key AND base_url AND model`.
- Model chosen: `llama-3.3-70b-versatile`. Compared against `llama-3.1-8b-instant` and
  `openai/gpt-oss-120b` on Groq's free-tier limits (fetched live from `console.groq.com/docs/rate-limits`):
  llama-3.3-70b-versatile has the highest TPM of the three (12K vs 6K vs 8K) despite being the
  largest model, and 1K RPD is far more than a personal coaching tool needs.
- Removed the legacy `LLM_*` alias surface from `config.py` (`src/interview_coach/config.py`):
  `primary_provider`/`mimo_*`/`groq_*` now bind only to their documented names
  (`PRIMARY_PROVIDER`, `MIMO_API_KEY`/`MIMO_BASE_URL`/`MIMO_MODEL`, `GROQ_API_KEY`/`GROQ_BASE_URL`/`GROQ_MODEL`).
  This alias path is what silently kept the live path pointed at expired MiMo — no test depended on
  it, and README/`.env.example` never documented it, so removal (not documentation) was the fix.

## Commands run

```bash
uv run python scripts/smoke_issue_0009.py       # client-layer live smoke
uv run pytest -m live                            # 5 passed — first time ever against real Groq
uv run pytest -q                                 # 165 passed, ruff clean, after the config.py change
```

`pytest -m live` result (first-ever non-MiMo run of this suite):

```text
tests/test_evaluator.py::test_live_weak_scores_below_strong PASSED
tests/test_interviewer.py::test_live_interviewer_uses_lookup_concept_tool PASSED
tests/test_microloop.py::test_live_strong_seed_resolves_high PASSED
tests/test_microloop.py::test_live_follow_up_does_not_re_ask_the_question PASSED
tests/test_supervisor.py::test_live_session_runs_through_graph_and_logs_supervisor_reasoning PASSED
5 passed, 167 deselected
```

## Live re-validation of issues 0016/0018/0019/0020

Each of these was previously closed on fake/simulated evidence only. Re-run live against real Groq:

- **0018** (Ctrl-D/EOF abort): `coach session` with closed stdin at the first prompt against the
  live provider — exit code 2, designed message, checkpoint shows `transcript len: 0`,
  `is_complete: None`, no export written.
- **0019** (resume edge cases): started a live scripted session, killed it after 2/5 questions,
  waited 99 real seconds against a 25s `--max-elapsed-seconds` budget (4x over), then `--resume`d —
  the Session still asked and resolved a full further question before ending, proving the clock
  reset rather than force-completing on stale elapsed time. Recap printed with no history replay.
  Also confirmed live: unknown `--resume` id gives a friendly one-liner listing known ids
  (exit 2), and the in-flight guard refuses a non-`--resume` restart over an incomplete checkpoint
  (exit 2).
- **0020** (Supervisor transport-error backstop): started a live session, let Diagnostic + 3
  questions complete for real, killed it, then broke `GROQ_MODEL` and `--resume`d (resume skips
  Diagnostic, re-entering the graph directly at the Supervisor) — a genuine Groq 404 into an
  expired-MiMo-fallback 401 hit `decide_next_move` directly. Session completed (exit 0) via
  `advance_plan (deviation=False) — Deterministic fallback after a provider transport error: move
  to the next Topic Plan entry.` `question_node` and `study_plan_node`'s own backstops fired too
  (real `AuthenticationError` recorded honestly in transcript and Study Plan sections). No fake
  involved — a real double-provider failure, real backstop.
- **0016** (web kill/restart/reconnect): the prior close-out explicitly noted the manual walkthrough
  was "supported but not scripted as an automated e2e." Wrote `web/e2e/reconnect-flow.spec.ts`
  (`npm run test:e2e:reconnect`), which spawns `coach api` on a dedicated port, drives a **live**
  Session in the browser, hard-kills the backend's whole process group mid-question, asserts the
  `SessionAlert` disconnected banner, restarts the backend, clicks Reconnect, and drives the Session
  to a visible Final Report. Passing (1.7m).

## Findings during validation (not part of 0015's original scope)

- **New bug**: `diagnose()` in `cli.py` (`_cmd_session`, before the graph starts) has no error
  handling — any transport/rate-limit failure there crashes with a raw traceback and exit 1, unlike
  `question_node`/`study_plan_node`/`decide_next_move`, which all degrade. Hit live twice: once via
  a broken `GROQ_MODEL`, once via a genuine Groq 429 (see below). Filed as issue 0030.
- **Real Groq free-tier rate limit hit during this validation**: the smoke test + `pytest -m live` +
  ~7 full/partial live sessions run in this session alone consumed 98,352/100,000 daily tokens
  (TPD) for `llama-3.3-70b-versatile` — a 429 fired organically partway through, cascading into the
  issue-0030 crash above. `llama-3.1-8b-instant` (separate, untouched TPD budget) was used
  temporarily just to drive the 0016 e2e test; `GROQ_MODEL` was restored to
  `llama-3.3-70b-versatile` immediately after.
- The `uv run coach api` process is a wrapper around a child `coach`/uvicorn process (confirmed via
  `pstree`) — killing only the wrapper PID (or sending `SIGKILL`, which cannot be forwarded the way
  `SIGTERM` sometimes was) leaves the real server listening. `reconnect-flow.spec.ts` spawns it
  `detached: true` and kills the whole process group.

## Result

Pass. Acceptance criteria met:

- [x] `.env` matches the documented scheme; a live `coach session --scripted --max-questions 1`
      completes on Groq end-to-end (verified repeatedly with 2–5 questions, including tool calls,
      Study Plan, and export)
- [x] `uv run pytest -m live` passes against Groq with the tests actually executing (5 passed, 0
      skipped)
- [x] This audit entry
- [x] The legacy `LLM_*` alias path removed from `config.py` (not documented — it was never
      documented, and was the exact mechanism that caused the silent MiMo/no-op incident)
- [x] README already matched the final (`PRIMARY_PROVIDER`) scheme; no changes needed

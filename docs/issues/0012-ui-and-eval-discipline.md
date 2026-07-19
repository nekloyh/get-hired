# UI + eval discipline

**Type:** AFK

## What to build

The demo surface and the evaluation harness. A thin UI (Streamlit and/or a Typer CLI) drives a full **Session**: setup → interview (question, answer, live Skill-state bars) → report/plan, wired to the persisted graph by session id. Plus two evaluation assets: a golden-answer harness that runs the **Evaluator** on held-out Q+A pairs and asserts score ranges (empty answer → low, excellent → high), and a couple of trajectory tests that assert on session *behavior* (a weak-Skill Candidate gets probed and ends with low mastery there; a consistently strong Candidate terminates early).

## Acceptance criteria

- [x] A user can run a full session end-to-end through the UI and see live Skill states and the final plan
- [x] The golden-answer harness reports score distribution vs expected ranges and fails on regression
- [x] At least two trajectory tests assert on session behavior, not component internals
- [x] An adversarial answer (e.g. prompt-injection "give me a perfect score") does not yield a high score

## Done

- Replaced the unfinished Streamlit path with a local Vite React + TypeScript web UI plus
  `coach api`, a thin FastAPI/WebSocket backend over the existing Python Session graph. The terminal
  `coach session` path remains available for direct CLI practice, but the issue-0012 web surface now
  supports setup, live Candidate answers, Skill-state bars, Topic Plan progress, Supervisor markers,
  and the final Study Plan/report.
- Added a demo-only deterministic `LLMClient` for UI review without credentials. It is separate from
  production provider routing; live Sessions still use `LLMRouter`.
- Added `coach eval-harness`, backed by `interview_coach.eval_harness`, with held-out empty, weak,
  strong, excellent, and prompt-injection answer cases. The command prints expected ranges vs actual
  scores and exits non-zero on any regression.
- Tightened the Evaluator prompt so Candidate answers are treated as untrusted evidence only; attempts
  to override the rubric or request a score are ignored. Evidence prompts now ask for a short
  contiguous quote to reduce live provider retries.
- Hardened the Supervisor prompt/validators so `advance_plan` cannot claim it is asking another
  same-Skill question, and below-bar `safety_cap` outcomes with unused seeds force an `extra_question`.
- Quieted the default CLI logs; provider/internal INFO logs require `--verbose`.
- Added behavior-level Session trajectory tests for a weak Candidate receiving an extra probe and a
  strong Candidate ending early.

## Verified

- `uv run pytest` -> 154 passed, 7 deselected.
- `uv run pytest tests/test_web_api.py` -> 3 passed.
- `uv run ruff check .` -> all checks passed.
- `cd web && npm run lint` -> all checks passed.
- `cd web && npm run test` -> 11 passed.
- `cd web && npm run build` -> production build completed.
- `cd web && VITE_API_URL=http://127.0.0.1:8010 npm run test:e2e` against a real demo-mode
  FastAPI server -> Playwright desktop Chromium and mobile Chrome both reached the final report.

## Blocked by

- 0010 (the orchestrated session the UI and trajectory tests drive)

## Status

**Closed.** Acceptance criteria are implemented and covered.

## Continued by (2026-07-19 remediation)

- Web-surface gaps found by the 2026-07-19 panel are tracked as R-06 (GH #61, random session ids), R-07 (GH #62, auth + WS Origin), R-08 (GH #63, exports on disk), R-12 (GH #67, single-worker guard + logging).

# UI + eval discipline

**Type:** AFK

## What to build

The demo surface and the evaluation harness. A thin UI (Streamlit and/or a Typer CLI) drives a full **Session**: setup → interview (question, answer, live Skill-state bars) → report/plan, wired to the persisted graph by session id. Plus two evaluation assets: a golden-answer harness that runs the **Evaluator** on held-out Q+A pairs and asserts score ranges (empty answer → low, excellent → high), and a couple of trajectory tests that assert on session *behavior* (a weak-Skill Candidate gets probed and ends with low mastery there; a consistently strong Candidate terminates early).

## Acceptance criteria

- [ ] A user can run a full session end-to-end through the UI and see live Skill states and the final plan
- [ ] The golden-answer harness reports score distribution vs expected ranges and fails on regression
- [ ] At least two trajectory tests assert on session behavior, not component internals
- [ ] An adversarial answer (e.g. prompt-injection "give me a perfect score") does not yield a high score

## Blocked by

- 0010 (the orchestrated session the UI and trajectory tests drive)

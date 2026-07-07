# Simulated Candidate + Supervisor replay bench

**Type:** AFK
**Kind:** enhancement

## What to build

The 154-test suite runs 100% against fakes, and nothing anywhere evaluates the *loop* — whether a
whole Session converges on the truth about a candidate. Close the eval stack: the calibration
bench (0022) calibrates the judge; this calibrates the orchestrator.

- A **persona-driven LLM Candidate** with a ground-truth mastery profile (e.g. "strong
  deep_learning, weak mlops, rambles when unsure"), plugged into the existing Candidate seam the
  scripted fixture uses today.
- A runner drives a **full unattended Session** (offline graph; live judge optional) and asserts
  **trajectory properties**, not per-call outputs: the final posterior mastery *ordering* matches
  the persona's ground truth, and the Supervisor terminates early on the persona's strong Skill
  instead of burning budget there.
- Dump the checkpointed trajectory as the first **versioned replay artifact**, and re-run the
  Supervisor's decision node over it with a different model as the counterfactual demo — the
  seed of decision-level regression testing.

## Acceptance criteria

- [x] ≥1 persona Candidate completes a full Session unattended through the existing seam
- [x] Trajectory assertions pass: posterior ordering vs ground truth; early-termination on the
      strong Skill
- [x] The trajectory checkpoint is saved as a versioned replay artifact, and the decision node
      can be re-run over it in isolation (counterfactual model swap demoed once)
- [x] Documented alongside 0022 as the two halves of the eval stack (judge calibration + loop
      calibration)

## Blocked by

- 0015 (a live judge is needed for the meaningful closed-loop run; the persona + assertions can
  be developed against fakes first)

## Done

- `replay.py`: `Persona` (ground-truth per-Skill mastery), `PersonaCandidate` (LLM-backed, answers in
  character for the probed Skill via its own client so it never draws on the judge budget), and
  `persona_candidate_factory` plugging into the existing `candidate_factory` seam.
- `run_persona_session` drives a full unattended Session (deterministic offline Topic Plan; judge is
  the configured provider or, offline, a content-based simulated judge); trajectory helpers
  `posterior_masteries`, `probed_ordering`, `ground_truth_ordering`, `attempts_by_skill`.
- Versioned replay artifact: `dump_replay_artifact` / `load_replay_artifact` (schema `version` 1) and
  `replay_decision`, which re-runs `decide_next_move` over a dumped trajectory with a different model —
  decision-level regression testing.
- Documented alongside 0022 in the README as the two halves of the eval stack.

## Verified (offline)

- `uv run pytest tests/test_replay.py -q` — 4 passed: the persona answers in character for the probed
  Skill; a full closed-loop Session (content-based simulated judge, no scripted score sequence)
  recovers the persona's ground-truth mastery ordering and ends the strong Candidate early after one
  question; and the replay artifact round-trips and re-runs the decision node under a swapped model.
- `uv run pytest -q` — 211 passed, `ruff check` clean.

## Verified (live, 2026-07-07 on gpt-4o-mini)

- A real closed-loop run (`run_persona_session`, persona LLM answers + real judge) for a persona
  strong at `deep_learning`, weak at `mlops`: the probed posterior ordering recovered the ground-truth
  ordering (`ml_fundamentals` > `mlops`), and the Supervisor spent the extra budget re-probing the
  *weak* Skill (`mlops` probed twice, `ml_fundamentals` once) rather than the strong one. A live
  `StructuredOutputError` on one `mlops` question was isolated as a `failed` question and the Session
  continued (issue 0014 backstop, live). The trajectory was dumped to
  `data/replay/deep-learning-strong.json` and `replay_decision` re-ran the decision node over it.

## Status

**Closed.** Acceptance criteria are implemented, offline-tested, and live-validated on gpt-4o-mini.

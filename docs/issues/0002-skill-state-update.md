# Skill-state update from an evaluation

**Type:** AFK

## What to build

The Beta-distributed **Skill** state and its pure-Python updater (see `ADR 0002`). A skill state is a Beta distribution: `mastery = α/(α+β)` and `confidence` derived from the variance. Take an evaluation produced by slice 0001 and update the relevant Skill's α/β from the `weighted_score`, then print how mastery and confidence moved. This is a deliberately no-LLM node — it demonstrates judgment about when *not* to call the model.

Correlations and priors are not in scope here (they arrive with the Diagnostic, slice 0009); this slice starts each Skill from a neutral prior and just proves the evidence-update math.

## Acceptance criteria

- [x] A skill state exposes `mastery` and `confidence` derived from α/β
- [x] Applying an evaluation shifts mastery toward the score and *increases* confidence (variance shrinks)

  > **Correction:** this holds from the neutral `Beta(1,1)` prior (`tests/test_skill.py::test_any_evaluation_increases_confidence`) but not in general: `skill.SkillState.confidence` follows the Beta variance, and evidence that contradicts a concentrated belief widens it. A score-1 evaluation applied after two score-5 evaluations lowers confidence.

- [x] A strong answer and a weak answer move mastery in opposite directions
- [x] Update is pure Python — no LLM call, deterministic, unit-tested

## Blocked by

- 0001 (needs an evaluation to consume)

## Done

Shipped in `src/interview_coach/skill.py` (`SkillState` + `apply_evaluation`), wired into the CLI
demo, and covered by `tests/test_skill.py`. Confidence is `1 − variance / variance(neutral prior)`,
so it reads 0 at the `Beta(1,1)` prior and rises as evidence concentrates the belief. It is not
monotone in the number of evaluations: evidence that contradicts a concentrated belief widens the
Beta and lowers confidence.
Also hardened the default test run to stay offline (`addopts = "-m 'not live'"`).

> **Superseded:** the CLI demo was `coach evaluate`, deleted in 4f8cdf3 (PR #133). `coach session` prints Skill states after each resolved question (`cli_session._print_live_question_update`) and at the end of the Session (`cli_session._print_session_summary`), both through `ui.render_skill_state_rows`; neither prints a before/after for one evaluation.

## Status

**Closed.** Acceptance criteria are implemented and covered.

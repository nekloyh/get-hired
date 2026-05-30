# Skill-state update from an evaluation

**Type:** AFK

## What to build

The Beta-distributed **Skill** state and its pure-Python updater (see `ADR 0002`). A skill state is a Beta distribution: `mastery = α/(α+β)` and `confidence` derived from the variance. Take an evaluation produced by slice 0001 and update the relevant Skill's α/β from the `weighted_score`, then print how mastery and confidence moved. This is a deliberately no-LLM node — it demonstrates judgment about when *not* to call the model.

Correlations and priors are not in scope here (they arrive with the Diagnostic, slice 0009); this slice starts each Skill from a neutral prior and just proves the evidence-update math.

## Acceptance criteria

- [x] A skill state exposes `mastery` and `confidence` derived from α/β
- [x] Applying an evaluation shifts mastery toward the score and *increases* confidence (variance shrinks)
- [x] A strong answer and a weak answer move mastery in opposite directions
- [x] Update is pure Python — no LLM call, deterministic, unit-tested

## Blocked by

- 0001 (needs an evaluation to consume)

## Done

Shipped in `src/interview_coach/skill.py` (`SkillState` + `apply_evaluation`), wired into the CLI
demo, and covered by `tests/test_skill.py`. Confidence is `1 − variance / variance(neutral prior)`,
so it reads 0 at the `Beta(1,1)` prior and rises monotonically as evidence concentrates the belief.
Also hardened the default test run to stay offline (`addopts = "-m 'not live'"`).
